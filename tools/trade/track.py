"""Track record of the screener's own setups, for the app: PUB/track.json, and every setup for good in PUB/tracklog/.

  python track.py PUB

Intraday: every setup the breakout scan saw break out (history/<day>_orb.json), followed on Yahoo 5-minute bars.
Swing: every pullback / tight-base / CANSLIM / Minervini setup on the morning screen (history/<day>_premarket.json),
followed on daily bars.

How a setup is scored (the app's own trade plan, the same for every setup, so the numbers compare):
  - intraday, bought where it could really have been bought: the open of the first 5-minute bar that starts at or
    after the alert (for scans from before alerts were timed, the bar after the breakout bar). If by then price is
    already back through the stop or at the first target, the setup counts as not entered;
  - swing, a buy order waiting at the "setup above" level: filled at that level, or at the open if it opened above
    it, within 3 sessions of the screen;
  - R is the planned stop distance (level to stop), the amount the position is sized to risk. A late or gapped
    fill therefore loses more than 1R at the stop and makes less than the planned R at the targets;
  - a stop hit before the first target is a loss; at the first target (1.5R intraday, 2R swing) half is booked and
    the stop on the rest moves to the price paid; the rest exits at the second target (3R), back at the price
    paid, or at the time limit (3:15 PM the same day intraday; the 10th or 30th session's close for swing);
  - if the stop and a target fall inside the same bar, the stop is assumed first (the cautious reading);
  - costs come off every result: config.COST_INTRADAY_PCT / COST_SWING_PCT of the trade's value for the round trip
    (brokerage, STT, exchange fees, stamp duty, GST, a little slippage). Each trade keeps r (after costs), gross
    (before costs) and ideal (the old reading: in at the level exactly, no costs) so the three can be compared.
Breakouts the scan left out (low opening volume, too far gone, position or loss limits, fell back, weak against
Nifty) are followed the same way and kept apart ("others"), so the filters can be judged against what they skipped.
track.json keeps detail for 7 days (intraday) and 30 days (swing) and counts for everything older; tracklog/<year>.json
keeps every finished setup with its detail, for good. Market study only: rule outcomes on past prices, not trades
anyone made.
"""
import datetime as dt
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402
from screener.data_live import now_ist  # noqa: E402
from screener import export  # noqa: E402
from screener.plan import walk  # noqa: E402

METHOD = 2                                # how results are worked out; a change rebuilds the record from the saved scans
KEEP = {"intraday": 7, "swing": 30}       # days of detail in track.json
SWING_TRIGGER_DAYS = 3                    # sessions
SWING_HOLD = {"Pullback": 10, "Tight base": 10, "CANSLIM": 30, "Minervini": 30}   # sessions, then the time exit
SETUPS = (("pullbacks", "Pullback"), ("bases", "Tight base"), ("canslim", "CANSLIM"), ("minervini", "Minervini"))
SQUARE_OFF = dt.time(15, 15)
GIVE_UP_DAYS = 45                         # an intraday setup still without prices after this long is closed as "no data"


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


def cost_r(kind, fill, unit):
    """Round-trip costs in R: a % of the trade's value, against the planned risk a share."""
    pct = C.COST_INTRADAY_PCT if kind == "intraday" else C.COST_SWING_PCT
    return pct / 100 * fill / unit if unit else 0.0


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
            t = {"key": key, "d": day, "sym": r["symbol"], "side": r["side"], "trig": r["trigger_time"],
                 "entry": r["entry"], "stop": r["stop"], "t1": r["t1"], "t2": r["t2"], "outcome": "Open",
                 "r": 0.0, "exit": None, "done": False}
            if "taken" in r:            # scans with the filters: taken (alerted) or left out, and why
                if r["taken"]:
                    t["alert"] = r.get("alert_time")
                else:
                    t["out"] = r.get("skip") or {"FAILED": "Fell back inside the range or VWAP before it could be taken.",
                                                 "TRIGGERED (weak RS)": "Broke out while weaker than Nifty."}.get(r.get("status"), "Not taken.")
            out.append(("trade", t))
    return out


def swing_signals(pub, have, existing=()):
    out = []
    recent = {}
    for t in existing:
        if t.get("outcome") != "Not triggered":
            k_ = (t["sym"], {v: k for k, v in SETUPS}[t["setup"]]); recent[k_] = max(recent.get(k_, ""), t["d"])
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
        for setup, label in SETUPS:
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
    if df is None or df[df.index.date == day].empty:
        if (now.date() - day).days > GIVE_UP_DAYS:
            t.update(outcome="No price data", r=0.0, gross=0.0, cost=0.0, ideal=0.0, done=True, void=True, hits={})
        return
    d = df[df.index.date == day]
    s = 1 if t["side"] == "long" else -1
    unit = abs(t["entry"] - t["stop"])
    trig = pd.Timestamp.combine(day, dt.time.fromisoformat(t["trig"]))
    over = now.date() > day or now.time() >= SQUARE_OFF
    # the old reading, kept for comparison: in at the level exactly on the bar after the breakout bar, no costs
    _, ideal, _, _, _ = walk(d[(d.index > trig) & (d.index.time < SQUARE_OFF)], t["side"], t["entry"], t["stop"], t["t1"], t["t2"], over)
    # where it could really be bought: the open of the first bar that starts at or after the alert
    start = pd.Timestamp.combine(day, dt.time.fromisoformat(t["alert"])) if t.get("alert") else trig + pd.Timedelta(minutes=5)
    live = d[(d.index >= start) & (d.index.time < SQUARE_OFF)]
    if live.empty:
        if over:
            t.update(outcome="Not entered: no prices after the alert", r=0.0, gross=0.0, cost=0.0, ideal=round(ideal, 2), done=True, void=True, hits={})
        return
    fill = float(live["open"].iloc[0])
    if s * (fill - t["stop"]) <= 0 or s * (t["t1"] - fill) <= 0:
        why = "back through the stop" if s * (fill - t["stop"]) <= 0 else "at the first target"
        t.update(fill=round(fill, 2), outcome=f"Not entered: price was already {why}", r=0.0, gross=0.0, cost=0.0,
                 ideal=round(ideal, 2), exit=None, done=True, void=True, hits={})
        return
    outcome, r, ex, done, ev = walk(live, t["side"], fill, t["stop"], t["t1"], t["t2"], over, unit=unit)
    c = cost_r("intraday", fill, unit)
    # 5-minute bars are stamped with their start: the level was reached by the bar's end
    t.update(fill=round(fill, 2), outcome=outcome, gross=round(r, 2), cost=round(c, 2), r=round(r - c, 2), ideal=round(ideal, 2),
             exit=round(ex, 2), done=done, hits={k: (v + pd.Timedelta(minutes=5)).strftime("%H:%M") for k, v in ev.items()})
    t.pop("void", None)


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
    hold = SWING_HOLD.get(t.get("setup"), 10)
    after = d[d.index.normalize() >= pd.Timestamp(t["trig"])].iloc[:hold]
    # the trigger day counts from the fill: only its low (stop) and high (targets) can matter, cautious order in walk()
    full = len(after) >= hold
    unit = abs(t["entry"] - t["stop"])
    if fill <= t["stop"] or fill >= t["t1"]:      # gapped past the first target (or the plan is broken): no sensible entry
        t.update(outcome="Not entered: opened beyond the first target", r=0.0, gross=0.0, cost=0.0, ideal=0.0, exit=None,
                 done=True, void=True, hits={}, held=0)
        return
    outcome, r, ex, done, ev = walk(after, "long", fill, t["stop"], t["t1"], t["t2"], full, unit=unit)
    c = cost_r("swing", fill, unit)
    t["hits"] = {k: v.strftime("%Y-%m-%d") for k, v in ev.items()}
    t.update(outcome=outcome, gross=round(r, 2), cost=round(c, 2), r=round(r - c, 2), ideal=round(r, 2), exit=round(ex, 2),
             done=done, held=len(after))
    t.pop("void", None)


def summarize(trades, days):
    """Counts and totals for setups that were entered. r is after costs; gross is before costs; ideal is the old
    reading (in at the level exactly, no costs)."""
    trig = [t for t in trades if t.get("trig") and not t.get("void")]
    fin = [t for t in trig if t["done"]]
    tot = lambda k: round(sum(t.get(k, t["r"]) for t in fin), 2)   # noqa: E731
    return {"signals": sum(days.values()), "triggered": len(trig), "open": len(trig) - len(fin),
            "profit": sum(1 for t in fin if t["r"] > 0), "loss": sum(1 for t in fin if t["r"] < 0),
            "flat": sum(1 for t in fin if t["r"] == 0), "r": tot("r"), "gross": tot("gross"), "ideal": tot("ideal"),
            "not_entered": sum(1 for t in trades if t.get("void")),
            "not_triggered": sum(1 for t in trades if t.get("outcome") == "Not triggered")}


# ------------------------------------------------------------------ the permanent log: PUB/tracklog/<year>.json
def log_load(pub):
    """{kind: {"days": {date: signals}, "trades": {key: trade}}} from every year's file."""
    log = {k: {"days": {}, "trades": {}} for k in KEEP}
    folder = os.path.join(pub, "tracklog")
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        doc = load(os.path.join(folder, f), {}) or {}
        if doc.get("method") != METHOD:
            continue
        for kind in KEEP:
            part = doc.get(kind) or {}
            log[kind]["days"].update(part.get("days") or {})
            log[kind]["trades"].update({t["key"]: t for t in part.get("trades") or []})
    return log


def log_save(pub, log, stamp):
    folder = os.path.join(pub, "tracklog")
    os.makedirs(folder, exist_ok=True)
    years = sorted({k[:4] for kind in KEEP for k in list(log[kind]["days"]) + [t["d"] for t in log[kind]["trades"].values()]})
    for y in years:
        doc = {"schema": 1, "method": METHOD, "updated": stamp, "year": y,
               "costs_pct": {"intraday": C.COST_INTRADAY_PCT, "swing": C.COST_SWING_PCT}}
        for kind in KEEP:
            doc[kind] = {"days": {d: n for d, n in sorted(log[kind]["days"].items()) if d[:4] == y},
                         "trades": sorted((t for t in log[kind]["trades"].values() if t["d"][:4] == y), key=lambda t: t["key"])}
        export._dump(os.path.join(folder, f"{y}.json"), export.clean(doc))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    pub = sys.argv[1]
    now = now_ist().replace(tzinfo=None)
    path = os.path.join(pub, "track.json")
    doc = load(path, {}) or {}
    log = log_load(pub)
    if doc.get("method") != METHOD:
        # results are worked out differently from here on: intraday is rebuilt from the saved scans, swing is re-scored
        doc.pop("intraday", None)
        for t in (doc.get("swing") or {}).get("trades", []):
            if t.get("outcome") != "Not triggered":
                t["done"] = False
    for kind in KEEP:
        k = doc.setdefault(kind, {"trades": [], "days": {}})
        k["trades"] = k["trades"] + k.pop("others", [])     # one working list; split again when saved

    # new setups from the history files
    for kind, fn in (("intraday", intraday_signals), ("swing", swing_signals)):
        k = doc[kind]
        have = {t["key"] for t in k["trades"]} | set(log[kind]["trades"])
        for item in (fn(pub, have, k["trades"]) if kind == "swing" else fn(pub, have)):
            if item[0] == "day":
                k["days"][item[1]] = item[2]
            else:
                k["trades"].append(item[1])
        if kind == "intraday":   # a breakout left out at one scan can be taken at a later one: today's latest scan decides
            today = now.date().isoformat()
            fresh = {item[1]["key"]: item[1] for item in fn(pub, set()) if item[0] == "trade" and item[1]["d"] == today}
            for t in k["trades"]:
                f = fresh.get(t["key"])
                if f and (f.get("alert"), f.get("out")) != (t.get("alert"), t.get("out")):
                    for key in ("alert", "out", "void"):
                        t.pop(key, None)
                    t.update({key: f[key] for key in ("alert", "out") if key in f}, done=False)
                    log[kind]["trades"].pop(t["key"], None)

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

    stamp = now_ist().isoformat(timespec="seconds")
    for kind, days in KEEP.items():
        k, lg = doc[kind], log[kind]
        # every finished setup goes into the permanent log, with its detail
        lg["days"].update(k["days"])
        for t in k["trades"]:
            if t["done"]:
                lg["trades"][t["key"]] = t
        # track.json: detail inside the window, counts for everything older
        cutoff = (now.date() - dt.timedelta(days=days)).isoformat()
        k["trades"] = [t for t in k["trades"] if not (t["d"] < cutoff and t["done"])]
        k["days"] = {d: n for d, n in k["days"].items() if d >= cutoff}
        old = [t for t in lg["trades"].values() if t["d"] < cutoff and not t.get("out")]
        old_days = {d: n for d, n in lg["days"].items() if d < cutoff}
        ds = sorted(set(old_days) | {t["d"] for t in old})
        k["archive"] = {**summarize(old, old_days), "from": ds[0] if ds else None, "to": ds[-1] if ds else None}
        k.pop("archived_keys", None)
        k["trades"].sort(key=lambda t: (t["d"], t.get("trig") or ""), reverse=True)
        mine, others = [t for t in k["trades"] if not t.get("out")], [t for t in k["trades"] if t.get("out")]
        k["recent"] = summarize(mine, k["days"])
        k["by_day"] = {d: summarize([t for t in mine if t["d"] == d], {d: n}) for d, n in sorted(k["days"].items())}
        k["left_out"] = summarize(others, {})
        k["all_time"] = summarize([t for t in lg["trades"].values() if not t.get("out")] + [t for t in mine if not t["done"]], lg["days"])
        k["all_time_left_out"] = summarize([t for t in lg["trades"].values() if t.get("out")], {})
        k["trades"], k["others"] = mine, others

    cost = {"intraday": C.COST_INTRADAY_PCT, "swing": C.COST_SWING_PCT}
    doc.update(schema=1, method=METHOD, updated=stamp, costs_pct=cost,
               rules={"intraday": "Bought at the open of the first 5-minute bar after the alert, not at the level. First target 1.5R "
                                  "(half booked, stop to the price paid), second 3R, out by 3:15 PM. Results are after costs of "
                                  f"{cost['intraday']:g}% of the trade's value.",
                      "swing": "Triggered within 3 sessions above the setup level (filled at the open if it gaps above); half booked "
                               "at the first target and the stop on the rest moved to the price paid. Pullback and tight base: "
                               "targets 2R and 3R, out at the 10th session. CANSLIM: stop 8% below, targets +20% and +25% (O'Neil). "
                               "Minervini: stop below the last contraction (8% at most), targets 2R and 3R. Both held up to 30 "
                               f"sessions. Results are after costs of {cost['swing']:g}% of the trade's value."})
    export._dump(path, export.clean(doc))
    log_save(pub, log, stamp)
    for kind in KEEP:
        r = doc[kind]["recent"]
        print(f"track {kind}: {r['triggered']} entered, {r['profit']} profit, {r['loss']} loss, {r['open']} open, "
              f"{r['r']:+.2f}R after costs ({r['ideal']:+.2f}R at the level with no costs); "
              f"{len(log[kind]['trades'])} setups in the permanent log")


if __name__ == "__main__":
    main()
