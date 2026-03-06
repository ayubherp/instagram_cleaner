"""
state.py - Shared state between server.py and main.py
Both files import this so the dashboard always reflects real data.
"""

import json
import os
from datetime import datetime, date
from threading import Lock


class SharedState:
    def __init__(self):
        self._lock = Lock()

        # Counters
        self.removed_today = 0
        self.removed_hour  = 0
        self.detected      = 0
        self.running       = False
        self.auto_restart  = False  # set True when user presses Start

        # Data
        self.logs          = []   # list of log dicts
        self.queue         = []   # list of bot dicts currently pending
        self.daily_history = self._load_history()

        # Config (matches config.py — overridable from dashboard)
        self.config = {
            "max_hour":                77,
            "max_day":                 1077,
            "min_score":               3,
            "dry_run":                 False,
            "delay_min":               4,
            "delay_max":               8,
            "batch_size":              10,
            "batch_rest_min":          30,
            "batch_rest_max":          60,
            "whitelist":               [],
            "follow_ratio_multiplier": 4.0,  # following >= N × followers → bot flag
            "run_hour_from":           6,    # active window start (24h)
            "run_hour_until":          23,   # active window end (24h)
        }

    # ── Logging ────────────────────────────────────────────────────────────

    def add_log(self, message: str, log_type: str = 'info', icon: str = 'ℹ️'):
        with self._lock:
            entry = {
                "id":      len(self.logs),
                "time":    datetime.now().strftime('%H:%M:%S'),
                "message": message,
                "type":    log_type,   # info | detected | removed | success | warn
                "icon":    icon,
            }
            self.logs.append(entry)
            # Keep last 500 logs only
            if len(self.logs) > 500:
                self.logs = self.logs[-500:]

    # ── Queue ──────────────────────────────────────────────────────────────

    def add_to_queue(self, user: dict):
        with self._lock:
            self.queue.append(user)

    def remove_from_queue(self, username: str):
        with self._lock:
            self.queue = [u for u in self.queue if u['username'] != username]

    # ── Counters ───────────────────────────────────────────────────────────

    def increment_removed(self):
        with self._lock:
            self.removed_today += 1
            self.removed_hour  += 1
            # Update today's history entry
            today_str = str(date.today())
            if self.daily_history and self.daily_history[-1]['date'] == today_str:
                self.daily_history[-1]['count'] += 1
            else:
                self.daily_history.append({'date': today_str, 'count': 1})
            self._save_history()

    def reset_hour_counter(self):
        with self._lock:
            self.removed_hour = 0

    # ── Limits ─────────────────────────────────────────────────────────────

    def can_remove(self) -> bool:
        return (
            self.removed_today < self.config['max_day'] and
            self.removed_hour  < self.config['max_hour']
        )

    # ── Serialization ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "removed_today":   self.removed_today,
            "removed_hour":    self.removed_hour,
            "detected":        self.detected,
            "running":         self.running,
            "queue_size":      len(self.queue),
            "config":          self.config,
            "log_count":       len(self.logs),
            "daily_history":   self.daily_history[-7:],  # last 7 days
        }

    # ── History persistence ────────────────────────────────────────────────

    def _load_history(self) -> list:
        path = "session/history.json"
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_history(self):
        os.makedirs("session", exist_ok=True)
        with open("session/history.json", "w") as f:
            json.dump(self.daily_history, f)


# Single global instance — import this everywhere
shared_state = SharedState()