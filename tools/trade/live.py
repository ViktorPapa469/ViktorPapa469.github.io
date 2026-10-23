"""Minute-by-minute market snapshot from NSE for the phone app: PUB/live.json.

  python live.py PUB

Reads NSE's own live pages (the same data nseindia.com shows):
  - market status (open / pre-open / closed; a holiday shows as closed),
  - Nifty 50, Nifty Bank and India VIX (allIndices),
  - every F&O stock: last price, change, day open / high / low (equity-stockIndices, "SECURITIES IN F&O"),
  - before 9:15, the pre-open session's indicative prices instead (market-data-pre-open, key FO).
Exit codes: 0 written, 2 NSE unreachable (the previous live.json is kept), 3 market closed all day (holiday).
NSE's figures are its own; anything published is for market study, as the app's terms say.
"""
import datetime as dt
import json
import os
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screener.data_live import NSEClient, now_ist  # noqa: E402
from screener import export  # noqa: E402

INDICES = {"NIFTY 50": "NIFTY 50", "NIFTY BANK": "BANK NIFTY", "INDIA VIX": "INDIA VIX"}


def num(x):
    try:
        f = float(str(x).replace(",", ""))
        return None if f != f else round(f, 2)
    except (TypeError, ValueError):
        return None


def fno_symbols(pub):
    """The F&O stocks the screener covers (from the last screen's rule check)."""
    try:
        with open(os.path.join(pub, "analysis.json"), encoding="utf-8") as fh:
            return set(json.load(fh).get("stocks", {}))
    except (OSError, ValueError):
        return set()


def yahoo(symbols, out, errors):
    """Fallback for stocks NSE didn't give: today's 1-minute bars from Yahoo Finance (a minute or two behind)."""
    try:
        import yfinance as yf
        data = yf.download([s + ".NS" for s in symbols], period="2d", interval="1m", group_by="ticker",
                           auto_adjust=False, threads=True, progress=False)
    except Exception as e:  # noqa: BLE001
        return errors.append(f"yahoo: {str(e)[:120]}")
    today = now_ist().date()
    n = 0
    for s in symbols:
        try:
            df = data[s + ".NS"].dropna(subset=["Close"])
            idx = df.index.tz_convert("Asia/Kolkata") if df.index.tz is not None else df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
            df.index = idx
            day, before = df[df.index.date == today], df[df.index.date < today]
            if day.empty:
                continue
            prev = float(before["Close"].iloc[-1]) if len(before) else None
            last = float(day["Close"].iloc[-1])
            out["stocks"][s] = [num(last), num((last / prev - 1) * 100) if prev else None, num(day["Open"].iloc[0]),
                                num(day["High"].max()), num(day["Low"].min()), num(prev)]
            n += 1
        except Exception:  # noqa: BLE001
            continue
    if n:
        out["source"] = (out["source"] + " + " if out["source"] else "") + f"Yahoo ({n})"


CUES = {"ES=F": "S&P 500 futures", "NQ=F": "Nasdaq futures", "^N225": "Nikkei", "^HSI": "Hang Seng",
        "USDINR=X": "USD/INR", "BZ=F": "Brent crude", "GC=F": "Gold"}


def cues(out, errors):
    """World markets that trade before and during Indian hours (Yahoo daily bars: today's bar moves live)."""
    try:
        import yfinance as yf
        data = yf.download(list(CUES), period="5d", interval="1d", group_by="ticker", auto_adjust=False,
                           threads=True, progress=False)
        res = []
        for t, name in CUES.items():
            try:
                c = data[t]["Close"].dropna()
                if len(c) >= 2:
                    res.append({"name": name, "last": num(c.iloc[-1]), "chg_pct": num((c.iloc[-1] / c.iloc[-2] - 1) * 100)})
            except Exception:  # noqa: BLE001
                continue
        out["cues"] = res
    except Exception as e:  # noqa: BLE001
        errors.append(f"cues: {str(e)[:120]}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    pub = sys.argv[1]
    now = now_ist()
    nse = NSEClient()
    errors = []
    out = {"schema": 1, "errors": errors, "source": None, "generated": now.isoformat(timespec="seconds"), "date": now.date().isoformat(),
           "status": None, "nse_time": None, "indices": {}, "breadth": None, "stocks": {}, "phase": None}

    try:
        ms = nse.api("/api/marketStatus")
        cm = next((m for m in ms.get("marketState", []) if m.get("market") == "Capital Market"), {})
        out["status"] = cm.get("marketStatus")
        out["trade_date"] = cm.get("tradeDate")
    except Exception as e:  # noqa: BLE001
        errors.append(f"market status: {str(e)[:120]}")

    hm = now.hour * 100 + now.minute
    preopen = 900 <= hm < 915
    out["phase"] = "early" if hm < 900 else "preopen" if preopen else "open" if 915 <= hm < 1530 else "closed"
    cues(out, errors)
    got = bool(out.get("cues"))
    if hm < 900:   # NSE has nothing new before the 9:00 pre-open: world markets only
        if not got:
            return 2
        export._dump(os.path.join(pub, "live.json"), out)
        print(f"live {now:%H:%M}: world markets only (before 9:00)")
        return 0
    try:
        for r in nse.api("/api/allIndices").get("data", []):
            name = INDICES.get(str(r.get("index", "")).upper())
            if name:
                out["indices"][name] = {"last": num(r.get("last")), "chg": num(r.get("percentChange")),
                                        "open": num(r.get("open")), "high": num(r.get("high")),
                                        "low": num(r.get("low")), "prev": num(r.get("previousClose"))}
        got = got or bool(out["indices"])
    except Exception as e:  # noqa: BLE001
        errors.append(f"indices: {str(e)[:120]}")

    try:
        if preopen:
            js = nse.api("/api/market-data-pre-open", {"key": "FO"})
            adv = dec = 0
            for item in js.get("data", []):
                m = item.get("metadata", {})
                sym, iep, chg = m.get("symbol"), num(m.get("iep") or m.get("lastPrice")), num(m.get("pChange"))
                if sym and iep:
                    out["stocks"][sym] = [iep, chg, None, None, None, num(m.get("previousClose"))]
                    adv += (chg or 0) > 0
                    dec += (chg or 0) < 0
            out["breadth"] = {"adv": adv, "dec": dec}
            out["source"] = "NSE pre-open"
        else:
            fno = fno_symbols(pub)
            for index in ("SECURITIES IN F&O", "NIFTY 500"):
                try:
                    # NSE wants %20 for spaces (requests would send "+", which NSE answers with 404)
                    js = nse.api("/api/equity-stockIndices?index=" + quote(index, safe=""))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{index}: {str(e)[:120]}")
                    continue
                out["nse_time"] = js.get("timestamp")
                for r in js.get("data", []):
                    sym = r.get("symbol")
                    if not sym or r.get("priority") == 1 or (index != "SECURITIES IN F&O" and fno and sym not in fno):
                        continue
                    out["stocks"][sym] = [num(r.get("lastPrice")), num(r.get("pChange")), num(r.get("open")),
                                          num(r.get("dayHigh")), num(r.get("dayLow")), num(r.get("previousClose"))]
                if out["stocks"]:
                    out["source"] = "NSE " + index
                    break
            missing = sorted(set(fno) - set(out["stocks"]))
            if missing and hm >= 915:
                yahoo(missing, out, errors)
            out["breadth"] = {"adv": sum(1 for v in out["stocks"].values() if (v[1] or 0) > 0),
                              "dec": sum(1 for v in out["stocks"].values() if (v[1] or 0) < 0)}
        got = got or bool(out["stocks"])
    except Exception as e:  # noqa: BLE001
        errors.append(f"stock prices: {str(e)[:120]}")

    if not got:
        print("live: NSE unreachable; previous live.json kept")
        return 2
    export._dump(os.path.join(pub, "live.json"), out)
    n50 = out["indices"].get("NIFTY 50", {})
    print(f"live {now:%H:%M}: {out['status']}, Nifty {n50.get('last')} ({n50.get('chg')}%), {len(out['stocks'])} stocks from {out['source']}"
          + (f"; problems: {errors}" if errors else ""))
    closed = str(out["status"] or "").lower().startswith("close")
    if closed and 916 <= hm < 1529 and now.weekday() < 5:
        return 3   # closed in the middle of the session: a market holiday
    return 0


if __name__ == "__main__":
    sys.exit(main())
