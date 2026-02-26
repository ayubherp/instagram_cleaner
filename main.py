"""
main.py - Instagram bot cleaner
Uses user_followers_v1_chunk for paging — confirmed working instagrapi method.
"""

import time
import random
import logging
import os
from dotenv import load_dotenv
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, RateLimitError
import pyotp

from state import shared_state
from bot_detector import score_account

load_dotenv()

USERNAME     = os.environ.get("IG_USER")
PASSWORD     = os.environ.get("IG_PASS")
TWO_FA       = os.environ.get("IG_2FA_SECRET")  # optional
SESSION_FILE = "session/session.json"

# ── File logging (activity.log) ──────────────────────────────────────────────
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
    """Write to file log AND push to dashboard"""
    getattr(log, level)(message)
    shared_state.add_log(message, log_type=log_type, icon=icon)


# ── 2FA helper ───────────────────────────────────────────────────────────────

def get_totp_code(secret: str) -> str:
    return pyotp.TOTP(secret).now()


# ── Login ────────────────────────────────────────────────────────────────────

def get_client() -> Client:
    cl = Client()
    cfg = shared_state.config
    cl.delay_range = [cfg.get('delay_min', 8), cfg.get('delay_max', 20)]

    # Try saved session first (avoids repeated logins)
    if os.path.exists(SESSION_FILE):
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(USERNAME, PASSWORD)
            log_both("Logged in via saved session", log_type='success', icon='✅')
            return cl
        except LoginRequired:
            log_both("Session expired — logging in fresh...", log_type='warn', icon='⚠️', level='warning')
        except Exception as e:
            log_both(f"Session load failed: {e} — logging in fresh...", log_type='warn', icon='⚠️', level='warning')

    # Fresh login
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


# ── Main cleanup ─────────────────────────────────────────────────────────────

def run_daily_cleanup():
    cfg = shared_state.config

    if not cfg['dry_run'] and not shared_state.can_remove():
        log_both(
            f"Limit already reached today ({shared_state.removed_today}/{cfg['max_day']}). Stopping.",
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
        user_id = cl.user_id

        # ── Fetch who YOU follow (once, usually small) ───────────────────
        following     = cl.user_following(user_id, amount=0)
        following_ids = set(following.keys())

        # ── Page through followers using confirmed API ────────────────────
        # user_followers_v1_chunk(user_id, max_amount, max_id)
        # Returns: (List[UserShort], next_max_id_str)
        # Pass max_id="" to start, then pass returned max_id for next page
        # Loop ends when returned max_id is None or empty string

        PAGE_SIZE     = 200     # fetch 200 per page
        max_id        = ""      # start cursor — empty string = first page
        total_scanned = 0
        batch_count   = 0
        whitelist     = cfg.get('whitelist', [])
        seen_ids      = set()   # avoid processing duplicates across pages

        while True:

            # ── Check stop / limits ──────────────────────────────────────
            if not shared_state.running:
                log_both("Stopped by user.", log_type='info', icon='⏹')
                break

            if not cfg['dry_run'] and not shared_state.can_remove():
                limit_type = "Daily" if shared_state.removed_today >= cfg['max_day'] else "Hourly"
                log_both(f"{limit_type} limit reached — stopping.", log_type='warn', icon='🚫')
                break

            # ── Fetch one page ───────────────────────────────────────────
            try:
                users_list, next_max_id = cl.user_followers_v1_chunk(
                    user_id=user_id,
                    max_amount=PAGE_SIZE,
                    max_id=max_id
                )
            except RateLimitError:
                log_both("Rate limit hit while fetching — pausing 15 mins.", log_type='warn', icon='⚠️', level='warning')
                time.sleep(900)
                continue
            except Exception as e:
                log_both(f"Error fetching page: {e}", log_type='warn', icon='❌', level='warning')
                time.sleep(30)
                break

            if not users_list:
                log_both("All followers scanned!", log_type='success', icon='🎉')
                break

            # ── Filter candidates from this page ─────────────────────────
            candidates = [
                u for u in users_list
                if u.pk not in seen_ids
                and u.pk not in following_ids
                and u.username not in whitelist
            ]

            # Track seen to avoid duplicates
            for u in users_list:
                seen_ids.add(u.pk)

            # ── Scan + remove each candidate immediately ─────────────────
            for user in candidates:

                if not shared_state.running:
                    break

                if not cfg['dry_run'] and not shared_state.can_remove():
                    break

                try:
                    info   = cl.user_info(user.pk)
                    result = score_account(info)
                    total_scanned += 1

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
                            cl.user_remove_follower(user.pk)
                            shared_state.increment_removed()
                            log_both(
                                f"Removed @{result['username']} · "
                                f"score {result['score']} · "
                                f"{shared_state.removed_today}/{cfg['max_day']} today",
                                log_type='removed', icon='🗑️'
                            )

                        shared_state.remove_from_queue(result['username'])

                    # Random delay between every action
                    delay = random.uniform(
                        cfg.get('delay_min', 8),
                        cfg.get('delay_max', 20)
                    )
                    time.sleep(delay)

                    # Batch rest every N scans
                    batch_count += 1
                    if batch_count % cfg.get('batch_size', 5) == 0:
                        rest = random.uniform(90, 180)
                        time.sleep(rest)

                except RateLimitError:
                    log_both("Rate limit hit — pausing 15 mins.", log_type='warn', icon='⚠️', level='warning')
                    time.sleep(900)

                except Exception as e:
                    log_both(f"Error on @{user.username}: {e}", log_type='warn', icon='❌', level='warning')
                    time.sleep(10)

            # ── Advance to next page ─────────────────────────────────────
            if not next_max_id:
                log_both("All pages completed!", log_type='success', icon='🎉')
                break

            max_id = next_max_id   # pass cursor to next iteration

        log_both(
            f"Session ended · scanned {total_scanned} · removed {shared_state.removed_today}",
            log_type='success', icon='✅'
        )

    except Exception as e:
        log_both(f"Fatal error: {e}", log_type='removed', icon='💥', level='error')

    finally:
        shared_state.running = False


# ── Run standalone (without dashboard) ───────────────────────────────────────

if __name__ == "__main__":
    run_daily_cleanup()