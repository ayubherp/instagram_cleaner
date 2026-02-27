"""
main.py - Instagram bot cleaner
 
Cache strategy:
- Fetches all followers ONCE, saves to cache permanently
- Tracks scan position — restart continues exactly where stopped
- Removed users deleted from cache immediately
- Cache only refreshes when ALL candidates are scanned (empty)
- Or manually: delete session/followers_cache.json to force refresh
- Never expires by date — perfect for laptop on/off usage
"""

import time
import random
import logging
import os
import json
from dotenv import load_dotenv
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, RateLimitError
import pyotp

from state import shared_state
from bot_detector import score_account

load_dotenv()

USERNAME     = os.environ.get("IG_USER")
PASSWORD     = os.environ.get("IG_PASS")
TWO_FA       = os.environ.get("IG_2FA_SECRET")
SESSION_FILE = "session/session.json"
CACHE_FILE   = "session/followers_cache.json"

# ── Logging ──────────────────────────────────────────────────────────────────
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


# ── 2FA ──────────────────────────────────────────────────────────────────────

def get_totp_code(secret: str) -> str:
    return pyotp.TOTP(secret).now()


# ── Login ─────────────────────────────────────────────────────────────────────

def get_client() -> Client:
    cl = Client()
    cfg = shared_state.config
    cl.delay_range = [cfg.get('delay_min', 8), cfg.get('delay_max', 20)]

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


# ── Cache helpers ─────────────────────────────────────────────────────────────

def load_cache() -> dict | None:
    """
    Load cache from disk.
    Returns dict with 'pending' and 'scanned_count' or None if not found.
    """
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Cache read failed: {e}")
        return None


def save_cache(pending: list, scanned_count: int, total_fetched: int):
    """Save full cache state to disk"""
    data = {
        "total_fetched":  total_fetched,   # original total when first fetched
        "scanned_count":  scanned_count,   # how many scanned so far (all time)
        "pending":        pending,         # remaining unscanned candidates
    }
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)


def update_cache_progress(pending: list, scanned_count: int, total_fetched: int):
    """Update cache after each scan — saves position for restart"""
    save_cache(pending, scanned_count, total_fetched)


def remove_from_cache(pk, pending: list, scanned_count: int, total_fetched: int):
    """Remove a user from cache immediately after removal"""
    updated = [u for u in pending if u["pk"] != pk]
    save_cache(updated, scanned_count, total_fetched)
    return updated


def clear_cache():
    """Delete cache to force a fresh fetch next run"""
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
        log_both("Cache cleared — will re-fetch on next run", log_type='info', icon='🔄')


# ── Main cleanup ──────────────────────────────────────────────────────────────

def run_daily_cleanup():
    cfg = shared_state.config

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
        f"limit {cfg['max_hour']}/hr · {cfg['max_day']}/day · score ≥ {cfg['min_score']}",
        log_type='success', icon='🚀'
    )

    try:
        cl = get_client()
        user_id   = cl.user_id
        whitelist = cfg.get('whitelist', [])

        # ── Step 1: Load cache OR fetch fresh ────────────────────────────
        cache = load_cache()

        if cache and len(cache.get("pending", [])) > 0:
            # ── Resume from cache ─────────────────────────────────────
            pending       = cache["pending"]
            scanned_count = cache.get("scanned_count", 0)
            total_fetched = cache.get("total_fetched", len(pending))

            log_both(
                f"Resuming from cache ⚡ · {len(pending)} remaining · "
                f"{scanned_count} already scanned · "
                f"{total_fetched} total fetched",
                log_type='success', icon='⚡'
            )

        else:
            # ── Fresh fetch ───────────────────────────────────────────
            if cache and len(cache.get("pending", [])) == 0:
                log_both(
                    "All previous candidates scanned! Fetching fresh follower list...",
                    log_type='info', icon='🔄'
                )
            else:
                log_both(
                    "No cache found — fetching all followers from Instagram...",
                    log_type='info', icon='📡'
                )

            # Fetch following to filter mutuals
            following = cl.user_following_v1(user_id, amount=0)
            following_ids = set(u.pk for u in following)

            # Fetch ALL followers (runs once, then cached)
            log_both(
                "Fetching all followers — this runs once then is cached forever until complete...",
                log_type='info', icon='📡'
            )
            all_followers = cl.user_followers_v1(user_id, amount=0)

            # Build unique candidate list (dict keys = unique PKs)
            seen_pks = set()
            pending  = []
            for u in all_followers:
                if u.pk in following_ids:
                    continue
                if u.username in whitelist:
                    continue
                if u.pk in seen_pks:        # ← skip duplicate
                    continue
                seen_pks.add(u.pk)
                pending.append({"pk": u.pk, "username": u.username})

            total_fetched = len(all_followers)
            scanned_count = 0

            # Save to cache immediately
            save_cache(pending, scanned_count, total_fetched)

            log_both(
                f"Fetched {total_fetched} followers · "
                f"{len(pending)} candidates saved to cache · "
                f"{total_fetched - len(pending)} skipped (mutual/whitelisted)",
                log_type='success', icon='💾'
            )

        # ── Step 2: Scan + remove from pending list ───────────────────────
        total_scanned_this_session = 0
        batch_count = 0

        # Work on a copy — we'll update pending as we go
        remaining = list(pending)

        for user in remaining:
            pk       = user["pk"]
            username = user["username"]

            # Check stop signal
            if not shared_state.running:
                log_both("Stopped by user.", log_type='info', icon='⏹')
                break

            # Check limits
            if not cfg['dry_run'] and not shared_state.can_remove():
                limit_type = "Daily" if shared_state.removed_today >= cfg['max_day'] else "Hourly"
                log_both(f"{limit_type} limit reached — stopping.", log_type='warn', icon='🚫')
                break

            try:
                info   = cl.user_info(pk)
                result = score_account(info)

                total_scanned_this_session += 1
                scanned_count += 1

                # Remove from pending (mark as scanned regardless of score)
                pending = [u for u in pending if u["pk"] != pk]

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

                # Save progress to cache after every scan
                # So restart picks up exactly here
                update_cache_progress(pending, scanned_count, total_fetched)

                # Random delay
                delay = random.uniform(
                    cfg.get('delay_min', 8),
                    cfg.get('delay_max', 20)
                )
                time.sleep(delay)

                # Batch rest
                batch_count += 1
                if batch_count % cfg.get('batch_size', 5) == 0:
                    rest = random.uniform(90, 180)
                    time.sleep(rest)

            except RateLimitError:
                log_both("Rate limit hit — pausing 15 mins.", log_type='warn', icon='⚠️', level='warning')
                # Save progress before long pause
                update_cache_progress(pending, scanned_count, total_fetched)
                time.sleep(900)

            except Exception as e:
                log_both(f"Error on @{username}: {e}", log_type='warn', icon='❌', level='warning')
                time.sleep(10)

        # ── Check if fully complete ───────────────────────────────────────
        if len(pending) == 0 and shared_state.running:
            log_both(
                "All candidates scanned! Cache will refresh on next run.",
                log_type='success', icon='🎉'
            )
            # Save empty cache — signals fresh fetch next run
            save_cache([], scanned_count, total_fetched)

        # ── Session summary ───────────────────────────────────────────────
        log_both(
            f"Session ended · scanned {total_scanned_this_session} this session · "
            f"removed {shared_state.removed_today} today · "
            f"{len(pending)} still remaining in cache",
            log_type='success', icon='✅'
        )

    except Exception as e:
        log_both(f"Fatal error: {e}", log_type='removed', icon='💥', level='error')

    finally:
        shared_state.running = False


# ── Run standalone (without dashboard) ───────────────────────────────────────

if __name__ == "__main__":
    run_daily_cleanup()