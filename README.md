# 🤖 InstaClean — Instagram Bot Follower Remover

A Python tool to detect and remove bot/fake followers from your Instagram account, with a live web dashboard.

> ⚠️ **Disclaimer:** This tool uses an unofficial Instagram API (`instagrapi`). Use at your own risk. Always start with Dry Run mode. The author is not responsible for any account actions taken by Instagram.

---

## ✨ Features

- 🖥️ Live web dashboard — monitor everything in real time
- 🧪 Dry Run mode — scan without removing anyone
- 🎯 Bot scoring system with 12 detection flags
- ⏱️ Hourly & daily removal limits with auto-reset
- 🕐 Active hours window — stops at night, auto-restarts in the morning
- 🔄 Resumable — restart anytime and continue exactly where it stopped
- 💾 Smart cache — following list and follower batches cached locally
- 🛡️ Mutual filtering — never removes people you follow back
- 📊 7-day removal history chart
- 📋 Real-time activity log

---

## 📁 Project Structure

```
instagram_cleaner/
├── server.py          # Flask web server — run this to start everything
├── main.py            # Core bot removal logic
├── state.py           # Shared state between server and cleaner
├── bot_detector.py    # Bot scoring algorithm
├── rate_limiter.py    # (legacy, no longer used)
├── dashboard.html     # Visual dashboard UI
├── .env               # Your credentials (never commit this!)
├── .gitignore
└── session/           # Auto-created at runtime
    ├── session.json           # Saved Instagram login session
    ├── following_cache.json   # Cached following list (for mutual filtering)
    ├── followers_cache.json   # Cached follower batches + scan progress
    ├── history.json           # 7-day removal history
    └── activity.log           # Full activity log
```

---

## 🚀 Setup

### 1. Requirements

- Python 3.10 or higher
- pip

```bash
python --version
```

---

### 2. Install Dependencies

```bash
pip install flask flask-cors instagrapi python-dotenv pyotp
```

---

### 3. Create `.env` File

```bash
# Windows PowerShell
New-Item .env -Type File

# Mac/Linux
touch .env
```

Add your credentials:
```
IG_USER=your_instagram_username
IG_PASS=your_instagram_password
IG_2FA_SECRET=your_2fa_secret   # only if you use 2FA (TOTP)
```

> 🔒 Never share or commit your `.env` file. It is already in `.gitignore`.

> For `IG_2FA_SECRET`: this is the secret key from your authenticator app setup (the string you scan as a QR code). Not the 6-digit code.

---

### 4. Configure Settings

All settings live in `state.py` under `self.config`. You can also change them live from the dashboard without restarting.

```python
self.config = {
    "max_hour":                100,    # max removals per hour
    "max_day":                 2000,   # max removals per day
    "min_score":               3,      # bot score threshold (1–12)
    "dry_run":                 True,   # True = scan only, no removals
    "delay_min":               4,      # min seconds between scans
    "delay_max":               12,     # max seconds between scans
    "batch_size":              10,     # scans before taking a batch rest
    "batch_rest_min":          30,     # min batch rest seconds
    "batch_rest_max":          60,    # max batch rest seconds
    "whitelist":               [],     # usernames to never remove
    "follow_ratio_multiplier": 4.0,    # following >= N×followers = bot flag
    "run_hour_from":           7,      # active window start (24h)
    "run_hour_until":          23,     # active window end (24h)
}
```

---

### 5. Run

```bash
python server.py
```

Open your browser:
```
http://localhost:5000
```

---

## 🎮 How to Use

### Step 1 — Dry Run First
`dry_run` is `True` by default. Press **Start Cleaning**. The tool scans followers and logs detected bots — **no one is removed.**

### Step 2 — Review
Watch the Activity Log. Do the detected accounts look like real bots? If yes, scoring is working correctly.

### Step 3 — Adjust Score Threshold
- `min_score: 2` → aggressive, catches more, small false positive risk
- `min_score: 3` → balanced (recommended default)
- `min_score: 4` → conservative, only obvious bots

### Step 4 — Go Live
Toggle **Live Mode** in the dashboard (or set `dry_run: False` in `state.py`), then press **Start Cleaning**.

---

## 🔄 How the Process Works

```
Step 1 — Fetch following list (user_following_v1)
         Saved to following_cache.json. Re-used on restart.
         Must complete fully before Step 2 begins.
         ↓
Step 2 — Fetch followers in batches of 200 (user_followers_v1_chunk)
         Each batch: filter out mutuals + whitelisted → save to followers_cache.json
         Resumes from cursor if interrupted.
         ↓
Step 3 — Bot scanning starts when pending candidates ≥ 700 OR fetch is complete
         Reads from local cache only — no repeated API follower fetches
         Scans each account with user_info() → scores → removes if above threshold
```

**Cache behavior:**
- Delete `session/following_cache.json` → re-fetches your following list next run
- Delete `session/followers_cache.json` → starts follower fetch from scratch
- Delete both → full fresh start

---

## 🎯 Bot Detection Flags

Each flag adds **+1** to the bot score. Account is removed if score ≥ `min_score`.

| Flag | What It Checks |
|------|----------------|
| `no_profile_pic` | No profile photo |
| `zero_posts` | 0 posts ever |
| `private_no_posts` | Private account with 0 posts |
| `no_bio` | Empty biography |
| `very_new_account` | < 3 posts AND < 10 followers |
| `follow_bomb` | Following > 500 but < 100 followers |
| `mass_follower` | Following > 2500 (near Instagram limit) |
| `high_follow_ratio` | Following ≥ N × followers (default 2×) |
| `full_ghost` | No bio + no pic + no posts (very high confidence) |
| `pure_follow_bot` | Following > 1000 but < 50 followers (very high confidence) |
| `numeric_suffix` | Username ends in 4+ digits e.g. `user48291` |
| `random_chars` | Username looks auto-generated e.g. `xk9m3az` |

**Max possible score: 12**

---

## 📈 Recommended Ramp-Up Plan

| Week | Mode | max_day | max_hour |
|------|------|---------|----------|
| Week 1–2 | Dry Run | — | — |
| Week 3 | Live | 300 | 40 |
| Week 4 | Live | 500 | 60 |
| Week 5+ | Live | 700 | 80 |

> Never jump straight to high limits, especially on a new IP (VPS). Instagram flags sudden behavioral spikes.

---

## 🛡️ Safety Features

- ✅ Random delays between every action
- ✅ Batch resting (pauses every N scans)
- ✅ Hourly + daily hard limits with automatic reset
- ✅ Active hours window — stops at night, auto-restarts in the morning
- ✅ Mutual filtering — never removes people you follow back
- ✅ Whitelist support
- ✅ Resumable from exact position on restart
- ✅ Rate limit detection with 15-min auto-pause
- ✅ Session reuse — avoids repeated logins

---

## ⚠️ Stop Immediately If You See

- "Action Blocked" on Instagram
- Phone number verification request
- Forced login / checkpoint
- Follower count stops updating

If any of these happen: stop the script, lower your limits, wait 24–48 hours.

---

## 🖥️ Running on a VPS

Recommended for 24/7 operation. The active hours window handles when it runs so you don't need to manually start/stop.

**Linux VPS:**
```bash
# Install
sudo apt update && sudo apt install python3 python3-pip screen -y
pip3 install flask flask-cors instagrapi python-dotenv pyotp --break-system-packages

# Run persistently
screen -S instaclean
python3 server.py
# Detach: Ctrl+A then D
# Reattach: screen -r instaclean
```

**Windows Server VPS:**
- Connect via Remote Desktop
- Install Python from python.org (check "Add to PATH")
- Run `python server.py` in PowerShell
- Keep the window open or use Task Scheduler for auto-start on reboot

**Important:** Delete `session/session.json` before first run on a new VPS — Instagram may reject a session created on a different IP.

---

## ❓ Troubleshooting

**Login keeps failing**
- Check `.env` credentials are correct
- Delete `session/session.json` and try again
- For 2FA: make sure `IG_2FA_SECRET` is the TOTP secret key, not the 6-digit code

**Mutual friends being removed**
- Delete `session/following_cache.json` — it may be empty/corrupted
- The tool will re-fetch your full following list before scanning

**Rate limit errors**
- Reduce `max_hour` to 40–50
- Increase `delay_min` / `delay_max`
- Stop and wait a few hours before restarting

**Bot not restarting in the morning**
- Make sure you pressed **Start** at least once (not just running `server.py`)
- Auto-restart only activates after a manual Start — it won't run on a fresh server launch without interaction

**Want a full fresh scan**
- Delete both `session/following_cache.json` and `session/followers_cache.json`

---

## 📦 Dependencies

| Package | Purpose |
|---------|---------|
| `instagrapi` | Unofficial Instagram API client |
| `flask` | Web server for dashboard |
| `flask-cors` | Cross-origin requests |
| `python-dotenv` | Load credentials from `.env` |
| `pyotp` | 2FA / TOTP code generation |

---

## 📄 License

MIT License — free to use and modify.