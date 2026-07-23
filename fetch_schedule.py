"""Nightly fetch: runs once at 23:00 China time, fetches tomorrow's schedule."""
import os
import json
import datetime
import requests
from urllib.parse import quote

API_URL = "http://fzielts.gedu.net.cn/fzielts/schedule_queryByTeacherClass.action"
TEACHER_ID = os.environ["TEACHER_ID"]
BARK_KEY = os.environ.get("BARK_KEY", "")
CACHE_FILE = "schedule_cache.json"

CHINA_TZ = datetime.timezone(datetime.timedelta(hours=8))


def now_china():
    return datetime.datetime.now(CHINA_TZ)


def send_bark(title, body):
    if not BARK_KEY:
        return False
    try:
        url = f"https://api.day.app/{BARK_KEY}/{quote(title)}/{quote(body)}?sound=alarm"
        return requests.get(url, timeout=10).ok
    except Exception:
        return False


def fetch_schedule(date_str):
    params = {
        'teacherScheduleQTO.beginDate': date_str,
        'teacherScheduleQTO.endDate': date_str,
        'teacherScheduleQTO.teacherId': TEACHER_ID,
    }
    try:
        resp = requests.post(API_URL, data=params, timeout=15,
                             headers={'Accept': 'application/json'})
        if not resp.ok:
            print(f"API error {resp.status_code} for {date_str}")
            return None
    except requests.RequestException as e:
        print(f"API request failed for {date_str}: {e}")
        return None

    events = []
    for raw in resp.json():
        if not raw.get('classTime'):
            continue
        parts = raw['classTime'].split('-')
        if len(parts) != 2:
            continue
        start, end = parts
        content = raw.get('content', '').replace('<br>', '').split('\xa0')
        title = content[1] if len(content) > 1 else raw.get('content', '')
        if '不排' in title:
            continue
        events.append({'start': start, 'end': end})
    return events


def build_reminders(first_start, last_end):
    reminders = []
    fh, fm = map(int, first_start.split(':'))
    for offset in [-15, -10, -5, 0]:
        t = fh * 60 + fm + offset
        rh, rm = (t // 60) % 24, t % 60
        reminders.append({
            'time': f"{rh:02d}:{rm:02d}",
            'label': 'GEDU打卡',
            'body': 'GEDU打卡',
        })
    lh, lm = map(int, last_end.split(':'))
    for offset in [0, 5, 10, 15]:
        t = lh * 60 + lm + offset
        rh, rm = (t // 60) % 24, t % 60
        reminders.append({
            'time': f"{rh:02d}:{rm:02d}",
            'label': 'GEDU打卡',
            'body': 'GEDU打卡',
        })
    return reminders


def main():
    n = now_china()
    tomorrow = (n + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Fetching schedule for {tomorrow}...")

    events = fetch_schedule(tomorrow)
    if events is None:
        print("Fetch failed!")
        send_bark("GEDU打卡", "课表抓取失败，明天可能没有打卡提醒")
        return
    if not events:
        print("No classes tomorrow")
        # Write empty cache so notifier knows there's nothing
        cache = {}
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE) as f:
                cache = json.load(f)
        cache[tomorrow] = None
        today_str = n.strftime("%Y-%m-%d")
        cache = {k: v for k, v in cache.items() if k >= today_str}
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, ensure_ascii=False)
        return

    earliest = min(events, key=lambda e: e['start'])
    latest = max(events, key=lambda e: e['end'])
    reminders = build_reminders(earliest['start'], latest['end'])

    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    cache[tomorrow] = reminders
    today_str = n.strftime("%Y-%m-%d")
    cache = {k: v for k, v in cache.items() if k >= today_str}
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, ensure_ascii=False)

    print(f"Saved {len(reminders)} reminders for {tomorrow}: "
          f"{earliest['start']} -> {latest['end']}")


if __name__ == "__main__":
    main()
