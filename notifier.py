"""Daytime notifier: reads cached schedule, sends Bark reminders. No API calls."""
import os
import json
import datetime
import requests
from urllib.parse import quote

BARK_KEY = os.environ.get("BARK_KEY", "")
CACHE_FILE = "schedule_cache.json"
SENT_DIR = "/tmp/checkin_sent"
WINDOW_MINUTES = 3

CHINA_TZ = datetime.timezone(datetime.timedelta(hours=8))


def now_china():
    return datetime.datetime.now(CHINA_TZ)


def main():
    if not BARK_KEY:
        print("BARK_KEY env not set — nothing to do")
        return

    if not os.path.exists(CACHE_FILE):
        print("No cache file yet — nightly fetch may not have run")
        return

    with open(CACHE_FILE) as f:
        cache = json.load(f)

    n = now_china()
    today_str = n.strftime("%Y-%m-%d")
    current_time = n.strftime("%H:%M")

    reminders = cache.get(today_str)
    if not reminders:
        print(f"No reminders for {today_str}")
        return

    os.makedirs(SENT_DIR, exist_ok=True)

    for r in reminders:
        ch, cm = map(int, current_time.split(':'))
        th, tm = map(int, r['time'].split(':'))
        diff = abs((ch * 60 + cm) - (th * 60 + tm))
        if diff > WINDOW_MINUTES:
            continue

        marker = f"{SENT_DIR}/{today_str}_{r['time']}"
        if os.path.exists(marker):
            continue

        url = f"https://api.day.app/{BARK_KEY}/{quote(r['label'])}/{quote(r['body'])}?sound=alarm"
        try:
            resp = requests.get(url, timeout=10)
            if resp.ok:
                open(marker, 'w').close()
                print(f"Sent [{r['time']}] {r['label']}")
        except Exception as e:
            print(f"Error sending notification: {e}")


if __name__ == "__main__":
    main()
