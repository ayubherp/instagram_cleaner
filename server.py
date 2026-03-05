"""
server.py - Flask bridge between Python scripts and the dashboard
Run this instead of main.py:  python server.py
Then open:  http://localhost:5000
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import threading
import time
import json
import os
from datetime import datetime, date
from state import shared_state

app = Flask(__name__, static_folder='.')
CORS(app)

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


# ── Background loop (resets + auto-restart) ───────────────────────────────────

def background_loop():
    """
    Runs every 60 seconds:
    - Resets hourly counter at the top of every clock hour
    - Resets daily counter at midnight
    - Auto-restarts the cleaner when entering active hours if it stopped overnight
    """
    last_hour = datetime.now().hour
    last_date = date.today()

    while True:
        time.sleep(60)
        now   = datetime.now()
        today = date.today()
        cfg   = shared_state.config

        # ── Hourly reset ──────────────────────────────────────────────────
        if now.hour != last_hour:
            prev = shared_state.removed_hour
            shared_state.reset_hour_counter()
            shared_state.add_log(
                f"Hourly counter reset · was {prev} · now 0",
                log_type='info', icon='🕐'
            )
            last_hour = now.hour

        # ── Daily reset at midnight ───────────────────────────────────────
        if today != last_date:
            prev = shared_state.removed_today
            with shared_state._lock:
                shared_state.removed_today = 0
            shared_state.add_log(
                f"Daily counter reset · was {prev} · new day started",
                log_type='info', icon='📅'
            )
            last_date = today

        # ── Auto-restart when entering active hours ───────────────────────
        # Conditions: not running + inside active hours + not manually stopped
        run_from  = cfg.get('run_hour_from',  6)
        run_until = cfg.get('run_hour_until', 23)
        in_hours  = run_from <= now.hour < run_until

        if not shared_state.running and in_hours and shared_state.auto_restart:
            shared_state.add_log(
                f"Active hours started ({run_from}:00) · auto-restarting...",
                log_type='success', icon='🌅'
            )
            thread = threading.Thread(target=run_cleaner, daemon=True)
            thread.start()


# ── API Routes ───────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'dashboard.html')

@app.route('/api/state')
def get_state():
    return jsonify(shared_state.to_dict())

@app.route('/api/logs')
def get_logs():
    since = int(request.args.get('since', 0))
    return jsonify(shared_state.logs[since:])

@app.route('/api/queue')
def get_queue():
    return jsonify(shared_state.queue)

@app.route('/api/config', methods=['GET', 'POST'])
def config():
    if request.method == 'POST':
        data = request.get_json()
        shared_state.config.update(data)
        shared_state.add_log(
            f"Config updated: {data}",
            log_type='info', icon='⚙️'
        )
        return jsonify({'ok': True})
    return jsonify(shared_state.config)

@app.route('/api/start', methods=['POST'])
def start():
    if shared_state.running:
        return jsonify({'ok': False, 'msg': 'Already running'})
    data = request.get_json() or {}
    shared_state.config['dry_run'] = data.get('dry_run', True)
    shared_state.auto_restart = True  # user started it — enable auto-restart

    thread = threading.Thread(target=run_cleaner, daemon=True)
    thread.start()
    return jsonify({'ok': True})

@app.route('/api/stop', methods=['POST'])
def stop():
    shared_state.running      = False
    shared_state.auto_restart = False  # user manually stopped — don't auto-restart
    shared_state.add_log('Stop requested by user.', log_type='info', icon='⏹')
    return jsonify({'ok': True})

@app.route('/api/reset', methods=['POST'])
def reset():
    with shared_state._lock:
        shared_state.removed_hour  = 0
        shared_state.removed_today = 0
    shared_state.add_log('Counters reset.', log_type='success', icon='🔄')
    return jsonify({'ok': True})

@app.route('/api/history')
def history():
    return jsonify(shared_state.daily_history)


# ── Cleaner Runner ───────────────────────────────────────────────────────────

def run_cleaner():
    from main import run_daily_cleanup
    run_daily_cleanup()


# ── Start Server ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    bg_thread = threading.Thread(target=background_loop, daemon=True)
    bg_thread.start()

    print("\n🚀 InstaClean server running!")
    print("📊 Open dashboard: http://localhost:5000\n")
    app.run(debug=False, port=5000, threaded=True)