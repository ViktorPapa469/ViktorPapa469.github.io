# Fovea daily reminders: run every 15 minutes by .github/workflows/reminders.yml.
# Reads the reminder records (reminders/{id}: push address, time zone, morning and evening times) from Firestore and sends a
# push to each device whose morning or evening time falls in this quarter-hour. The device's helper (sw.js) picks the line.
import os, sys, json, time, datetime as dt
from zoneinfo import ZoneInfo
import requests
from pywebpush import webpush, WebPushException

PROJECT = os.environ.get('FB_PROJECT', 'fovea-25d37'); KEY = os.environ['FB_KEY']
VAPID = os.environ.get('VAPID_PRIVATE', '').strip()
if not VAPID: sys.exit('VAPID_PRIVATE secret is missing: add it under Settings > Secrets and variables > Actions.')
open('vapid.pem', 'w').write(VAPID + '\n')
OFFSET = 3                         # runs start at :03, :18, :33 and :48; a run that is late by up to 14 minutes still serves its own quarter
now = dt.datetime.now(dt.timezone.utc)
slot = ((now.hour * 60 + now.minute - OFFSET) % 1440) // 15

def records():
    url = os.environ.get('FS_BASE', 'https://firestore.googleapis.com/v1') + '/projects/%s/databases/(default)/documents/reminders' % PROJECT
    tok = None
    while True:
        r = requests.get(url, params={'pageSize': 300, 'key': KEY, **({'pageToken': tok} if tok else {})}, timeout=30); r.raise_for_status(); j = r.json()
        for d in j.get('documents', []):
            f = {k: list(v.values())[0] for k, v in d.get('fields', {}).items()}
            yield d['name'].rsplit('/', 1)[-1], f
        tok = j.get('nextPageToken')
        if not tok: return

def due(f, key):
    try:
        hh, mm = map(int, str(f.get(key, '')).split(':')); tz = ZoneInfo(f.get('tz') or 'UTC')
    except Exception: return False
    d = now.astimezone(tz).date()
    for day in (d - dt.timedelta(days=1), d, d + dt.timedelta(days=1)):
        t = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz).astimezone(dt.timezone.utc)
        if abs((t - now).total_seconds()) < 1800 and (t.hour * 60 + t.minute) // 15 == slot: return True
    return False

sent = gone = failed = 0
for rid, f in records():
    if not f.get('on') or not f.get('endpoint'): continue
    kind = 'morning' if due(f, 'morning') else 'evening' if due(f, 'evening') else None
    if not kind: continue
    try:
        webpush(subscription_info={'endpoint': f['endpoint'], 'keys': {'p256dh': f.get('p256dh', ''), 'auth': f.get('auth', '')}},
                data=json.dumps({'kind': kind}), vapid_private_key='vapid.pem', vapid_claims={'sub': 'https://viktorpapa469.github.io', 'exp': int(time.time()) + 3000},
                ttl=3600, headers={'Urgency': 'normal'})
        sent += 1
    except WebPushException as e:
        code = getattr(e.response, 'status_code', 0)
        if code in (404, 410): gone += 1          # the device dropped this address; the app makes a new one when it next opens
        else: failed += 1; print('push failed', rid[:6], code, str(e)[:120])
os.remove('vapid.pem')
print('slot %02d:%02d UTC  sent %d  expired %d  failed %d' % (slot * 15 // 60, slot * 15 % 60, sent, gone, failed))
