"""Nightly fetch: runs at 23:00 China time. Scans forward from tomorrow
until finding a day with classes (max 7 days), caches all scanned days."""
import os
import json
import datetime
import requests
from urllib.parse import quote

API_URL = "http://fzielts.gedu.net.cn/fzielts/schedule_queryByTeacherClass.action"
TEACHER_ID = os.environ["TEACHER_ID"]
BARK_KEY = os.environ.get("BARK_KEY", "")
CACHE_FILE = "schedule_cache.json"
MAX_SCAN_DAYS = 7

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


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, ensure_ascii=False)


def scan_and_cache(start_date_str, max_days=MAX_SCAN_DAYS):
    """Scan forward from start_date_str until a day with classes is found.
    Returns (class_date, reminders, failed_dates) where:
      - class_date: str or None
      - reminders: list or None (None = API error, [] = no classes in range)
      - failed_dates: list of date_strs that were empty
    Also writes the updated cache file."""
    cache = load_cache()
    start = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
    empty_dates = []

    for i in range(max_days):
        day = (start + datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        print(f"Fetching schedule for {day}...")

        events = fetch_schedule(day)
        if events is None:
            # API error — abort, mark all scanned empty dates in cache
            today_str = now_china().strftime("%Y-%m-%d")
            for d in empty_dates:
                cache[d] = None
            cache = {k: v for k, v in cache.items() if k >= today_str}
            save_cache(cache)
            return None, None, empty_dates

        if events:
            earliest = min(events, key=lambda e: e['start'])
            latest = max(events, key=lambda e: e['end'])
            reminders = build_reminders(earliest['start'], latest['end'])
            today_str = now_china().strftime("%Y-%m-%d")
            for d in empty_dates:
                cache[d] = None
            cache[day] = reminders
            cache = {k: v for k, v in cache.items() if k >= today_str}
            save_cache(cache)
            print(f"Found classes on {day}: {earliest['start']} -> {latest['end']}"
                  f" ({len(reminders)} reminders)")
            if empty_dates:
                print(f"Skipped empty days: {', '.join(empty_dates)}")
            return day, reminders, empty_dates

        print(f"No classes on {day}")
        empty_dates.append(day)

    # All max_days scanned, no classes found
    today_str = now_china().strftime("%Y-%m-%d")
    for d in empty_dates:
        cache[d] = None
    cache = {k: v for k, v in cache.items() if k >= today_str}
    save_cache(cache)
    print(f"No classes found in next {max_days} days")
    return None, [], empty_dates


def main():
    import sys
    n = now_china()
    if len(sys.argv) > 1:
        start_date = sys.argv[1]
    else:
        start_date = (n + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    class_date, reminders, empty_dates = scan_and_cache(start_date)

    if class_date is None and reminders is None:
        send_bark("GEDU打卡", "课表抓取失败，明天可能没有打卡提醒")
    elif reminders == []:
        send_bark("GEDU打卡", f"从{start_date}起{MAX_SCAN_DAYS}天均无课程")


if __name__ == "__main__":
    main()
