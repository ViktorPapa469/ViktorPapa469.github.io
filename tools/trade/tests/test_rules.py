"""Tests for the live scan's filters and limits (screener/orb.py), the trade plan (screener/plan.py) and the track
record (track.py).  Run:  python tools/trade/tests/test_rules.py   (no internet needed; prices are made up)"""
import datetime as dt
import json
import os
import sys
import tempfile

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import config as C  # noqa: E402
import track  # noqa: E402
from screener import orb  # noqa: E402
from screener.plan import walk  # noqa: E402

DAY = dt.date(2026, 11, 4)
N = 0


def test(name, fn):
    global N
    fn()
    N += 1
    print("ok -", name)


def near(a, b, tol=0.011):
    assert abs(a - b) <= tol, (a, b)


def bars(rows, start="09:15", tz="Asia/Kolkata"):
    """5-minute bars from [(open, high, low, close, volume), ...]."""
    idx = pd.date_range(pd.Timestamp.combine(DAY, dt.time.fromisoformat(start)), periods=len(rows), freq="5min", tz=tz)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx).astype(float)


def flat(px, n, vol=1000):
    return [(px, px + 0.1, px - 0.1, px, vol)] * n


# opening range 99-101 on 3000 shares, then a close above 101 at 09:30 and a drift up
def breakout(after, vol=1000, base=100.0):
    return bars([(base, base + 1, base - 1, base, vol)] * 3 + after)


UP = [(101.0, 101.2, 100.9, 101.15, 1500), (101.15, 101.25, 101.05, 101.2, 1000), (101.2, 101.3, 101.1, 101.2, 1000)]
NIFTY = bars(flat(25000, 6))


def w(sym, ind="Banks", side="long"):
    return {"symbol": sym, "side": side, "atr": 2.0, "industry": ind, "lot": None}


def row(res, sym):
    return [r for r in res["rows"] if r["symbol"] == sym][0]


# ------------------------------------------------------------------ the plan
def t_walk_default_unit():
    b = bars([(100, 100.5, 99.5, 100, 1), (100, 100.2, 98.9, 99, 1)], start="09:35", tz=None)
    out, r, ex, done, _ = walk(b, "long", 100, 99, 101.5, 103, False)
    assert (out, done, ex) == ("Stop", True, 99) and r == -1.0


def t_walk_late_fill_costs_more():
    # planned: in at 100, stop 99 (1R = 1). Bought at 100.3 instead: the stop loses 1.3R, the first target pays less
    b = bars([(100.3, 100.5, 98.9, 99, 1)], start="09:35", tz=None)
    near(walk(b, "long", 100.3, 99, 101.5, 103, False, unit=1.0)[1], -1.3)
    b = bars([(100.3, 101.6, 100.2, 101.5, 1), (101.5, 101.6, 100.2, 100.4, 1)], start="09:35", tz=None)
    out, r, _, done, _ = walk(b, "long", 100.3, 99, 101.5, 103, False, unit=1.0)
    assert out == "First target, rest out at entry" and done
    near(r, 0.6)        # half of 1.2R; the rest came back to the price paid


def t_walk_short():
    b = bars([(100, 100.2, 98.4, 98.5, 1), (98.5, 98.6, 96.9, 97, 1)], start="09:35", tz=None)
    out, r, _, _, _ = walk(b, "short", 100, 101, 98.5, 97, False)
    assert out == "Both targets"
    near(r, 2.25)


# ------------------------------------------------------------------ the live scan
def t_taken_when_everything_passes():
    res = orb.evaluate([w("AAA")], {"AAA": breakout(UP), "NIFTY 50": NIFTY}, orv={"AAA": 1500})
    r = row(res, "AAA")
    assert r["status"] == "TRIGGERED" and r["taken"] and r["alert_time"] == "09:45", r
    near(r["rvol_open"], 2.0)
    assert res["taken"]["AAA"]["entry"] == 101 and res["limits"]["open"] == 1


def t_low_volume_is_skipped():
    res = orb.evaluate([w("AAA")], {"AAA": breakout(UP), "NIFTY 50": NIFTY}, orv={"AAA": 3000})
    r = row(res, "AAA")
    assert r["status"] == "SKIPPED" and "Opening volume" in r["skip"] and not res["taken"], r


def t_no_volume_history_does_not_block():
    res = orb.evaluate([w("AAA")], {"AAA": breakout(UP), "NIFTY 50": NIFTY}, orv={})
    assert row(res, "AAA")["status"] == "TRIGGERED" and res["limits"]["volume_filter"] is False


def t_extended_is_skipped_until_it_comes_back():
    far = [(101.0, 102.2, 100.9, 102.0, 1500), (102.0, 102.3, 101.9, 102.1, 1000)]     # stop 100.5ish; far past 0.5R
    res = orb.evaluate([w("AAA")], {"AAA": breakout(far), "NIFTY 50": NIFTY}, orv={"AAA": 1500})
    r = row(res, "AAA")
    assert r["status"] == "SKIPPED" and "past the level" in r["skip"], r
    back = far + [(102.1, 102.1, 101.1, 101.2, 1000)]
    res = orb.evaluate([w("AAA")], {"AAA": breakout(back), "NIFTY 50": NIFTY}, orv={"AAA": 1500})
    assert row(res, "AAA")["status"] == "TRIGGERED"


def t_weak_against_nifty_is_not_taken():
    strong = bars([(25000, 25010, 24990, 25000, 1)] * 3 + [(25000, 25600, 25000, 25500, 1)] * 3)
    res = orb.evaluate([w("AAA")], {"AAA": breakout(UP), "NIFTY 50": strong}, orv={"AAA": 1500})
    assert row(res, "AAA")["status"] == "TRIGGERED (weak RS)" and not res["taken"]


def t_position_and_sector_limits():
    b = {s: breakout(UP) for s in "ABCDE"}
    b["NIFTY 50"] = NIFTY
    watch = [w("A", "Banks"), w("B", "Banks"), w("C", "IT"), w("D", "Autos"), w("E", "Metals")]
    res = orb.evaluate(watch, b, orv={s: 1500 for s in "ABCDE"})
    st = {r["symbol"]: r for r in res["rows"]}
    assert [st[s]["status"] for s in "ABCDE"] == ["TRIGGERED", "SKIPPED", "TRIGGERED", "TRIGGERED", "SKIPPED"], \
        {s: (st[s]["status"], st[s].get("skip")) for s in st}
    assert "Banks" in st["B"]["skip"] and "already open" in st["E"]["skip"]
    assert res["limits"]["open"] == C.MAX_OPEN_POSITIONS == 3


def t_taken_levels_and_alert_stay_fixed():
    b1 = {"AAA": breakout(UP), "NIFTY 50": NIFTY}
    r1 = orb.evaluate([w("AAA")], b1, orv={"AAA": 1500})
    more = UP + [(101.2, 101.9, 101.15, 101.8, 900), (101.8, 102.0, 101.6, 101.9, 900)]
    r2 = orb.evaluate([w("AAA")], {"AAA": breakout(more), "NIFTY 50": bars(flat(25000, 8))}, orv={"AAA": 1500}, taken=r1["taken"])
    a, b = row(r1, "AAA"), row(r2, "AAA")
    assert b["taken"] and b["alert_time"] == a["alert_time"] == "09:45" and b["entry"] == a["entry"] and b["stop"] == a["stop"]
    assert r2["taken"] == r1["taken"] and r2["limits"]["open"] == 1


def t_daily_loss_limit_stops_new_setups():
    # three setups taken at 09:45, all stopped by 10:00; a fourth breaks out afterwards
    lose = UP + [(101.2, 101.2, 99.0, 99.2, 2000), (99.2, 99.4, 99.0, 99.1, 500), (99.1, 99.3, 99.0, 99.1, 500)]
    watch = [w("A", "Banks"), w("C", "IT"), w("D", "Autos")]
    first = orb.evaluate(watch, {**{s: breakout(UP) for s in "ACD"}, "NIFTY 50": NIFTY}, orv={})
    assert first["limits"]["open"] == 3
    late = bars([(100, 101, 99, 100, 1000)] * 3 + flat(100, 5) + [(100, 101.4, 100, 101.3, 1500)])
    b = {**{s: breakout(lose) for s in "ACD"}, "E": late, "NIFTY 50": bars(flat(25000, 9))}
    res = orb.evaluate(watch + [w("E", "Metals")], b, orv={}, taken=first["taken"])
    lim, e = res["limits"], row(res, "E")
    assert lim["open"] == 0 and lim["halted"] and lim["closed_r"] <= -3, lim
    assert e["status"] == "SKIPPED" and "Daily loss limit" in e["skip"], e
    old, C.DAILY_LOSS_LIMIT_R = C.DAILY_LOSS_LIMIT_R, 10      # with a looser limit the same breakout is taken
    try:
        assert row(orb.evaluate(watch + [w("E", "Metals")], b, orv={}, taken=first["taken"]), "E")["status"] == "TRIGGERED"
    finally:
        C.DAILY_LOSS_LIMIT_R = old


def t_scan_clock_sets_the_alert():
    now = pd.Timestamp.combine(DAY, dt.time(9, 52)).tz_localize("Asia/Kolkata")
    res = orb.evaluate([w("AAA")], {"AAA": breakout(UP), "NIFTY 50": NIFTY}, orv={}, now=now)
    assert row(res, "AAA")["alert_time"] == "09:52"


def t_nothing_new_after_the_watch_window():
    now = pd.Timestamp.combine(DAY, dt.time(13, 0)).tz_localize("Asia/Kolkata")
    res = orb.evaluate([w("AAA")], {"AAA": breakout(UP), "NIFTY 50": NIFTY}, orv={}, now=now)
    assert row(res, "AAA")["status"] == "SKIPPED" and "11:00" in row(res, "AAA")["skip"]


# ------------------------------------------------------------------ the track record
def five(rows, start="09:15"):
    return bars(rows, start=start, tz=None)[["open", "high", "low", "close"]]


def trade(**kw):
    t = {"key": f"{DAY}:AAA:long", "d": DAY.isoformat(), "sym": "AAA", "side": "long", "trig": "09:30", "entry": 101.0,
         "stop": 100.0, "t1": 102.5, "t2": 104.0, "outcome": "Open", "r": 0.0, "exit": None, "done": False}
    t.update(kw)
    return t


AFTER = dt.datetime.combine(DAY, dt.time(16, 0))
DAY_BARS = [(100, 101, 99, 100, 1)] * 3 + [(101, 101.4, 100.9, 101.3, 1),      # 09:30 breakout bar
                                              (101.3, 101.5, 101.2, 101.4, 1),      # 09:35
                                              (101.4, 101.6, 101.3, 101.5, 1),      # 09:40
                                              (101.5, 101.6, 99.8, 99.9, 1)]        # 09:45 stop


def t_track_fills_at_next_bar_after_alert_and_takes_costs():
    t = trade(alert="09:38")
    track.eval_intraday(t, {"AAA": five(DAY_BARS)}, AFTER)
    assert t["fill"] == 101.4 and t["outcome"] == "Stop" and t["done"] and t["hits"] == {"stop": "09:50"}, t
    near(t["gross"], -1.4)                          # bought 0.4 above the level, sized for a 1.00 stop
    near(t["cost"], C.COST_INTRADAY_PCT / 100 * 101.4 / 1.0)
    near(t["r"], t["gross"] - t["cost"])
    near(t["ideal"], -1.0)                          # the old reading: in at 101 exactly, no costs


def t_track_without_alert_uses_bar_after_breakout():
    t = trade()
    track.eval_intraday(t, {"AAA": five(DAY_BARS)}, AFTER)
    assert t["fill"] == 101.3
    near(t["gross"], -1.3)


def t_track_not_entered_when_already_through_stop():
    rows = DAY_BARS[:4] + [(99.9, 100.0, 99.5, 99.6, 1)]
    t = trade()
    track.eval_intraday(t, {"AAA": five(rows)}, AFTER)
    assert t["void"] and t["done"] and t["r"] == 0 and "Not entered" in t["outcome"], t
    s = track.summarize([t], {DAY.isoformat(): 5})
    assert s["triggered"] == 0 and s["not_entered"] == 1 and s["signals"] == 5


def t_track_summary_keeps_three_readings():
    a, b = trade(alert="09:38"), trade(key="k2", sym="BBB")
    win = DAY_BARS[:6] + [(101.5, 104.2, 101.4, 104.0, 1)]
    track.eval_intraday(a, {"AAA": five(DAY_BARS)}, AFTER)
    track.eval_intraday(b, {"BBB": five(win)}, AFTER)
    assert b["outcome"] == "Both targets"
    s = track.summarize([a, b], {})
    assert (s["triggered"], s["profit"], s["loss"]) == (2, 1, 1)
    assert s["ideal"] > s["gross"] > s["r"], s


def t_track_end_to_end_with_permanent_log():
    """main(): rebuilds from saved scans, follows taken and left-out breakouts, writes track.json and tracklog/."""
    with tempfile.TemporaryDirectory() as pub:
        os.makedirs(os.path.join(pub, "history"))
        old = (DAY - dt.timedelta(days=20)).isoformat()
        rows = [{"symbol": "AAA", "side": "long", "status": "TRIGGERED", "trigger_time": "09:30", "entry": 101.0, "stop": 100.0,
                 "t1": 102.5, "t2": 104.0, "taken": True, "alert_time": "09:38"},
                {"symbol": "BBB", "side": "long", "status": "SKIPPED", "trigger_time": "09:30", "entry": 101.0, "stop": 100.0,
                 "t1": 102.5, "t2": 104.0, "taken": False, "skip": "Opening volume was 0.8x its usual"},
                {"symbol": "CCC", "side": "long", "status": "WAITING"}]
        legacy = [{"symbol": "AAA", "side": "long", "status": "FAILED", "trigger_time": "09:30", "entry": 101.0, "stop": 100.0,
                   "t1": 102.5, "t2": 104.0}]
        for day, rr in ((DAY.isoformat(), rows), (old, legacy)):
            with open(os.path.join(pub, "history", f"{day}_orb.json"), "w") as fh:
                json.dump({"date": day, "rows": rr}, fh)
        # an old-style track.json (no method): must be rebuilt, not trusted
        with open(os.path.join(pub, "track.json"), "w") as fh:
            json.dump({"intraday": {"trades": [], "days": {}, "archive": {"triggered": 45, "r": 11.88}, "archived_keys": [f"{old}:AAA:long"]}}, fh)
        win = DAY_BARS[:6] + [(101.5, 104.2, 101.4, 104.0, 1)]

        def fake(symbols, **kw):
            if kw.get("interval") != "5m":
                return {}
            day = five(DAY_BARS)
            prev = day.copy()
            prev.index = prev.index - pd.Timedelta(days=20)
            both = pd.concat([prev, day])
            w_ = five(win)
            return {s: (both if s == "AAA" else w_) for s in symbols}

        real_yahoo, real_now, argv = track.yahoo, track.now_ist, sys.argv
        track.yahoo = fake
        track.now_ist = lambda: pd.Timestamp.combine(DAY, dt.time(16, 0)).tz_localize("Asia/Kolkata")
        sys.argv = ["track.py", pub]
        try:
            track.main()
            track.main()      # a second run must change nothing
        finally:
            track.yahoo, track.now_ist, sys.argv = real_yahoo, real_now, argv
        doc = json.load(open(os.path.join(pub, "track.json")))
        k = doc["intraday"]
        assert doc["method"] == track.METHOD and "archived_keys" not in k
        assert [t["sym"] for t in k["trades"]] == ["AAA"] and [t["sym"] for t in k["others"]] == ["BBB"], k
        assert k["recent"]["triggered"] == 1 and k["recent"]["loss"] == 1 and k["left_out"]["profit"] == 1
        assert k["archive"]["triggered"] == 1 and k["archive"]["from"] == old       # rebuilt from the old scan
        assert k["all_time"]["triggered"] == 2 and k["all_time_left_out"]["triggered"] == 1
        log = json.load(open(os.path.join(pub, "tracklog", "2026.json")))
        keys = sorted(t["key"] for t in log["intraday"]["trades"])
        assert keys == sorted([f"{DAY}:AAA:long", f"{DAY}:BBB:long", f"{old}:AAA:long"]), keys
        assert all("fill" in t and "gross" in t and "ideal" in t for t in log["intraday"]["trades"])


for name, fn in list(globals().items()):
    if name.startswith("t_") and callable(fn):
        test(name[2:].replace("_", " "), fn)
print(f"{N} tests passed")
