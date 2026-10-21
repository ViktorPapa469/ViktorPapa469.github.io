"""Opening Bell push notifications, sent from GitHub (see ci.sh).

  python push.py screen     PUB   # today's screen is ready (morning run)
  python push.py preview    PUB   # tomorrow's preview is ready (evening run)
  python push.py breakouts  PUB   # each stock newly marked TRIGGERED in PUB/orb.json
  python push.py squareoff  PUB   # 3:15 reminder, only on days the market traded

Phones sign up in the app (Settings > Notifications), which saves a push address, the alert types they want and
the terms version they accepted to Firestore trade_alerts/{id}; only phones on the current terms are sent to. This lists them with Fovea's public web key and signs each push with the VAPID_PRIVATE
secret, the same key pair Fovea's reminders use. Quantities are not sent: each phone works them out from its own
capital and risk. What was already sent is kept in PUB/state/pushed.json, so a rerun never repeats a notification.
Never fails the run: problems are printed as warnings.
"""
import datetime as dt
import json
import os
import re
import sys
import time

import requests

PROJECT = os.environ.get("FB_PROJECT", "opening-bell-4fdc9")
KEY = os.environ.get("FB_KEY", "")
FS = os.environ.get("FS_BASE", "https://firestore.googleapis.com/v1")
SITE = "https://viktorpapa469.github.io"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TTL = {"screen": 3 * 3600, "preview": 12 * 3600, "breakouts": 15 * 60, "squareoff": 15 * 60}
PREF = {"screen": "screen", "preview": "preview", "breakouts": "breakouts", "squareoff": "squareoff"}


def terms_version():
    """The current terms version, read from trade/terms.html. Phones that haven't accepted it get nothing."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, "..", "..", "trade", "terms.html"), encoding="utf-8") as fh:
            m = re.search(r'<meta name="terms-version" content="([^"]+)"', fh.read())
        return m.group(1) if m else None
    except OSError:
        return None


def warn(msg):
    print(f"::warning::push: {msg}" if os.environ.get("GITHUB_ACTIONS") else f"WARN push: {msg}", flush=True)


def today():
    return dt.datetime.now(IST).date().isoformat()


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def nice_day(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d:%a} {d.day} {d:%b}"


def names(items, k=3):
    syms = [x["symbol"] for x in items[:k]]
    return ", ".join(syms) if syms else "none"


def money(x):
    return f"₹{x:,.2f}"


# ------------------------------------------------------------------ messages
def msg_screen(pre, kind):
    r = pre.get("regime") or {}
    title = (f"Screen ready for {nice_day(pre['date'])}" if kind == "screen"
             else f"Preview for {nice_day(pre['date'])}")
    body = f"{r.get('label', 'Market')}. Longs: {names(pre.get('longs', []))}. Shorts: {names(pre.get('shorts', []))}."
    if kind == "preview":
        body += " Final screen at about 9:12."
    return [{"kind": kind, "title": title, "body": body, "tab": "plan", "tag": f"ob-{kind}", "date": pre["date"]}]


def msg_breakouts(orb, already):
    out = []
    for r in orb.get("rows", []):
        if r.get("status") != "TRIGGERED" or r["symbol"] in already or r.get("entry") is None:
            continue
        long = r.get("side") == "long"
        out.append({
            "kind": "breakouts", "tab": "live", "tag": f"ob-{r['symbol']}", "date": orb["date"],
            "symbol": r["symbol"], "side": r.get("side"), "time": r.get("trigger_time"),
            "entry": r["entry"], "stop": r["stop"], "t1": r.get("t1"), "lot": r.get("lot"),
            "size_mult": orb.get("size_mult", 1), "extended": bool(r.get("extended")),
            # fallback text; the phone replaces it with one that includes its own suggested position
            "title": f"{r['symbol']} {'long' if long else 'short'} setup triggered {r.get('trigger_time') or ''}".strip(),
            "body": (f"{'Long setup above' if long else 'Short setup below'} {money(r['entry'])}, "
                     f"stop {money(r['stop'])}, target {money(r['t1'])}. For study only, not investment advice."),
        })
    return out


def msg_squareoff():
    return [{"kind": "squareoff", "title": "15 minutes to the close", "tab": "live", "tag": "ob-squareoff",
             "body": "Reminder: brokers auto square-off intraday positions near the close.",
             "date": today()}]


# ------------------------------------------------------------------ sending
def records():
    url = f"{FS}/projects/{PROJECT}/databases/(default)/documents/trade_alerts"
    tok = None
    while True:
        params = {"pageSize": 300, "key": KEY}
        if tok:
            params["pageToken"] = tok
        r = requests.get(url, params=params, headers={"Referer": SITE + "/"}, timeout=30)
        r.raise_for_status()
        j = r.json()
        for d in j.get("documents", []):
            f = {k: _val(v) for k, v in d.get("fields", {}).items()}
            yield d["name"].rsplit("/", 1)[-1], f
        tok = j.get("nextPageToken")
        if not tok:
            return


def _val(v):
    (t, x), = v.items()
    if t == "mapValue":
        return {k: _val(y) for k, y in x.get("fields", {}).items()}
    if t == "arrayValue":
        return [_val(y) for y in x.get("values", [])]
    if t == "integerValue":
        return int(x)
    return x


def send(messages, kind):
    """Send each message to every phone that wants this kind. Returns True if sending was possible."""
    if not messages:
        return True
    vapid = os.environ.get("VAPID_PRIVATE", "").strip()
    if not vapid or not KEY:
        warn("VAPID_PRIVATE or FB_KEY missing; notifications not sent")
        return False
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        warn("pywebpush not installed; notifications not sent")
        return False
    try:
        terms = terms_version()
        if not terms:
            warn("trade/terms.html not found; notifications not sent")
            return False
        phones = [(rid, f) for rid, f in records()
                  if f.get("on") and f.get("endpoint") and f.get("terms") == terms
                  and (f.get("kinds") or {}).get(PREF[kind], True)]
    except Exception as e:  # noqa: BLE001 - any Firestore problem just skips this round
        warn(f"could not list phones ({str(e)[:160]})")
        return False
    pem = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".vapid.pem")
    with open(pem, "w") as fh:
        fh.write(vapid + "\n")
    sent = gone = failed = 0
    try:
        for rid, f in phones:
            sub = {"endpoint": f["endpoint"], "keys": {"p256dh": f.get("p256dh", ""), "auth": f.get("auth", "")}}
            for m in messages:
                try:
                    webpush(subscription_info=sub, data=json.dumps(m, ensure_ascii=False),
                            vapid_private_key=pem, ttl=TTL[kind],
                            vapid_claims={"sub": SITE, "exp": int(time.time()) + 3000},
                            headers={"Urgency": "high" if kind in ("breakouts", "squareoff") else "normal",
                                     "Topic": re.sub(r"[^A-Za-z0-9_-]", "_", m["tag"])[:32]})
                    sent += 1
                except WebPushException as e:
                    code = getattr(e.response, "status_code", 0)
                    if code in (404, 410):  # the phone dropped this address; the app makes a new one when opened
                        gone += 1
                        break
                    failed += 1
                    print("push failed", rid[:6], code, str(e)[:120])
    finally:
        os.remove(pem)
    print(f"push {kind}: {len(messages)} message(s), {len(phones)} phone(s), sent {sent}, expired {gone}, failed {failed}")
    return True


# ------------------------------------------------------------------ main
def main():
    if len(sys.argv) != 3 or sys.argv[1] not in TTL:
        sys.exit(__doc__)
    kind, pub = sys.argv[1], sys.argv[2]
    state_path = os.path.join(pub, "state", "pushed.json")
    state = load(state_path) or {}
    if state.get("date") != today():
        state = {"date": today()}
    pre, orb = load(os.path.join(pub, "premarket.json")), load(os.path.join(pub, "orb.json"))

    if kind in ("screen", "preview"):
        if not pre or pre.get("demo"):
            return warn("no screen to announce")
        if pre["date"] > today():
            kind = "preview"  # built after the close: it's for the next session
        elif pre["date"] < today():
            return warn("screen is out of date; not announced")
        key = f"{kind}:{pre['date']}"
        if state.get(key):
            return print(f"push {kind}: already sent for {pre['date']}")
        ok = send(msg_screen(pre, kind), kind)
        if ok:
            state[key] = True
    elif kind == "breakouts":
        if not orb or orb.get("demo") or orb.get("date") != today():
            return print("push breakouts: no scan for today")
        done = set(state.get("breakouts", []))
        msgs = msg_breakouts(orb, done)
        if not msgs:
            return print("push breakouts: nothing new")
        if send(msgs, kind):
            state["breakouts"] = sorted(done | {m["symbol"] for m in msgs})
    elif kind == "squareoff":
        traded = orb and orb.get("date") == today() and any(r.get("last") is not None for r in orb.get("rows", []))
        if not traded:
            return print("push squareoff: no trading today (no live prices this morning)")
        if state.get("squareoff"):
            return print("push squareoff: already sent")
        if send(msg_squareoff(), kind):
            state["squareoff"] = True

    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w") as fh:
        json.dump(state, fh)


if __name__ == "__main__":
    main()
