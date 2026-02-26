# 🤖 InstaClean — Instagram Bot Follower Remover

A Python tool to detect and remove bot/fake followers from your Instagram account, with a live visual dashboard.

> ⚠️ **Disclaimer:** This tool uses an unofficial Instagram API (`instagrapi`). Use at your own risk. Always start with Dry Run mode. The author is not responsible for any account actions taken by Instagram.

---

## ✨ Features

- 🖥️ Live visual dashboard (runs in your browser)
- 🧪 Dry Run mode — scan without removing anything
- 🎯 Bot scoring system with 9 detection flags
- ⏱️ Hourly & daily removal limits
- 🔄 Session reuse — no repeated logins
- 📊 7-day removal history chart
- 🛡️ Whitelist to protect specific accounts
- 📋 Real-time activity log

---

## 📁 Project Structure

```
instagram_cleaner/
├── server.py          # Flask web server — run this to start
├── main.py            # Instagram bot removal logic
├── state.py           # Shared state between server and cleaner
├── bot_detector.py    # Bot scoring algorithm
├── config.py          # All settings
├── rate_limiter.py    # Daily counter with persistence
├── dashboard.html     # Visual dashboard (served by Flask)
├── .env               # Your credentials (never commit this!)
├── .gitignore
└── session/           # Auto-created at runtime
    ├── session.json       # Saved login session
    ├── daily_counter.json # Removal counter
    ├── history.json       # 7-day history
    └── activity.log       # Log file
```

---

## 🚀 Setup Guide

### 1. Requirements

- Python 3.8 or higher
- pip

Check your Python version:
```bash
python --version
```

If not installed, download from [python.org](https://python.org).

---

### 2. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/instagram_cleaner.git
cd instagram_cleaner
```

---

### 3. Install Dependencies

**Windows (PowerShell):**
```powershell
pip install flask flask-cors instagrapi python-dotenv schedule
```

**Mac / Linux:**
```bash
pip3 install flask flask-cors instagrapi python-dotenv schedule
```

> 💡 Optional but recommended — use a virtual environment:
> ```bash
> python -m venv venv
> # Windows:
> .\venv\Scripts\activate
> # Mac/Linux:
> source venv/bin/activate
> ```

---

### 4. Create Your `.env` File

Create a file named `.env` in the project root:

**Windows PowerShell:**
```powershell
New-Item .env -Type File
```

**Mac/Linux:**
```bash
touch .env
```

Open `.env` and add your Instagram credentials:
```
IG_USER=your_instagram_username
IG_PASS=your_instagram_password
```

> 🔒 Never share or commit your `.env` file. It is already in `.gitignore`.

---

### 5. Configure Settings

Open `config.py` and adjust to your needs:

```python
config = {
    # Removal limits
    "max_removals_per_day":  500,   # recommended: start at 300, ramp up weekly
    "max_removals_per_hour": 60,    # recommended: never exceed 80

    # Delays between actions (seconds) — randomized to look human
    "delay_between_actions": (10, 35),
    "delay_between_batches": (90, 180),
    "batch_size": 5,

    # Bot detection — minimum score to remove (1–9)
    # 2 = aggressive | 3 = balanced (default) | 4 = conservative
    "min_bot_score": 3,

    # Only run between these hours (24hr format)
    "run_hour_range": (8, 23),

    # Accounts to never remove
    "whitelist": ["friend1", "brand_collab"],

    # Safety switches
    "skip_verified": True,   # never remove blue-tick accounts
    "cooldown_after_block": 1800,  # wait 30min if action blocked
    "max_errors_before_stop": 3,

    # ALWAYS start with True — switch to False only after reviewing dry run results
    "dry_run": True,
}
```

---

### 6. Run the Dashboard

```bash
python server.py
```

Then open your browser and go to:
```
http://localhost:5000
```

---

## 🎮 How to Use

### Step 1 — Dry Run First (Safe Mode)
Make sure `dry_run: True` in `config.py`. Press **Start Cleaning** in the dashboard. The tool will scan your followers and show detected bots in the queue — **without removing anyone.**

### Step 2 — Review Results
Watch the **Bot Queue** and **Activity Log** panels. Ask yourself: do these accounts look like real bots? If yes, the detection is working correctly.

### Step 3 — Adjust Sensitivity
In the dashboard, change **Min Bot Score**:
- Lower (2) = removes more accounts
- Higher (4) = removes fewer, only obvious bots

### Step 4 — Go Live
When confident, toggle **Dry Run OFF** in the dashboard and press **Start Cleaning** again. Real removals will begin.

---

## 🎯 Bot Detection — How Scoring Works

Each flag below adds **+1** to the bot score. An account is removed if its score reaches `min_bot_score`.

| Flag | What It Checks |
|------|---------------|
| `no_profile_pic` | Account has no photo |
| `zero_posts` | 0 posts ever published |
| `private_no_posts` | Private account with 0 posts |
| `no_bio` | Empty biography |
| `very_new_account` | Less than 3 posts and less than 10 followers |
| `follow_bomb` | Following 3000+ but has under 100 followers |
| `mass_follower` | Following 7500+ accounts (near Instagram's limit) |
| `numeric_suffix` | Username ends in 4+ numbers (e.g. `user48291`) |
| `random_chars` | Username looks randomly generated (e.g. `xk9m3az`) |

**Max possible score: 9**

---

## 📈 Recommended Ramp-Up Plan

| Week | Mode | Max/Day | Max/Hour |
|------|------|---------|---------|
| Week 1–2 | Dry Run ✅ | — | — |
| Week 3 | Live | 300 | 40 |
| Week 4 | Live | 500 | 60 |
| Week 5+ | Live | 700 | 60 |

> Never jump to high limits immediately. Instagram detects sudden behavior spikes.

---

## ⚠️ Warning Signs — Stop Immediately If You See

- "Action Blocked" popup on Instagram
- Asked to verify your phone number
- Follower count stops updating
- Can't follow/unfollow anyone
- Forced login verification

If any of these happen: stop the script, set limits lower, and wait 24–48 hours before trying again.

---

## 🛡️ Safety Features Built In

- ✅ Random delays between every action (not robotic)
- ✅ Batch resting (pauses every 5 actions)
- ✅ Hourly and daily hard limits
- ✅ Only runs during daytime hours
- ✅ Session reuse (avoids repeated logins)
- ✅ Auto-stops on consecutive errors
- ✅ Whitelist for accounts to never remove
- ✅ Skips verified (blue tick) accounts

---

## 🔄 Run Automatically Every Day

**Windows — Task Scheduler:**
1. Search "Task Scheduler" in the Start menu
2. Create Basic Task → Daily
3. Set the action to run:
   ```
   python C:\path\to\instagram_cleaner\server.py
   ```

**Mac/Linux — Cron:**
```bash
crontab -e
# Add this line (runs daily at 10:30am):
30 10 * * * cd ~/instagram_cleaner && python server.py
```

---

## ❓ Troubleshooting

**`touch` is not recognized (Windows)**
```powershell
New-Item filename -Type File
```

**`venv\Scripts\activate` fails (Windows)**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Login keeps failing**
- Check your `.env` credentials are correct
- Delete `session/session.json` and try again
- If you have 2FA enabled, you may need to temporarily disable it or handle the verification code in the login flow

**Rate limit errors**
- Reduce `max_removals_per_hour` to 30–40
- Increase `delay_between_actions` to `(15, 45)`
- Stop the script and wait a few hours

---

## 📦 Dependencies

| Package | Purpose |
|---------|---------|
| `instagrapi` | Unofficial Instagram API client |
| `flask` | Web server for dashboard |
| `flask-cors` | Cross-origin requests for dashboard |
| `python-dotenv` | Load credentials from `.env` |
| `schedule` | Daily job scheduling |

---

## 📄 License

MIT License — free to use and modify.

---

## 🙏 Contributing

Pull requests welcome. Please test with Dry Run mode before submitting any changes that affect removal logic.
