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


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    pub = sys.argv[1]
    now = now_ist()
    nse = NSEClient()
    out = {"schema": 1, "generated": now.isoformat(timespec="seconds"), "date": now.date().isoformat(),
           "status": None, "nse_time": None, "indices": {}, "breadth": None, "stocks": {}, "phase": None}

    try:
        ms = nse.api("/api/marketStatus")
        cm = next((m for m in ms.get("marketState", []) if m.get("market") == "Capital Market"), {})
        out["status"] = cm.get("marketStatus")
        out["trade_date"] = cm.get("tradeDate")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: market status ({str(e)[:80]})")

    hm = now.hour * 100 + now.minute
    preopen = 900 <= hm < 915
    out["phase"] = "preopen" if preopen else "open" if 915 <= hm < 1530 else "closed"
    got = False
    try:
        for r in nse.api("/api/allIndices").get("data", []):
            name = INDICES.get(str(r.get("index", "")).upper())
            if name:
                out["indices"][name] = {"last": num(r.get("last")), "chg": num(r.get("percentChange")),
                                        "open": num(r.get("open")), "high": num(r.get("high")),
                                        "low": num(r.get("low")), "prev": num(r.get("previousClose"))}
        got = bool(out["indices"])
    except Exception as e:  # noqa: BLE001
        print(f"WARN: indices ({str(e)[:80]})")

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
        else:
            js = nse.api("/api/equity-stockIndices", {"index": "SECURITIES IN F&O"})
            out["nse_time"] = js.get("timestamp")
            adv = dec = 0
            for r in js.get("data", []):
                sym = r.get("symbol")
                if not sym or r.get("priority") == 1:   # the index's own row
                    continue
                last, chg = num(r.get("lastPrice")), num(r.get("pChange"))
                out["stocks"][sym] = [last, chg, num(r.get("open")), num(r.get("dayHigh")), num(r.get("dayLow")), num(r.get("previousClose"))]
                adv += (chg or 0) > 0
                dec += (chg or 0) < 0
            out["breadth"] = {"adv": adv, "dec": dec}
        got = got or bool(out["stocks"])
    except Exception as e:  # noqa: BLE001
        print(f"WARN: stock prices ({str(e)[:80]})")

    if not got:
        print("live: NSE unreachable; previous live.json kept")
        return 2
    export._dump(os.path.join(pub, "live.json"), out)
    n50 = out["indices"].get("NIFTY 50", {})
    print(f"live {now:%H:%M}: {out['status']}, Nifty {n50.get('last')} ({n50.get('chg')}%), {len(out['stocks'])} stocks")
    closed = str(out["status"] or "").lower().startswith("close")
    if closed and 916 <= hm < 1529 and now.weekday() < 5:
        return 3   # closed in the middle of the session: a market holiday
    return 0


if __name__ == "__main__":
    sys.exit(main())
