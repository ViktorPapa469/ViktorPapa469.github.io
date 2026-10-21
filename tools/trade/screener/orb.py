"""Live opening-range breakout check with VWAP and relative strength vs Nifty."""
import datetime as dt

import numpy as np
import pandas as pd

import config as C
from .analysis import size


def vwap(df):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan).fillna(1)
    return (tp * vol).cumsum() / vol.cumsum()


def opening_range(df, minutes):
    start = df.index[0].normalize() + pd.Timedelta(hours=9, minutes=15)
    end = start + pd.Timedelta(minutes=minutes)
    orw = df[(df.index >= start) & (df.index < end)]
    return orw, end


def evaluate(watch, bars, mult=1.0):
    """watch: list of dicts with symbol, side, atr, lot (from the morning screen)."""
    nifty = bars.get("NIFTY 50")
    nifty_chg = nifty_above_vwap = None
    if nifty is not None and len(nifty):
        nifty_chg = (nifty["close"].iloc[-1] / nifty["open"].iloc[0] - 1) * 100
        nifty_above_vwap = bool(nifty["close"].iloc[-1] > vwap(nifty).iloc[-1]) if nifty["volume"].sum() else None

    out = []
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

        broke = after[(s * (after["close"] - level)) > 0]
        row.update(last=last, chg=chg, rs=rs, orh=orh, orl=orl, vwap=vw.iloc[-1])
        if broke.empty:
            status = "WAITING"
        else:
            t = broke.index[0]
            brk_vol = after.loc[t, "volume"] / avg_bar_vol if avg_bar_vol else np.nan
            holding = s * (last - vw.iloc[-1]) > 0 and s * (last - level) > -0.1 * w["atr"]
            rs_ok = s * rs > 0
            status = "TRIGGERED" if holding and rs_ok else ("FAILED" if not holding else "TRIGGERED (weak RS)")
            entry = level
            # stop: tighter of the opposite OR edge and VWAP, but never closer than 0.25 x ATR
            cands = [x for x in (orl if s == 1 else orh, vw.loc[t]) if s * (entry - x) > 0]
            stop = max(cands) if s == 1 and cands else (min(cands) if cands else entry - s * 0.5 * w["atr"])
            if abs(entry - stop) < 0.25 * w["atr"]:
                stop = entry - s * 0.25 * w["atr"]
            r = abs(entry - stop)
            row.update(trigger_time=t.strftime("%H:%M"), breakout_vol=brk_vol, entry=entry, stop=stop,
                       t1=entry + s * 1.5 * r, t2=entry + s * 3 * r,
                       qty=size(entry, stop, mult), extended=s * (last - entry) > r)
        row["status"] = status
        out.append(row)

    order = {"TRIGGERED": 0, "TRIGGERED (weak RS)": 1, "WAITING": 2, "RANGE FORMING": 3, "FAILED": 4, "NO DATA": 5}
    out.sort(key=lambda r: (order.get(r["status"], 9), -abs(r.get("rs", 0) or 0)))
    return {"rows": out, "nifty_chg": nifty_chg, "nifty_above_vwap": nifty_above_vwap,
            "as_of": max((b.index[-1] for b in bars.values() if len(b)), default=None)}
