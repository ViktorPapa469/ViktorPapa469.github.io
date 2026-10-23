"""JSON for the phone app (viktorpapa469.github.io/trade/).

Position sizes are NOT stored here: the data is published from a public repo,
so the app works them out on the phone from the capital and risk you set there.
"""
import datetime as dt
import json
import math
import os

import numpy as np
import pandas as pd

SCHEMA = 1
KEEP_DAYS = 30


def clean(x):
    """Make numpy/pandas values JSON-safe; NaN/inf become null."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (pd.Timestamp, dt.datetime)):
        return x.isoformat()
    if isinstance(x, dt.date):
        return x.isoformat()
    return x


def _pick(p, keys):
    return {k: p.get(k) for k in keys if k in p}


INTRADAY_KEYS = ("symbol", "industry", "side", "price", "chg1", "score", "reasons", "warnings",
                 "pdh", "pdl", "atr", "lot", "gap_pct", "est_stop_dist")
SWING_KEYS = ("symbol", "industry", "setup", "price", "chg1", "score", "reasons", "warnings",
              "entry", "stop", "t1", "t2", "risk_pct", "lot")
ORB_KEYS = ("symbol", "side", "industry", "lot", "status", "last", "chg", "rs", "orh", "orl", "vwap",
            "trigger_time", "breakout_vol", "entry", "stop", "t1", "t2", "extended")


def premarket_payload(ctx, notes, generated):
    reg, res = ctx["regime"], ctx["result"]
    sectors = [{"name": n, "n": int(r["n"]), "rs20": r["rs20"], "rs5": r["rs5"], "score": r["score"]}
               for n, r in res["sectors"].iterrows()]
    ev = ctx["events"]
    events = [{"symbol": r["symbol"], "date": r["date"], "purpose": r["purpose"]} for _, r in ev.iterrows()] if len(ev) else []
    return clean({
        "schema": SCHEMA, "kind": "premarket", "date": ctx["date"], "generated": generated,
        "as_of": ctx["as_of_date"], "demo": ctx["demo"],
        "regime": {k: reg.get(k) for k in ("label", "bias", "size_mult", "nifty", "nifty_chg", "nifty_vs20",
                                           "nifty_vs50", "nifty_ret5", "bank", "bank_chg", "vix", "vix_chg")},
        "preopen": ctx["preopen_breadth"], "fii_dii": ctx["fii_dii"], "cues": ctx["cues"],
        "sectors": sectors, "events": events,
        "longs": [_pick(p, INTRADAY_KEYS) for p in res["longs"]],
        "shorts": [_pick(p, INTRADAY_KEYS) for p in res["shorts"]],
        "pullbacks": [_pick(p, SWING_KEYS) for p in res["pullbacks"]],
        "bases": [_pick(p, SWING_KEYS) for p in res["bases"]],
        "canslim": [_pick(p, SWING_KEYS) for p in res.get("canslim", [])],
        "minervini": [_pick(p, SWING_KEYS) for p in res.get("minervini", [])],
        "meta": {"universe": ctx["universe"], "priced": ctx["priced"], "liquid": res["liquid_count"],
                 "oi_date": ctx.get("oi_date_iso")},
        "notes": notes,
    })


def orb_payload(date, res, size_mult, notes, generated, demo):
    return clean({
        "schema": SCHEMA, "kind": "orb", "date": date, "generated": generated, "demo": demo,
        "bars_to": res["as_of"].strftime("%H:%M") if res.get("as_of") is not None else None,
        "nifty_chg": res.get("nifty_chg"), "nifty_above_vwap": res.get("nifty_above_vwap"),
        "size_mult": size_mult, "rows": [_pick(r, ORB_KEYS) for r in res["rows"]], "notes": notes,
    })


def empty_orb(date, size_mult, message, generated, demo):
    return clean({"schema": SCHEMA, "kind": "orb", "date": date, "generated": generated, "demo": demo,
                  "bars_to": None, "nifty_chg": None, "nifty_above_vwap": None, "size_mult": size_mult,
                  "rows": [], "notes": [message]})


def write(out_dir, name, payload):
    """Write <name>.json plus a dated copy in history/, and refresh index.json."""
    os.makedirs(os.path.join(out_dir, "history"), exist_ok=True)
    _dump(os.path.join(out_dir, f"{name}.json"), payload)
    _dump(os.path.join(out_dir, "history", f"{payload['date']}_{name}.json"), payload)
    hist = os.path.join(out_dir, "history")
    cutoff = (dt.date.fromisoformat(payload["date"]) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    for f in os.listdir(hist):
        if f[:10] < cutoff:
            os.remove(os.path.join(hist, f))
    days = sorted({f[:10] for f in os.listdir(hist) if f.endswith(".json")}, reverse=True)
    _dump(os.path.join(out_dir, "index.json"), {"schema": SCHEMA, "updated": payload["generated"], "days": days})


def _dump(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


# ------------------------------------------------------------------ prices for paper-trade results
DAILY_KEEP = 90       # trading days of daily bars published
INTRADAY_KEEP = 30    # calendar days of 15-minute files kept


def _r(x):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(float(x), 2)


def write_daily_prices(out_dir, daily, generated):
    """prices/daily.json: one shared date list and, per symbol, [opens, highs, lows, closes] aligned to it."""
    dates = sorted({d for df in daily.values() for d in df.index[-DAILY_KEEP:]})[-DAILY_KEEP:]
    idx = pd.DatetimeIndex(dates)
    syms = {}
    for s, df in sorted(daily.items()):
        sub = df.reindex(idx)
        syms[s] = [[_r(x) for x in sub[c]] for c in ("open", "high", "low", "close")]
    os.makedirs(os.path.join(out_dir, "prices"), exist_ok=True)
    _dump(os.path.join(out_dir, "prices", "daily.json"),
          {"schema": SCHEMA, "updated": generated, "dates": [d.strftime("%Y-%m-%d") for d in idx], "symbols": syms})
    _prices_meta(out_dir, generated)


def write_intraday_prices(out_dir, bars, generated):
    """prices/intraday/<date>.json: 15-minute bars per trading day (times are bar starts, IST)."""
    by_day = {}
    for s, df in bars.items():
        for day, g in df.groupby(df.index.date):
            by_day.setdefault(day, {})[s] = g
    folder = os.path.join(out_dir, "prices", "intraday")
    os.makedirs(folder, exist_ok=True)
    for day, symbols in by_day.items():
        times = sorted({t.strftime("%H:%M") for g in symbols.values() for t in g.index})
        out = {}
        for s, g in sorted(symbols.items()):
            g = g.copy()
            g.index = [t.strftime("%H:%M") for t in g.index]
            g = g[~g.index.duplicated(keep="last")].reindex(times)
            out[s] = [[_r(x) for x in g[c]] for c in ("open", "high", "low", "close")]
        _dump(os.path.join(folder, f"{day.isoformat()}.json"),
              {"schema": SCHEMA, "updated": generated, "date": day.isoformat(), "times": times, "symbols": out})
    cutoff = (dt.date.today() - dt.timedelta(days=INTRADAY_KEEP)).isoformat()
    for f in os.listdir(folder):
        if f[:10] < cutoff:
            os.remove(os.path.join(folder, f))
    _prices_meta(out_dir, generated)
    return sorted(by_day)


def _prices_meta(out_dir, generated):
    base = os.path.join(out_dir, "prices")
    folder = os.path.join(base, "intraday")
    days = sorted((f[:10] for f in os.listdir(folder) if f.endswith(".json")), reverse=True) if os.path.isdir(folder) else []
    daily = None
    try:
        with open(os.path.join(base, "daily.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        daily = d["dates"][-1] if d.get("dates") else None
    except (OSError, ValueError, KeyError):
        pass
    _dump(os.path.join(base, "meta.json"), {"schema": SCHEMA, "updated": generated, "daily_to": daily, "intraday_days": days})


def write_analysis(out_dir, ctx, res, generated):
    """analysis.json: every F&O stock checked against each screener rule, for the app's Analyse button."""
    from .analysis import rule_checks
    lists = {}
    for key, label in (("longs", "Intraday longs"), ("shorts", "Intraday shorts"), ("pullbacks", "Swing pullbacks"), ("bases", "Swing tight bases"),
                       ("canslim", "CANSLIM"), ("minervini", "Minervini")):
        for i, p in enumerate(res.get(key, [])):
            lists.setdefault(p["symbol"], []).append(f"{label} #{i + 1}")
    stocks = {}
    for sym, r in res["features"].iterrows():
        stocks[sym] = {"industry": r.industry, "price": r.price, "chg1": r.chg1, "event": r.event or None,
                       "lists": lists.get(sym, []), "groups": rule_checks(r, res["top"], res["bottom"])}
    _dump(os.path.join(out_dir, "analysis.json"), clean({"schema": SCHEMA, "date": ctx["date"], "as_of": ctx["as_of_date"],
                                                       "generated": generated, "stocks": stocks,
                                                       "sectors": {"top": sorted(res["top"]), "bottom": sorted(res["bottom"])},
                                                       "market_up": ctx["regime"].get("label") == "Uptrend",
                                                       "rs_dist": [round(x, 2) for x in res.get("rs_dist", [])]}))
