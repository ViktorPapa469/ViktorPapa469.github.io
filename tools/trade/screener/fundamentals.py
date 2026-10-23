"""Company earnings for CANSLIM, from Yahoo Finance, cached in PUB/state/fundamentals.json.

Per stock: latest quarter's EPS growth vs the same quarter a year earlier (and the quarter before, to see whether
growth is accelerating), yearly EPS growth over up to 3 years, return on equity and institutional holding.
Earnings change once a quarter, so each stock is refreshed at most once a week, in the evening run, within a time
limit; the morning screen only reads the cache. Anything Yahoo doesn't have stays empty and shows in the app as
"Not available" (left out of the score).
"""
import datetime as dt
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

MAX_AGE_DAYS = 7


def _eps_row(df):
    if df is None or getattr(df, "empty", True):
        return None
    for name in ("Diluted EPS", "Basic EPS"):
        if name in df.index:
            s = df.loc[name].dropna()
            if len(s):
                return s.sort_index()   # oldest first
    return None


def _growth(new, old):
    if new is None or old is None or not np.isfinite(new) or not np.isfinite(old) or old <= 0:
        return None
    return round((new / old - 1) * 100, 1)


def fetch_one(sym):
    import yfinance as yf
    t = yf.Ticker(sym + ".NS")
    out = {"t": dt.date.today().isoformat()}
    try:
        q = _eps_row(t.quarterly_income_stmt)
        if q is not None and len(q) >= 5:
            out["eps_q"] = _growth(float(q.iloc[-1]), float(q.iloc[-5]))
            if len(q) >= 6:
                out["eps_q_prev"] = _growth(float(q.iloc[-2]), float(q.iloc[-6]))
    except Exception:  # noqa: BLE001
        pass
    try:
        a = _eps_row(t.income_stmt)
        if a is not None and len(a) >= 2:
            yrs = min(3, len(a) - 1)
            new, old = float(a.iloc[-1]), float(a.iloc[-1 - yrs])
            if old > 0 and new > 0:
                out["eps_3y"] = round(((new / old) ** (1 / yrs) - 1) * 100, 1)
                out["eps_years"] = yrs
    except Exception:  # noqa: BLE001
        pass
    try:
        info = t.get_info() or {}
        if out.get("eps_q") is None and info.get("earningsQuarterlyGrowth") is not None:
            out["eps_q"] = round(float(info["earningsQuarterlyGrowth"]) * 100, 1)
        if info.get("returnOnEquity") is not None:
            out["roe"] = round(float(info["returnOnEquity"]) * 100, 1)
        if info.get("heldPercentInstitutions") is not None:
            out["inst"] = round(float(info["heldPercentInstitutions"]) * 100, 1)
    except Exception:  # noqa: BLE001
        pass
    return sym, out


def load(pub):
    try:
        with open(os.path.join(pub, "state", "fundamentals.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def refresh(pub, symbols, log, max_minutes=8):
    """Fetch stale or missing stocks (oldest first) until the time limit; save and return the cache."""
    cache = load(pub)
    cutoff = (dt.date.today() - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
    todo = sorted((s for s in symbols if (cache.get(s) or {}).get("t", "") < cutoff), key=lambda s: (cache.get(s) or {}).get("t", ""))
    if not todo:
        return cache
    start, done = time.time(), 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i in range(0, len(todo), 30):
            if time.time() - start > max_minutes * 60:
                log(f"fundamentals: time limit reached, {len(todo) - done} left for the next run")
                break
            for sym, rec in ex.map(fetch_one, todo[i:i + 30]):
                cache[sym] = rec
                done += 1
    have = sum(1 for s in symbols if (cache.get(s) or {}).get("eps_q") is not None)
    log(f"fundamentals: {done} refreshed; earnings data for {have} of {len(symbols)} stocks")
    os.makedirs(os.path.join(pub, "state"), exist_ok=True)
    with open(os.path.join(pub, "state", "fundamentals.json"), "w", encoding="utf-8") as fh:
        json.dump(cache, fh, separators=(",", ":"))
    return cache
