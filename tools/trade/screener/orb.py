"""Live opening-range breakout check with VWAP and relative strength vs Nifty.

A break of the opening range is only taken (status TRIGGERED, which is what sends the alert) when, at the scan that
sees it, all of these hold:
  - price is holding beyond the range and VWAP, and the stock is beating Nifty (as before);
  - the opening range's volume is at least ORB_MIN_RVOL times the stock's own average for those minutes;
  - price is no more than ORB_MAX_CHASE_R past the level (otherwise it is too late to enter);
  - fewer than MAX_OPEN_POSITIONS setups taken today are still running, none of them in the same sector;
  - the setups already closed today have not lost DAILY_LOSS_LIMIT_R or more.
A break that misses a filter is marked SKIPPED with the reason, and is taken later only if a scan before WATCH_UNTIL
finds every filter met. Once taken, a setup's levels and alert time are fixed for the day (the `taken` record)."""
import numpy as np
import pandas as pd

import config as C
from .analysis import size
from .plan import walk


def vwap(df):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan).fillna(1)
    return (tp * vol).cumsum() / vol.cumsum()


def opening_range(df, minutes):
    start = df.index[0].normalize() + pd.Timedelta(hours=9, minutes=15)
    end = start + pd.Timedelta(minutes=minutes)
    orw = df[(df.index >= start) & (df.index < end)]
    return orw, end


def _hm_add(hm, minutes):
    h, m = map(int, hm.split(":"))
    x = h * 60 + m + minutes
    return f"{x // 60:02d}:{x % 60:02d}"


def progress(df, side, plan):
    """How a taken setup has gone so far on today's bars, by the plan (see plan.walk): bought at the open of the
    first bar that starts at or after the alert. Returns {"open": still running, "r": result so far in R}."""
    h, m = map(int, plan["at"].split(":"))
    after = df[df.index >= df.index[0].normalize() + pd.Timedelta(hours=h, minutes=m)]
    if after.empty:
        return {"open": True, "r": 0.0}
    s, fill = (1 if side == "long" else -1), float(after["open"].iloc[0])
    if s * (fill - plan["stop"]) <= 0 or s * (plan["t1"] - fill) <= 0:   # already through the stop or at the target: no entry
        return {"open": False, "r": 0.0}
    _, r, _, done, _ = walk(after, side, fill, plan["stop"], plan["t1"], plan["t2"], False,
                            unit=abs(plan["entry"] - plan["stop"]))
    return {"open": not done, "r": float(r)}


def evaluate(watch, bars, mult=1.0, orv=None, taken=None, now=None):
    """watch: list of dicts with symbol, side, atr, lot, industry (from the morning screen).
    orv: {symbol: average opening-range volume over the last sessions}; a stock without one skips the volume filter.
    taken: today's record of setups already taken {symbol: {side, at, trig, entry, stop, t1, t2, industry}}.
    now: the clock time of this scan (IST); the alert can't be earlier than the last bar's end or than now."""
    orv = orv or {}
    taken = {k: dict(v) for k, v in (taken or {}).items()}
    nifty = bars.get("NIFTY 50")
    nifty_chg = nifty_above_vwap = None
    if nifty is not None and len(nifty):
        nifty_chg = (nifty["close"].iloc[-1] / nifty["open"].iloc[0] - 1) * 100
        nifty_above_vwap = bool(nifty["close"].iloc[-1] > vwap(nifty).iloc[-1]) if nifty["volume"].sum() else None
    as_of = max((b.index[-1] for b in bars.values() if len(b)), default=None)
    at = None
    if as_of is not None:
        at = (as_of + pd.Timedelta(minutes=5)).strftime("%H:%M")
        if now is not None and now.date() == as_of.date():
            at = max(at, now.strftime("%H:%M"))

    out, cands, n_open, closed_r, open_ind = [], [], 0, 0.0, set()
    for w in watch:
        df = bars.get(w["symbol"])
        row = {"symbol": w["symbol"], "side": w["side"], "industry": w.get("industry", ""), "lot": w.get("lot")}
        if df is None or df.empty:
            out.append({**row, "status": "NO DATA"})
            continue
        orw, or_end = opening_range(df, C.ORB_MINUTES)
        if orw.empty or df.index[-1] < or_end:
            out.append({**row, "status": "RANGE FORMING", "last": df["close"].iloc[-1]})
            continue
        orh, orl = orw["high"].max(), orw["low"].min()
        after = df[df.index >= or_end]
        vw = vwap(df)
        last = df["close"].iloc[-1]
        chg = (last / df["open"].iloc[0] - 1) * 100
        rs = chg - (nifty_chg or 0)
        avg_bar_vol = df["volume"].mean()
        s = 1 if w["side"] == "long" else -1
        level = orh if s == 1 else orl
        usual, or_vol = orv.get(w["symbol"]), float(orw["volume"].sum())
        rvol = or_vol / usual if usual and or_vol > 0 else np.nan

        row.update(last=last, chg=chg, rs=rs, orh=orh, orl=orl, vwap=vw.iloc[-1], rvol_open=rvol)
        tk = taken.get(w["symbol"])
        if tk and tk.get("side") != w["side"]:
            tk = None
        broke = after[(s * (after["close"] - level)) > 0]
        if tk:      # taken earlier today: its levels are fixed; the status only says whether it is still holding
            entry, stop, r = tk["entry"], tk["stop"], abs(tk["entry"] - tk["stop"])
            p = progress(df, w["side"], tk)
            n_open += p["open"]
            closed_r += 0 if p["open"] else p["r"]
            if p["open"] and row["industry"] not in ("", "Other"):
                open_ind.add(row["industry"])
            holding = s * (last - vw.iloc[-1]) > 0 and s * (last - entry) > -0.1 * w["atr"]
            row.update(trigger_time=tk["trig"], breakout_vol=tk.get("bvol"), entry=entry, stop=stop, t1=tk["t1"], t2=tk["t2"],
                       qty=size(entry, stop, mult), extended=s * (last - entry) > r, taken=True, alert_time=tk["at"],
                       plan_open=bool(p["open"]), plan_r=p["r"])
            row["status"] = "TRIGGERED" if holding else "FAILED"
        elif broke.empty:
            row["status"] = "WAITING"
        else:
            t = broke.index[0]
            brk_vol = after.loc[t, "volume"] / avg_bar_vol if avg_bar_vol else np.nan
            holding = s * (last - vw.iloc[-1]) > 0 and s * (last - level) > -0.1 * w["atr"]
            entry = level
            # stop: tighter of the opposite OR edge and VWAP, but never closer than 0.25 x ATR
            cs = [x for x in (orl if s == 1 else orh, vw.loc[t]) if s * (entry - x) > 0]
            stop = max(cs) if s == 1 and cs else (min(cs) if cs else entry - s * 0.5 * w["atr"])
            if abs(entry - stop) < 0.25 * w["atr"]:
                stop = entry - s * 0.25 * w["atr"]
            r = abs(entry - stop)
            row.update(trigger_time=t.strftime("%H:%M"), breakout_vol=brk_vol, entry=entry, stop=stop,
                       t1=entry + s * 1.5 * r, t2=entry + s * 3 * r,
                       qty=size(entry, stop, mult), extended=s * (last - entry) > r, taken=False)
            cands.append((t, row, holding, s * rs > 0, s * (last - entry) / r))
        out.append(row)

    # breaks not yet taken, earliest first, against the filters and the limits as they stand at this scan
    last_take = _hm_add(C.WATCH_UNTIL, 5)
    for t, row, holding, rs_ok, chase in sorted(cands, key=lambda c: c[0]):
        rv, ind = row["rvol_open"], row["industry"]
        skip = None
        if not holding:
            row["status"] = "FAILED"
            continue
        if not pd.isna(rv) and rv < C.ORB_MIN_RVOL:
            skip = f"Opening volume was {rv:.1f}x its usual; the filter needs {C.ORB_MIN_RVOL:g}x or more."
        elif not rs_ok:
            row["status"] = "TRIGGERED (weak RS)"
            continue
        elif chase > C.ORB_MAX_CHASE_R:
            skip = f"Already {chase:.1f}R past the level: too late to enter. It counts again if price comes back within {C.ORB_MAX_CHASE_R:g}R."
        elif at is None or at > last_take:
            skip = f"Past {C.WATCH_UNTIL}: no new breakouts are taken."
        elif closed_r <= -C.DAILY_LOSS_LIMIT_R:
            skip = f"Daily loss limit reached: today's closed setups stand at {closed_r:+.1f}R (limit {C.DAILY_LOSS_LIMIT_R:g}R)."
        elif n_open >= C.MAX_OPEN_POSITIONS:
            skip = f"{C.MAX_OPEN_POSITIONS} setups are already open, the most allowed at once."
        elif C.ONE_PER_SECTOR and ind in open_ind:
            skip = f"A setup in {ind} is already open: one a sector."
        if skip:
            row.update(status="SKIPPED", skip=skip)
            continue
        row.update(status="TRIGGERED", taken=True, alert_time=at, plan_open=True, plan_r=0.0)
        taken[row["symbol"]] = {"side": row["side"], "at": at, "trig": row["trigger_time"], "entry": float(row["entry"]),
                                "stop": float(row["stop"]), "t1": float(row["t1"]), "t2": float(row["t2"]),
                                "bvol": None if pd.isna(row["breakout_vol"]) else float(row["breakout_vol"]), "industry": ind}
        n_open += 1
        if ind not in ("", "Other"):
            open_ind.add(ind)

    order = {"TRIGGERED": 0, "TRIGGERED (weak RS)": 1, "WAITING": 2, "RANGE FORMING": 3, "SKIPPED": 4, "FAILED": 5, "NO DATA": 6}
    out.sort(key=lambda r: (order.get(r["status"], 9), -abs(r.get("rs", 0) or 0)))
    return {"rows": out, "nifty_chg": nifty_chg, "nifty_above_vwap": nifty_above_vwap, "as_of": as_of, "taken": taken,
            "limits": {"open": int(n_open), "max_open": C.MAX_OPEN_POSITIONS, "closed_r": round(float(closed_r), 2),
                       "loss_limit": C.DAILY_LOSS_LIMIT_R, "halted": bool(closed_r <= -C.DAILY_LOSS_LIMIT_R),
                       "min_rvol": C.ORB_MIN_RVOL, "max_chase": C.ORB_MAX_CHASE_R, "volume_filter": bool(orv)}}
