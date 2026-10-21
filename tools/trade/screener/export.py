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
