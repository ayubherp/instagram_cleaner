import json, os
from datetime import date

COUNTER_FILE = "session/daily_counter.json"

def get_today_count() -> int:
    if not os.path.exists(COUNTER_FILE):
        return 0
    with open(COUNTER_FILE) as f:
        data = json.load(f)
    if data.get("date") != str(date.today()):
        return 0  # reset for new day
    return data.get("count", 0)

def increment_count():
    count = get_today_count() + 1
    os.makedirs("session", exist_ok=True)
    with open(COUNTER_FILE, "w") as f:
        json.dump({"date": str(date.today()), "count": count}, f)
    return count

def can_remove_more(max_per_day: int) -> bool:
    return get_today_count() < max_per_day