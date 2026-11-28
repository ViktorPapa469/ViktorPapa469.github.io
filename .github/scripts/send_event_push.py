# Event Run Sheet phone alerts: run every 5 minutes by .github/workflows/events-push.yml.
# Reads the events and notifications from Firestore (public reads, using the app's public web key from events/config.json)
# and pushes to every phone that turned on "Phone alerts":
#   - a reminder about 5 minutes before each sub-event (what's required and how many tasks are still open);
#   - every notification an organiser sent since the last run.
# The time of the last run is kept on the ci-state-events branch (LAST), so a late or skipped run catches up
# (at most 20 minutes back, so an outage doesn't send a flood of stale alerts).
import os, sys, json, time, datetime as dt
from zoneinfo import ZoneInfo
import requests
from pywebpush import webpush, WebPushException

cfg = json.load(open('events/config.json'))
PROJECT, KEY = cfg.get('projectId', ''), cfg.get('apiKey', '')
if not PROJECT or not KEY or 'PASTE' in KEY:
    print('events/config.json has no Firebase project yet: nothing to do'); sys.exit(0)
VAPID = os.environ.get('VAPID_PRIVATE', '').strip()
if not VAPID: sys.exit('VAPID_PRIVATE secret is missing: add it under Settings > Secrets and variables > Actions.')

now = time.time()
try: last = float(os.environ.get('LAST') or 0)
except ValueError: last = 0
start = max(last, now - 1200) if last else now - 330
BASE = 'https://firestore.googleapis.com/v1/projects/%s/databases/(default)/documents/' % PROJECT
HDR = {'Referer': 'https://viktorpapa469.github.io/events/'}

def val(v):
    if 'stringValue' in v: return v['stringValue']
    if 'integerValue' in v: return int(v['integerValue'])
    if 'doubleValue' in v: return float(v['doubleValue'])
    if 'booleanValue' in v: return v['booleanValue']
    if 'arrayValue' in v: return [val(x) for x in v['arrayValue'].get('values', [])]
    if 'mapValue' in v: return {k: val(x) for k, x in v['mapValue'].get('fields', {}).items()}
    return None

def docs(coll, **params):
    tok = None
    while True:
        p = {'pageSize': 300, 'key': KEY, **params, **({'pageToken': tok} if tok else {})}
        r = requests.get(BASE + coll, headers=HDR, params=p, timeout=30)
        if r.status_code != 200:
            try: m = r.json().get('error', {}); m = '%s: %s' % (m.get('status'), m.get('message'))
            except Exception: m = r.text[:300]
            sys.exit('Firestore refused %s (HTTP %d) %s' % (coll, r.status_code, m))
        j = r.json()
        for d in j.get('documents', []):
            yield d['name'].rsplit('/', 1)[-1], {k: val(x) for k, x in d.get('fields', {}).items()}
        tok = j.get('nextPageToken')
        if not tok or params.get('pageSize'): return

def local(s, tz):
    try: return dt.datetime.strptime(s, '%Y-%m-%dT%H:%M').replace(tzinfo=tz).timestamp()
    except Exception: return None

msgs = []
for eid, ev in docs('events'):
    try: tz = ZoneInfo(ev.get('tz') or 'Asia/Kolkata')
    except Exception: tz = ZoneInfo('Asia/Kolkata')
    for s in ev.get('subs') or []:
        if not isinstance(s, dict): continue
        begins = local(s.get('as') or s.get('ps') or '', tz)
        if begins is None or not (start < begins - 300 <= now): continue
        mins = round((begins - now) / 60)
        hhmm = (s.get('as') or s.get('ps'))[11:16]
        open_tasks = [t for t in (s.get('tasks') or []) if isinstance(t, dict) and not t.get('done')]
        bits = [hhmm + (' · ' + s['loc'] if s.get('loc') else '') + (' · In charge: ' + s['lead'] if s.get('lead') else '')]
        if s.get('reqs'): bits.append('Needed: ' + ', '.join(s['reqs'])[:150])
        if open_tasks: bits.append('%d task%s still open' % (len(open_tasks), '' if len(open_tasks) == 1 else 's'))
        title = ('In %d min: ' % mins if mins > 0 else 'Now: ') + (s.get('title') or 'Next sub-event')
        msgs.append({'title': title[:90], 'body': '. '.join(bits)[:240], 'tag': 'sub-' + str(s.get('id', '')), 'ttl': 900})

for nid, n in docs('notices', orderBy='at desc', pageSize=20):
    at = (n.get('at') or 0) / 1000
    if not (start < at <= now): continue
    urgent = n.get('level') == 'urgent'
    title = ('URGENT · ' if urgent else '') + (n.get('evName') or 'Event notification')
    body = (n.get('text') or '') + (' (For: %s)' % n['to'] if n.get('to') else '')
    msgs.append({'title': title[:90], 'body': body[:280], 'tag': 'note-' + nid, 'urgent': urgent, 'ttl': 3600})

sent = gone = failed = phones = 0
if msgs:
    open('vapid.pem', 'w').write(VAPID + '\n')
    for pid, p in docs('push'):
        if not p.get('on', True) or not p.get('endpoint'): continue
        phones += 1
        for m in msgs:
            try:
                webpush(subscription_info={'endpoint': p['endpoint'], 'keys': {'p256dh': p.get('p256dh', ''), 'auth': p.get('auth', '')}},
                        data=json.dumps({k: m[k] for k in ('title', 'body', 'tag', 'urgent') if k in m}), vapid_private_key='vapid.pem',
                        vapid_claims={'sub': 'https://viktorpapa469.github.io', 'exp': int(time.time()) + 3000},
                        ttl=m['ttl'], headers={'Urgency': 'high'})
                sent += 1
            except WebPushException as e:
                code = getattr(e.response, 'status_code', 0)
                if code in (404, 410): gone += 1; break   # this phone turned alerts off or reinstalled; it saves a new address next time
                failed += 1; print('push failed', pid[:6], code, str(e)[:120])
    os.remove('vapid.pem')
open('/tmp/events_last.txt', 'w').write('%.0f\n' % now)
print('window %s to %s UTC  messages %d  phones %d  sent %d  expired %d  failed %d' % (
    dt.datetime.fromtimestamp(start, dt.timezone.utc).strftime('%H:%M'), dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime('%H:%M'), len(msgs), phones, sent, gone, failed))
