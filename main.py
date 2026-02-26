"""
main.py - Instagram bot cleaner (now connected to dashboard via state.py)
"""

import time
import random
import logging
import os
from dotenv import load_dotenv
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, RateLimitError

from state import shared_state
from bot_detector import score_account

load_dotenv()

USERNAME     = os.environ.get("IG_USER")
PASSWORD     = os.environ.get("IG_PASS")
SESSION_FILE = "session/session.json"

# Setup logging — writes to file AND console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("session/activity.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def log_both(message: str, log_type: str = 'info', icon: str = 'ℹ️', level='info'):
    """Log to both file logger AND the dashboard shared state"""
    getattr(log, level)(message)
    shared_state.add_log(message, log_type=log_type, icon=icon)


# ── Login ───────────────────────────────────────────────────────────────────

def get_client() -> Client:
    cl = Client()
    delay = shared_state.config.get
    cl.delay_range = [delay('delay_min', 8), delay('delay_max', 20)]

    if os.path.exists(SESSION_FILE):
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(USERNAME, PASSWORD)
            log_both("Logged in via saved session", log_type='success', icon='✅')
            return cl
        except LoginRequired:
            log_both("Session expired, logging in fresh...", log_type='warn', icon='⚠️', level='warning')

    cl.login(USERNAME, PASSWORD)
    cl.dump_settings(SESSION_FILE)
    log_both("Fresh login successful — session saved", log_type='success', icon='✅')
    return cl


# ── Main cleanup ─────────────────────────────────────────────────────────────

def run_daily_cleanup():
    cfg = shared_state.config

    if not shared_state.can_remove():
        log_both(
            f"Limit already reached (today: {shared_state.removed_today}/{cfg['max_day']}). Stopping.",
            log_type='warn', icon='🚫'
        )
        return

    shared_state.running = True
    log_both(
        f"=== Cleanup started | mode: {'DRY RUN' if cfg['dry_run'] else 'LIVE'} ===",
        log_type='success', icon='🚀'
    )
    log_both(
        f"Limits: {cfg['max_hour']}/hr · {cfg['max_day']}/day · min score: {cfg['min_score']}",
        log_type='info', icon='⚙️'
    )

    try:
        cl = get_client()
        user_id = cl.user_id

        log_both("Fetching followers...", log_type='info', icon='📡')
        followers = cl.user_followers(user_id, amount=0)

        log_both("Fetching following...", log_type='info', icon='📡')
        following = cl.user_following(user_id, amount=0)

        # Only analyze people you DON'T follow back
        whitelist = cfg.get('whitelist', [])
        candidates = {
            uid: u for uid, u in followers.items()
            if uid not in following
            and u.username not in whitelist
        }

        log_both(
            f"Found {len(candidates)} candidates to analyze",
            log_type='info', icon='👥'
        )

        batch_count = 0

        for uid, user in candidates.items():

            # Check stop signal from dashboard
            if not shared_state.running:
                log_both("Stopped by user.", log_type='info', icon='⏹')
                break

            # Check limits
            if not shared_state.can_remove():
                limit_type = "Daily" if shared_state.removed_today >= cfg['max_day'] else "Hourly"
                log_both(
                    f"{limit_type} limit reached — stopping.",
                    log_type='warn', icon='🚫'
                )
                break

            try:
                info = cl.user_info(uid)
                result = score_account(info)

                if result['score'] >= cfg['min_score']:
                    shared_state.detected += 1

                    flag_list = [k for k, v in result['flags'].items() if v]
                    bot_info = {
                        'username': result['username'],
                        'score':    result['score'],
                        'flags':    flag_list,
                    }

                    log_both(
                        f"Bot detected: @{result['username']} (score={result['score']}, flags={flag_list})",
                        log_type='detected', icon='🔍'
                    )
                    shared_state.add_to_queue(bot_info)

                    if cfg['dry_run']:
                        log_both(
                            f"[DRY RUN] Would remove @{result['username']}",
                            log_type='info', icon='🧪'
                        )
                    else:
                        cl.user_remove_follower(uid)
                        shared_state.increment_removed()
                        log_both(
                            f"Removed @{result['username']} "
                            f"(today: {shared_state.removed_today}/{cfg['max_day']}, "
                            f"hour: {shared_state.removed_hour}/{cfg['max_hour']})",
                            log_type='removed', icon='🗑️'
                        )

                    shared_state.remove_from_queue(result['username'])

                # Random delay between actions
                delay = random.uniform(cfg.get('delay_min', 8), cfg.get('delay_max', 20))
                time.sleep(delay)

                # Batch rest
                batch_count += 1
                if batch_count % cfg.get('batch_size', 5) == 0:
                    rest = random.uniform(60, 120)
                    log_both(f"Batch rest: {rest:.0f}s...", log_type='info', icon='⏸')
                    time.sleep(rest)

            except RateLimitError:
                log_both("Rate limit hit! Sleeping 15 minutes...", log_type='warn', icon='⚠️', level='warning')
                time.sleep(900)

            except Exception as e:
                log_both(f"Error on @{user.username}: {e}", log_type='warn', icon='❌', level='warning')
                time.sleep(10)

        log_both(
            f"=== Done. Removed {shared_state.removed_today} today ===",
            log_type='success', icon='✅'
        )

    except Exception as e:
        log_both(f"Fatal error: {e}", log_type='removed', icon='💥', level='error')

    finally:
        shared_state.running = False


# ── Run standalone (without dashboard) ──────────────────────────────────────

if __name__ == "__main__":
    run_daily_cleanup()