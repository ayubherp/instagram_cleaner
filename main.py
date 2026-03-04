"""
main.py - Instagram bot cleaner

Flow:
  Step 1 — Fetch ALL following via user_following_v1 → save to following_cache.json.
            Fully completes before anything else starts. Re-fetches if cache is empty.
  Step 2 — Fetch followers in batches of 200 via user_followers_v1_chunk.
            Each batch is immediately filtered (mutuals + whitelist) and appended
            to followers_cache.json. Resumes from cursor on restart.
  Step 3 — Bot scanning starts once pending candidates >= BOT_SCAN_THRESHOLD (700),
            or when follower fetch is fully complete. Interleaves with Step 2.

Time window:
  - Checked at startup, inside the main fetch loop, and inside each scan loop.
  - Configurable via run_hour_from / run_hour_until in config (default 8–23).

Restart safety:
  - following_cache.json  → re-used if non-empty, otherwise re-fetched
  - followers_cache.json  → resumes from saved cursor; scanned_pks prevents re-adding
  - Delete both files to start completely fresh
"""

import time
import random
import logging
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, RateLimitError
import pyotp

from state import shared_state
from bot_detector import score_account

load_dotenv()

USERNAME           = os.environ.get("IG_USER")
PASSWORD           = os.environ.get("IG_PASS")
TWO_FA             = os.environ.get("IG_2FA_SECRET")
SESSION_FILE       = "session/session.json"
FOLLOWING_CACHE    = "session/following_cache.json"
FOLLOWERS_CACHE    = "session/followers_cache.json"

BOT_SCAN_THRESHOLD = 700  # start scanning once this many candidates are cached

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs("session", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("session/activity.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def log_both(message: str, log_type: str = 'info', icon: str = 'ℹ️', level: str = 'info'):
    getattr(log, level)(message)
    shared_state.add_log(message, log_type=log_type, icon=icon)


def in_active_hours(cfg: dict) -> bool:
    """Returns True if current hour is within run_hour_from and run_hour_until."""
    now       = datetime.now().hour
    run_from  = cfg.get('run_hour_from',  8)
    run_until = cfg.get('run_hour_until', 23)
    return run_from <= now < run_until


# ── 2FA ───────────────────────────────────────────────────────────────────────

def get_totp_code(secret: str) -> str:
    return pyotp.TOTP(secret).now()


# ── Login ─────────────────────────────────────────────────────────────────────

def get_client() -> Client:
    cl = Client()
    cfg = shared_state.config
    cl.delay_range = [cfg.get('delay_min', 3), cfg.get('delay_max', 8)]

    if os.path.exists(SESSION_FILE):
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(USERNAME, PASSWORD)
            log_both("Logged in via saved session", log_type='success', icon='✅')
            return cl
        except LoginRequired:
            log_both("Session expired — logging in fresh...", log_type='warn', icon='⚠️', level='warning')
        except Exception as e:
            log_both(f"Session load failed: {e}", log_type='warn', icon='⚠️', level='warning')

    try:
        if TWO_FA:
            cl.login(USERNAME, PASSWORD, verification_code=get_totp_code(TWO_FA))
        else:
            cl.login(USERNAME, PASSWORD)
    except Exception as e:
        log_both(f"Login failed: {e}", log_type='removed', icon='💥', level='error')
        raise

    cl.dump_settings(SESSION_FILE)
    log_both("Fresh login successful — session saved", log_type='success', icon='✅')
    return cl


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Following cache
# Fetched once via user_following_v1. Must fully complete before Step 2 begins.
# ══════════════════════════════════════════════════════════════════════════════

def get_following_pks(cl, user_id) -> set:
    """
    Returns the full set of following PKs.
    Loads from cache when non-empty. Re-fetches if missing or empty (invalid).
    Only writes cache AFTER the full result is in hand — no partial saves.
    """
    if os.path.exists(FOLLOWING_CACHE):
        try:
            with open(FOLLOWING_CACHE) as f:
                data = json.load(f)
            pks = data.get("pks", [])
            if len(pks) > 0:
                log_both(
                    f"Step 1 · Following cache loaded ✓ · {len(pks)} accounts · "
                    f"mutuals will be filtered from followers",
                    log_type='success', icon='✅'
                )
                return set(pks)
            else:
                log_both(
                    "Step 1 · Following cache was empty — deleting and re-fetching...",
                    log_type='warn', icon='⚠️', level='warning'
                )
                os.remove(FOLLOWING_CACHE)
        except Exception as e:
            log_both(
                f"Step 1 · Following cache read failed ({e}) — re-fetching...",
                log_type='warn', icon='⚠️', level='warning'
            )

    log_both(
        "Step 1 · Fetching all following accounts — completes fully before follower fetch starts...",
        log_type='info', icon='📡'
    )

    following = cl.user_following_v1(user_id, amount=0)
    pks = [u.pk for u in following]

    if len(pks) > 0:
        with open(FOLLOWING_CACHE, "w") as f:
            json.dump({"pks": pks}, f)
        log_both(
            f"Step 1 · Following fetched & cached ✓ · {len(pks)} accounts · "
            f"starting follower fetch now",
            log_type='success', icon='💾'
        )
    else:
        log_both(
            "Step 1 · Warning: following list returned 0 — mutual filtering may not work!",
            log_type='warn', icon='⚠️', level='warning'
        )

    return set(pks)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Followers cache
# Fetched in batches of 200. Mutuals filtered per batch. Appended to cache.
# ══════════════════════════════════════════════════════════════════════════════

def load_followers_cache() -> dict:
    """
    {
        "fetch_complete": bool,
        "next_max_id":    str,         # "" = start from beginning
        "scanned_count":  int,
        "total_fetched":  int,
        "scanned_pks":    [int, ...],  # PKs already scanned — prevents re-adding on resume
        "pending":        [{"pk": int, "username": str}, ...]
    }
    """
    if os.path.exists(FOLLOWERS_CACHE):
        try:
            with open(FOLLOWERS_CACHE) as f:
                data = json.load(f)
            # backfill scanned_pks if missing (old cache format)
            if "scanned_pks" not in data:
                data["scanned_pks"] = []
            return data
        except Exception as e:
            log.warning(f"Followers cache read failed: {e}")
    return {
        "fetch_complete": False,
        "next_max_id":    "",
        "scanned_count":  0,
        "total_fetched":  0,
        "scanned_pks":    [],
        "pending":        []
    }


def save_followers_cache(cache: dict):
    with open(FOLLOWERS_CACHE, "w") as f:
        json.dump(cache, f)


def fetch_one_follower_batch(cl, user_id, max_id: str,
                              following_pks: set, whitelist: list,
                              seen_pks: set) -> tuple:
    """
    Fetches one page (~200) via user_followers_v1_chunk.
    Filters mutuals and whitelisted accounts. Updates seen_pks in-place.
    Returns (new_candidates, next_max_id_str, raw_page_count, skipped_mutuals).
    """
    users, next_max_id = cl.user_followers_v1_chunk(
        user_id, max_amount=200, max_id=max_id
    )

    new_candidates  = []
    skipped_mutuals = 0
    for u in users:
        if u.pk in seen_pks:
            continue
        seen_pks.add(u.pk)
        if u.pk in following_pks:
            skipped_mutuals += 1
            continue
        if u.username in whitelist:
            continue
        new_candidates.append({"pk": u.pk, "username": u.username})

    return new_candidates, (next_max_id or ""), len(users), skipped_mutuals


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Bot scanning
# ══════════════════════════════════════════════════════════════════════════════

def scan_and_remove_bots(cl, followers_cache: dict, cfg: dict) -> tuple:
    """
    Scans all current pending candidates. Removes bots.
    Returns (updated_cache, count_scanned_this_round).
    """
    pending       = followers_cache["pending"]
    scanned_count = followers_cache["scanned_count"]
    scanned_pks   = followers_cache["scanned_pks"]
    batch_count   = 0
    scanned_round = 0

    remaining = list(pending)  # snapshot — new arrivals from fetch won't interfere

    for user in remaining:
        pk       = user["pk"]
        username = user["username"]

        if not shared_state.running:
            log_both("Stopped by user.", log_type='info', icon='⏹')
            break

        # ── Time window check (place 2 of 3) ─────────────────────────────────
        if not in_active_hours(cfg):
            log_both(
                f"Outside active hours ({cfg.get('run_hour_from', 8)}:00–"
                f"{cfg.get('run_hour_until', 23)}:00) · pausing until next window",
                log_type='info', icon='🕐'
            )
            shared_state.running = False
            break

        if not cfg['dry_run'] and not shared_state.can_remove():
            limit_type = "Daily" if shared_state.removed_today >= cfg['max_day'] else "Hourly"
            log_both(f"{limit_type} limit reached — stopping.", log_type='warn', icon='🚫')
            break

        try:
            info   = cl.user_info(pk)
            result = score_account(info, cfg)

            scanned_round += 1
            scanned_count += 1

            # Mark as scanned — remove from pending, record pk so it's never re-added
            pending = [u for u in pending if u["pk"] != pk]
            scanned_pks.append(pk)
            followers_cache["pending"]       = pending
            followers_cache["scanned_count"] = scanned_count
            followers_cache["scanned_pks"]   = scanned_pks

            if result['score'] >= cfg['min_score']:
                shared_state.detected += 1
                flag_list = [k for k, v in result['flags'].items() if v]

                shared_state.add_to_queue({
                    'username': result['username'],
                    'score':    result['score'],
                    'flags':    flag_list,
                })

                if cfg['dry_run']:
                    log_both(
                        f"[DRY RUN] @{result['username']} · "
                        f"score {result['score']} · {flag_list}",
                        log_type='detected', icon='🧪'
                    )
                else:
                    cl.user_remove_follower(pk)
                    shared_state.increment_removed()
                    log_both(
                        f"Removed @{result['username']} · "
                        f"score {result['score']} · "
                        f"{shared_state.removed_today}/{cfg['max_day']} today",
                        log_type='removed', icon='🗑️'
                    )

                shared_state.remove_from_queue(result['username'])

            save_followers_cache(followers_cache)

            time.sleep(random.uniform(cfg.get('delay_min', 3), cfg.get('delay_max', 8)))

            batch_count += 1
            if batch_count % cfg.get('batch_size', 5) == 0:
                rest = random.uniform(cfg.get('batch_rest_min', 45), cfg.get('batch_rest_max', 90))
                log_both(f"Batch rest {rest:.0f}s...", log_type='info', icon='💤')
                time.sleep(rest)

        except RateLimitError:
            log_both("Rate limit hit — pausing 15 mins.", log_type='warn', icon='⚠️', level='warning')
            save_followers_cache(followers_cache)
            time.sleep(900)

        except Exception as e:
            log_both(f"Error on @{username}: {e}", log_type='warn', icon='❌', level='warning')
            time.sleep(10)

    return followers_cache, scanned_round


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run_daily_cleanup():
    cfg = shared_state.config

    # ── Time window check (place 1 of 3) ─────────────────────────────────────
    if not in_active_hours(cfg):
        log_both(
            f"Outside active hours ({cfg.get('run_hour_from', 8)}:00–"
            f"{cfg.get('run_hour_until', 23)}:00) · not starting",
            log_type='info', icon='🕐'
        )
        shared_state.running = False
        return

    if not cfg['dry_run'] and not shared_state.can_remove():
        log_both(
            f"Daily limit already reached ({shared_state.removed_today}/{cfg['max_day']}). Stopping.",
            log_type='warn', icon='🚫'
        )
        shared_state.running = False
        return

    shared_state.running = True

    log_both(
        f"Session started · {'DRY RUN' if cfg['dry_run'] else 'LIVE'} · "
        f"limit {cfg['max_hour']}/hr · {cfg['max_day']}/day · score ≥ {cfg['min_score']} · "
        f"active hours {cfg.get('run_hour_from', 8)}:00–{cfg.get('run_hour_until', 23)}:00",
        log_type='success', icon='🚀'
    )

    try:
        cl        = get_client()
        user_id   = cl.user_id
        whitelist = cfg.get('whitelist', [])

        # ── STEP 1: Get following PKs — blocks until fully complete ───────────
        following_pks = get_following_pks(cl, user_id)

        # ── STEP 2 + 3: Batch-fetch followers, filter, cache, scan ───────────
        followers_cache = load_followers_cache()
        fetch_complete  = followers_cache.get("fetch_complete", False)
        max_id          = followers_cache.get("next_max_id", "")
        follower_page   = 0
        total_scanned   = 0

        # seen_pks = pending + already-scanned — prevents re-adding any pk on resume
        seen_follower_pks = (
            set(u["pk"] for u in followers_cache["pending"]) |
            set(followers_cache.get("scanned_pks", []))
        )

        if fetch_complete:
            log_both(
                f"Step 2 · Follower fetch already complete · "
                f"{followers_cache['total_fetched']} fetched · "
                f"{len(followers_cache['pending'])} pending scan",
                log_type='success', icon='⚡'
            )
        else:
            log_both(
                "Step 2 · Fetching followers in batches of 200"
                + (" · resuming from cursor" if max_id else ""),
                log_type='info', icon='📡'
            )

        while shared_state.running:

            # ── Time window check (place 3 of 3) ─────────────────────────────
            if not in_active_hours(cfg):
                log_both(
                    f"Outside active hours ({cfg.get('run_hour_from', 8)}:00–"
                    f"{cfg.get('run_hour_until', 23)}:00) · stopping for the night",
                    log_type='info', icon='🕐'
                )
                break

            # ── Fetch next follower batch ─────────────────────────────────────
            if not fetch_complete:
                try:
                    new_candidates, next_max_id, raw_count, skipped_mutuals = fetch_one_follower_batch(
                        cl, user_id, max_id, following_pks, whitelist, seen_follower_pks
                    )

                    followers_cache["total_fetched"] += raw_count
                    followers_cache["pending"].extend(new_candidates)
                    followers_cache["next_max_id"] = next_max_id
                    follower_page += 1

                    is_done = not bool(next_max_id)
                    if is_done:
                        followers_cache["fetch_complete"] = True
                        fetch_complete = True
                        log_both(
                            f"Step 2 · Follower fetch complete ✓ · "
                            f"{followers_cache['total_fetched']} total fetched · "
                            f"{skipped_mutuals} mutuals skipped this page · "
                            f"{len(followers_cache['pending'])} candidates pending",
                            log_type='success', icon='🎉'
                        )
                    else:
                        max_id = next_max_id
                        log_both(
                            f"Step 2 · Follower page {follower_page} · "
                            f"+{len(new_candidates)} candidates · "
                            f"{skipped_mutuals} mutuals skipped · "
                            f"{len(followers_cache['pending'])} pending · "
                            f"{followers_cache['total_fetched']} fetched total",
                            log_type='info', icon='📥'
                        )

                    save_followers_cache(followers_cache)
                    time.sleep(random.uniform(2, 5))

                except RateLimitError:
                    log_both("Rate limit during follower fetch — pausing 15 mins.", log_type='warn', icon='⚠️', level='warning')
                    save_followers_cache(followers_cache)
                    time.sleep(900)
                    continue
                except Exception as e:
                    log_both(f"Error fetching follower batch: {e}", log_type='warn', icon='❌', level='warning')
                    time.sleep(15)
                    continue

            # ── Scan bots if threshold met or fetch is done ───────────────────
            pending_count = len(followers_cache["pending"])
            should_scan   = fetch_complete or (pending_count >= BOT_SCAN_THRESHOLD)

            if should_scan and pending_count > 0:
                log_both(
                    f"Step 3 · Scanning {pending_count} candidates "
                    + ("(fetch complete)" if fetch_complete else f"(≥{BOT_SCAN_THRESHOLD} threshold met)"),
                    log_type='info', icon='🔍'
                )
                followers_cache, scanned = scan_and_remove_bots(cl, followers_cache, cfg)
                total_scanned += scanned

                if not shared_state.running:
                    break

            # ── All done? ─────────────────────────────────────────────────────
            if fetch_complete and len(followers_cache["pending"]) == 0:
                log_both(
                    "All candidates scanned! Delete cache files to start fresh next time.",
                    log_type='success', icon='🎉'
                )
                break

            if not fetch_complete:
                continue

            break

        # ── Session summary ───────────────────────────────────────────────────
        log_both(
            f"Session ended · scanned {total_scanned} this session · "
            f"removed {shared_state.removed_today} today · "
            f"{len(followers_cache.get('pending', []))} still in candidate queue",
            log_type='success', icon='✅'
        )

    except Exception as e:
        log_both(f"Fatal error: {e}", log_type='removed', icon='💥', level='error')

    finally:
        shared_state.running = False


# ── Run standalone (without dashboard) ───────────────────────────────────────

if __name__ == "__main__":
    run_daily_cleanup()