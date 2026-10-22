"""Track record of the screener's own setups, for the app: PUB/track.json.

  python track.py PUB

Intraday: every setup the breakout scan saw break out (history/<day>_orb.json), followed on Yahoo 5-minute bars.
Swing: every pullback / tight-base setup on the morning screen (history/<day>_premarket.json), followed on daily bars.

How a setup is scored (the app's own trade plan, the same for every setup, so the numbers compare):
  - triggered: intraday, the scan saw it break the opening range; swing, price traded at or above the "setup above"
    level within 3 sessions of the screen (filled at that level, or at the open if it opened above it);
  - a stop hit before the first target is a loss of 1R (R = entry minus stop);
  - at the first target (1.5R intraday, 2R swing) half is booked and the stop on the rest moves to the entry;
    the rest exits at the second target (3R), back at the entry, or at the time limit;
  - time limit: 3:15 PM the same day for intraday, the 10th session's close for swing;
  - if the stop and a target fall inside the same bar, the stop is assumed first (the cautious reading).
Details are kept 7 days for intraday and 30 days for swing; older results are kept only as counts (triggered,
profitable, loss) and total R. Market study only: these are rule outcomes on past prices, not trades anyone made.
"""
import datetime as dt
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screener.data_live import now_ist  # noqa: E402
from screener import export  # noqa: E402

KEEP = {"intraday": 7, "swing": 30}       # days of detail
SWING_TRIGGER_DAYS, SWING_HOLD = 3, 10    # sessions
SQUARE_OFF = dt.time(15, 15)


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def yahoo(symbols, **kw):
    import yfinance as yf
    out = {}
    if not symbols:
        return out
    data = yf.download([s + ".NS" for s in symbols], group_by="ticker", auto_adjust=False, threads=True, progress=False, **kw)
    for s in symbols:
        try:
            df = data[s + ".NS"] if isinstance(data.columns, pd.MultiIndex) else data
            df = df.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
            if df.index.tz is not None:
                df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
            if len(df):
                out[s] = df
        except Exception:  # noqa: BLE001
            continue
    return out


def walk(bars, side, entry, stop, t1, t2, time_exit_ok):
    """Follow the plan over bars (after the fill). Returns (outcome, R, exit price, done)."""
    s, risk = (1 if side == "long" else -1), abs(entry - stop)
    if not risk:
        return "No risk", 0.0, entry, True
    half = False
    for _, b in bars.iterrows():
        hi, lo = (b["high"], b["low"]) if s == 1 else (-b["low"], -b["high"])   # mirror shorts
        e, st, a, z = s * entry, s * (entry if half else stop), s * t1, s * t2
        if lo <= st:                       # stop first when both sit in one bar
            if half:
                return "First target, rest out at entry", 0.5 * abs(t1 - entry) / risk, entry, True
            return "Stop", -1.0, stop, True
        if not half and hi >= a:
            half = True
            if hi >= z:
                return "Both targets", (0.5 * abs(t1 - entry) + 0.5 * abs(t2 - entry)) / risk, t2, True
            continue
        if half and hi >= z:
            return "Both targets", (0.5 * abs(t1 - entry) + 0.5 * abs(t2 - entry)) / risk, t2, True
    if not len(bars):
        return "Open", 0.0, entry, False
    last = float(bars["close"].iloc[-1])
    move = s * (last - entry) / risk
    r = 0.5 * abs(t1 - entry) / risk + 0.5 * move if half else move
    if time_exit_ok:
        return ("First target, rest at time exit" if half else "Time exit"), r, last, True
    return ("Open, first target booked" if half else "Open"), r, last, False


def intraday_signals(pub, have):
    out = []
    hist = os.path.join(pub, "history")
    for f in sorted(os.listdir(hist)) if os.path.isdir(hist) else []:
        if not f.endswith("_orb.json"):
            continue
        day = f[:10]
        orb = load(os.path.join(hist, f), {})
        pre = load(os.path.join(hist, f"{day}_premarket.json"), {})
        if orb.get("demo"):
            continue
        signals = len(pre.get("longs", [])) + len(pre.get("shorts", [])) or len(orb.get("rows", []))
        out.append(("day", day, signals))
        for r in orb.get("rows", []):
            if r.get("entry") is None or r.get("trigger_time") is None:
                continue
            key = f"{day}:{r['symbol']}:{r['side']}"
            if key in have:
                continue
            out.append(("trade", {"key": key, "d": day, "sym": r["symbol"], "side": r["side"], "trig": r["trigger_time"],
                                  "entry": r["entry"], "stop": r["stop"], "t1": r["t1"], "t2": r["t2"], "outcome": "Open",
                                  "r": 0.0, "exit": None, "done": False}))
    return out


def swing_signals(pub, have, existing=()):
    out = []
    recent = {}
    for t in existing:
        if t.get("outcome") != "Not triggered":
            k_ = (t["sym"], {"Pullback": "pullbacks", "Tight base": "bases"}[t["setup"]]); recent[k_] = max(recent.get(k_, ""), t["d"])
    hist = os.path.join(pub, "history")
    for f in sorted(os.listdir(hist)) if os.path.isdir(hist) else []:
        if not f.endswith("_premarket.json"):
            continue
        pre = load(os.path.join(hist, f), {})
        day = f[:10]
        # only the morning screen counts: an evening preview (built the day before) is replaced by it
        if pre.get("demo") or str(pre.get("generated", ""))[:10] != day:
            continue
        out.append(("day", day, len(pre.get("pullbacks", [])) + len(pre.get("bases", []))))
        for setup, label in (("pullbacks", "Pullback"), ("bases", "Tight base")):
            for r in pre.get(setup, []):
                key = f"{day}:{r['symbol']}:{setup}"
                if key in have or r.get("entry") is None:
                    continue
                # the same setup listed again on the next screens is one setup, not several
                lastd = recent.get((r["symbol"], setup))
                if lastd and (dt.date.fromisoformat(day) - dt.date.fromisoformat(lastd)).days <= 7:
                    continue
                recent[(r["symbol"], setup)] = day
                out.append(("trade", {"key": key, "d": day, "sym": r["symbol"], "side": "long", "setup": label,
                                      "entry": r["entry"], "stop": r["stop"], "t1": r["t1"], "t2": r["t2"],
                                      "trig": None, "fill": None, "outcome": "Waiting", "r": 0.0, "exit": None, "done": False}))
    return out


def eval_intraday(t, bars5, now):
    df = bars5.get(t["sym"])
    day = dt.date.fromisoformat(t["d"])
    if df is None:
        return
    d = df[df.index.date == day]
    if d.empty:
        return
    trig = pd.Timestamp.combine(day, dt.time.fromisoformat(t["trig"]))
    after = d[(d.index > trig) & (d.index.time < SQUARE_OFF)]      # bars after the breakout bar, up to 3:15
    over = now.date() > day or now.time() >= SQUARE_OFF
    outcome, r, ex, done = walk(after, t["side"], t["entry"], t["stop"], t["t1"], t["t2"], over)
    t.update(outcome=outcome, r=round(r, 2), exit=round(ex, 2), done=done)


def eval_swing(t, daily, now):
    df = daily.get(t["sym"])
    if df is None:
        return
    day = pd.Timestamp(t["d"])
    d = df[df.index.normalize() >= day]
    if d.empty:
        return
    if t["trig"] is None:
        window = d.iloc[:SWING_TRIGGER_DAYS]
        hit = window[window["high"] >= t["entry"]]
        if hit.empty:
            if len(window) >= SWING_TRIGGER_DAYS:
                t.update(outcome="Not triggered", done=True)
            return
        first = hit.index[0]
        t["trig"] = first.strftime("%Y-%m-%d")
        t["fill"] = round(max(t["entry"], float(hit.iloc[0]["open"])), 2)
    fill = t["fill"]
    after = d[d.index.normalize() >= pd.Timestamp(t["trig"])].iloc[:SWING_HOLD]
    # the trigger day counts from the fill: only its low (stop) and high (targets) can matter, cautious order in walk()
    full = len(after) >= SWING_HOLD
    outcome, r, ex, done = walk(after, "long", fill, t["stop"], t["t1"], t["t2"], full)
    t.update(outcome=outcome, r=round(r, 2), exit=round(ex, 2), done=done, held=len(after))


def summarize(trades, days):
    trig = [t for t in trades if t.get("trig")]
    fin = [t for t in trig if t["done"]]
    return {"signals": sum(days.values()), "triggered": len(trig), "open": len(trig) - len(fin),
            "profit": sum(1 for t in fin if t["r"] > 0), "loss": sum(1 for t in fin if t["r"] < 0),
            "flat": sum(1 for t in fin if t["r"] == 0), "r": round(sum(t["r"] for t in fin), 2),
            "not_triggered": sum(1 for t in trades if t.get("outcome") == "Not triggered")}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    pub = sys.argv[1]
    now = now_ist().replace(tzinfo=None)
    path = os.path.join(pub, "track.json")
    doc = load(path, {}) or {}
    for kind in KEEP:
        doc.setdefault(kind, {"trades": [], "days": {}, "archive": {"signals": 0, "triggered": 0, "profit": 0, "loss": 0,
                                                                   "flat": 0, "r": 0.0, "from": None, "to": None}})

    # new setups from the history files
    for kind, fn in (("intraday", intraday_signals), ("swing", swing_signals)):
        k = doc[kind]
        have = {t["key"] for t in k["trades"]} | set(k.get("archived_keys", []))
        for item in (fn(pub, have, k["trades"]) if kind == "swing" else fn(pub, have)):
            if item[0] == "day":
                if item[1] > (k["archive"]["to"] or ""):
                    k["days"][item[1]] = item[2]
            else:
                k["trades"].append(item[1])

    # follow open setups on fresh prices
    oi = [t for t in doc["intraday"]["trades"] if not t["done"]]
    os_ = [t for t in doc["swing"]["trades"] if not t["done"]]
    try:
        bars5 = yahoo(sorted({t["sym"] for t in oi}), period="1mo", interval="5m") if oi else {}
        for t in oi:
            eval_intraday(t, bars5, now)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: intraday prices ({str(e)[:100]})")
    try:
        daily = yahoo(sorted({t["sym"] for t in os_}), period="3mo", interval="1d") if os_ else {}
        for t in os_:
            eval_swing(t, daily, now)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: daily prices ({str(e)[:100]})")

    # beyond the detail window: finished results become counts
    for kind, days in KEEP.items():
        k = doc[kind]
        cutoff = (now.date() - dt.timedelta(days=days)).isoformat()
        old_days = {d: n for d, n in k["days"].items() if d < cutoff}
        old = [t for t in k["trades"] if t["d"] < cutoff and t["done"]]
        if old_days or old:
            s, a = summarize(old, old_days), k["archive"]
            for f in ("signals", "triggered", "profit", "loss", "flat"):
                a[f] = a.get(f, 0) + s[f]
            a["r"] = round(a.get("r", 0) + s["r"], 2)
            ds = sorted(old_days) or sorted(t["d"] for t in old)
            a["from"] = min(filter(None, [a.get("from"), ds[0]]))
            a["to"] = max(filter(None, [a.get("to"), ds[-1]]))
            k["archived_keys"] = sorted(set(k.get("archived_keys", [])) | {t["key"] for t in old})[-3000:]
            k["trades"] = [t for t in k["trades"] if t not in old]
            k["days"] = {d: n for d, n in k["days"].items() if d >= cutoff}
        k["recent"] = summarize(k["trades"], k["days"])
        k["by_day"] = {d: summarize([t for t in k["trades"] if t["d"] == d], {d: n}) for d, n in sorted(k["days"].items())}
        k["trades"].sort(key=lambda t: (t["d"], t.get("trig") or ""), reverse=True)

    doc.update(schema=1, updated=now_ist().isoformat(timespec="seconds"),
               rules={"intraday": "First target 1.5R (half booked, stop to entry), second 3R, out by 3:15 PM.",
                      "swing": "Triggered within 3 sessions above the setup level; first target 2R (half booked, stop to "
                               "entry), second 3R, out at the 10th session's close."})
    export._dump(path, export.clean(doc))
    for kind in KEEP:
        r = doc[kind]["recent"]
        print(f"track {kind}: {r['triggered']} triggered, {r['profit']} profit, {r['loss']} loss, {r['open']} open, {r['r']:+.2f}R")


if __name__ == "__main__":
    main()
