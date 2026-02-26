"""
server.py - Flask bridge between Python scripts and the dashboard
Run this instead of main.py:  python server.py
Then open:  http://localhost:5000
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import threading
import json
import os
from datetime import datetime, date
from state import shared_state

app = Flask(__name__, static_folder='.')
CORS(app)

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # only show errors, not every GET request

# ── API Routes ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'dashboard.html')

@app.route('/api/state')
def get_state():
    """Dashboard polls this every 2 seconds to update UI"""
    return jsonify(shared_state.to_dict())

@app.route('/api/logs')
def get_logs():
    """Returns activity log entries"""
    since = int(request.args.get('since', 0))
    return jsonify(shared_state.logs[since:])

@app.route('/api/queue')
def get_queue():
    """Returns current bot queue"""
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

    # Run cleaner in background thread
    thread = threading.Thread(target=run_cleaner, daemon=True)
    thread.start()
    return jsonify({'ok': True})

@app.route('/api/stop', methods=['POST'])
def stop():
    shared_state.running = False
    shared_state.add_log('Stop requested by user.', log_type='info', icon='⏹')
    return jsonify({'ok': True})

@app.route('/api/reset', methods=['POST'])
def reset():
    shared_state.removed_hour = 0
    shared_state.removed_today = 0
    shared_state.add_log('Counters reset.', log_type='success', icon='🔄')
    return jsonify({'ok': True})

@app.route('/api/history')
def history():
    return jsonify(shared_state.daily_history)

# ── Cleaner Runner ──────────────────────────────────────────────────────────

def run_cleaner():
    """Runs the actual Instagram bot removal logic"""
    from main import run_daily_cleanup
    run_daily_cleanup()

# ── Start Server ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\n🚀 InstaClean server running!")
    print("📊 Open dashboard: http://localhost:5000\n")
    app.run(debug=False, port=5000, threaded=True)