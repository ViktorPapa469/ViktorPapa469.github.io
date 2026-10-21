"""Every NSE and BSE stock checked against the screener's rules, for the app's Analyse button.

  python market.py PUB [--max-minutes 40] [--limit N]

Runs after the close (ci.sh). F&O stocks are left out here: they are analysed with each screen, with open interest,
in PUB/analysis.json. For all other stocks:
  - the lists come from NSE (EQUITY_L.csv: main board and SME) and BSE (the day's equity bhavcopy; only companies
    not also listed on NSE, matched by ISIN);
  - a year of daily prices comes from Yahoo Finance (SYMBOL.NS, or the BSE scrip code .BO);
  - each stock goes through screener.analysis.rule_checks, so the rules are exactly the screener's. Checks a stock
    has no data for (open interest outside F&O, a sector outside the Nifty 500 list) are marked as not available.
Writes PUB/market/rules.json (rule names), PUB/market/index.json (every stock, for search) and
PUB/market/s/<first letter>.json (results), so the phone only downloads the part it needs.
Never fails the run: problems are printed as warnings and whatever was analysed is published.
"""
import datetime as dt
import io
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screener import analysis, export  # noqa: E402
from screener.data_live import LiveData, now_ist, UA  # noqa: E402

np.seterr(all="ignore")
MIN_BARS = 30


def log(msg):
    print(f"[{now_ist():%H:%M:%S}] {msg}", flush=True)


def nse_list(live):
    raw = live.nse.archive("/content/equities/EQUITY_L.csv").decode("utf-8", "ignore")
    df = pd.read_csv(io.StringIO(raw))
    df.columns = [c.strip().upper() for c in df.columns]
    df["SERIES"] = df["SERIES"].astype(str).str.strip()
    df = df[df["SERIES"].isin(["EQ", "BE", "BZ", "SM", "ST"])]
    out = pd.DataFrame({"symbol": df["SYMBOL"].str.strip(), "name": df["NAME OF COMPANY"].str.strip(),
                        "isin": df["ISIN NUMBER"].str.strip(), "exchange": "NSE"})
    out["yahoo"] = out["symbol"] + ".NS"
    return out


def bse_list():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://www.bseindia.com/", "Accept": "*/*"})
    today = now_ist().date()
    for back in range(0, 8):
        d = today - dt.timedelta(days=back)
        if d.weekday() >= 5:
            continue
        url = f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d:%Y%m%d}_F_0000.CSV"
        try:
            r = s.get(url, timeout=30)
            if r.status_code != 200 or b"TckrSymb" not in r.content[:2000]:
                continue
            df = pd.read_csv(io.BytesIO(r.content))
        except Exception:
            continue
        df = df[df["FinInstrmTp"].astype(str).str.upper() == "STK"]
        out = pd.DataFrame({"symbol": df["TckrSymb"].astype(str).str.strip(), "name": df["FinInstrmNm"].astype(str).str.strip(),
                            "isin": df["ISIN"].astype(str).str.strip(), "exchange": "BSE",
                            "yahoo": df["FinInstrmId"].astype(str).str.strip() + ".BO"})
        log(f"BSE bhavcopy {d}: {len(out)} equities")
        return out
    raise RuntimeError("BSE bhavcopy unavailable")


def shard(sym):
    c = sym[:1].upper()
    return c if "A" <= c <= "Z" else "0"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    pub = sys.argv[1]
    max_min = float(sys.argv[sys.argv.index("--max-minutes") + 1]) if "--max-minutes" in sys.argv else 40
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    started = time.time()
    live = LiveData(log)

    try:
        with open(os.path.join(pub, "analysis.json"), encoding="utf-8") as fh:
            fno_doc = json.load(fh)
    except (OSError, ValueError):
        return log("WARN: no analysis.json yet (needs a screen first); market analysis skipped")
    fno = set(fno_doc.get("stocks", {}))
    top, bottom = set(fno_doc.get("sectors", {}).get("top", [])), set(fno_doc.get("sectors", {}).get("bottom", []))

    parts = []
    try:
        parts.append(nse_list(live))
        log(f"NSE list: {len(parts[-1])} equities")
    except Exception as e:
        log(f"WARN: NSE equity list unavailable ({str(e)[:120]})")
    try:
        b = bse_list()
        known = set(parts[0]["isin"]) if parts else set()
        b = b[~b["isin"].isin(known)]
        nse_syms = set(parts[0]["symbol"]) if parts else set()
        b.loc[b["symbol"].isin(nse_syms | fno), "symbol"] = b["symbol"] + ".BO"   # same ticker as an NSE company: keep apart
        parts.append(b)
        log(f"BSE-only equities: {len(b)}")
    except Exception as e:
        log(f"WARN: BSE list unavailable ({str(e)[:120]})")
    if not parts:
        return log("WARN: no stock lists available; market analysis skipped")
    allst = pd.concat(parts, ignore_index=True).drop_duplicates("symbol")
    todo = allst[~allst["symbol"].isin(fno)]
    if limit:
        todo = todo.head(limit)

    nifty = live.index_daily().get("NIFTY 50")
    if nifty is None or len(nifty) < 60:
        return log("WARN: Nifty prices unavailable; market analysis skipped")
    industries = live.industries()
    events = live.events()
    today = now_ist().date()
    ev = {}
    for _, e in (events.iterrows() if len(events) else []):
        days = (e["date"] - today).days if pd.notna(e["date"]) else None
        if days is not None and -2 <= days <= 3:
            ev[e["symbol"]] = "Results just out" if days < 0 else "Results today" if days == 0 else f"Results in {days}d"

    results, schema, done = {}, None, 0
    tickers = list(todo["yahoo"])
    meta = todo.set_index("yahoo")
    step = 240
    for i in range(0, len(tickers), step):
        if time.time() - started > max_min * 60:
            log(f"WARN: time limit reached after {done} stocks; publishing what was analysed")
            break
        raw = live._download(tickers[i:i + step], period="1y", interval="1d")
        for t, df in raw.items():
            try:
                from screener.data_live import _completed_daily
                df = _completed_daily(df)
                if len(df) < MIN_BARS:
                    continue
                m = meta.loc[t]
                sym = m["symbol"]
                f = analysis.stock_features(df, nifty["close"])
                f.update({"industry": industries.get(sym, "Other"), "buildup": "", "oi_chg_pct": np.nan,
                          "lot": np.nan, "gap_pct": np.nan, "event": ev.get(sym, "")})
                r = pd.Series(f)
                groups = analysis.rule_checks(r, top, bottom, fno=False)
                if schema is None:
                    schema = [{"name": g["name"], "items": [[x[0], x[3], x[4]] for x in g["items"]]} for g in groups]
                last = df.iloc[-1]
                results[sym] = {"n": m["name"], "x": m["exchange"], "d": df.index[-1].strftime("%Y-%m-%d"),
                                "p": f["price"], "c": f["chg1"], "o": last["open"], "h": last["high"], "l": last["low"],
                                "i": None if f["industry"] == "Other" else f["industry"], "e": f["event"] or None,
                                "g": [bool(g["pass"]) for g in groups],
                                "v": [[None if x[1] is None else int(bool(x[1])), x[2]] for g in groups for x in g["items"]]}
                done += 1
            except Exception as e:  # noqa: BLE001 - one odd stock never stops the rest
                log(f"WARN: {t} skipped ({str(e)[:80]})")
        log(f"analysed {done} of {len(tickers)}")

    if not results:
        return log("WARN: no stocks analysed; market analysis not published")
    out = os.path.join(pub, "market")
    if os.path.isdir(os.path.join(out, "s")):
        for fname in os.listdir(os.path.join(out, "s")):
            os.remove(os.path.join(out, "s", fname))
    os.makedirs(os.path.join(out, "s"), exist_ok=True)
    stamp = now_ist().isoformat(timespec="seconds")
    as_of = max(x["d"] for x in results.values())
    by = {}
    for sym, x in results.items():
        by.setdefault(shard(sym), {})[sym] = x
    for k, d in by.items():
        export._dump(os.path.join(out, "s", f"{k}.json"), export.clean(d))
    index = [[sym, x["n"], x["x"], shard(sym)] for sym, x in sorted(results.items())]
    names = dict(zip(allst["symbol"], allst["name"]))
    index += [[sym, names.get(sym), "NSE F&O", "fno"] for sym in sorted(fno)]
    export._dump(os.path.join(out, "rules.json"), {"schema": 1, "groups": schema})
    export._dump(os.path.join(out, "index.json"), {"schema": 1, "updated": stamp, "as_of": as_of, "stocks": index})
    log(f"market analysis: {len(results)} stocks (+{len(fno)} F&O in analysis.json), {len(by)} files, "
        f"{(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
