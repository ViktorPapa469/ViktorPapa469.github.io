"""15-minute prices for the app's paper-trade results (Test tab).

  python prices.py intraday PUB          # last 5 sessions of 15-minute bars for every stock in PUB/prices/daily.json
  python prices.py intraday PUB --demo   # made-up bars for today (sample data)

Writes PUB/prices/intraday/<date>.json and refreshes PUB/prices/meta.json. Daily bars are written by
run.py premarket --json. Never fails the run: problems are printed as warnings.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screener import export  # noqa: E402
from screener.data_live import now_ist  # noqa: E402


def log(msg):
    print(f"[{now_ist():%H:%M:%S}] {msg}", flush=True)


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "intraday":
        sys.exit(__doc__)
    pub, demo = sys.argv[2], "--demo" in sys.argv
    try:
        with open(os.path.join(pub, "prices", "daily.json"), encoding="utf-8") as fh:
            symbols = sorted(json.load(fh)["symbols"])
    except (OSError, ValueError, KeyError):
        return log("WARN: no prices/daily.json yet; 15-minute prices skipped")
    if demo:
        from screener.data_demo import DemoData
        bars = DemoData(log).intraday(symbols)
        bars.pop("NIFTY 50", None)
        bars = {s: df.resample("15min", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna() for s, df in bars.items()}
    else:
        from screener.data_live import LiveData
        raw = LiveData(log)._download([s + ".NS" for s in symbols], period="5d", interval="15m", prepost=False)
        bars = {}
        for t, df in raw.items():
            idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
            df.index = idx.tz_convert("Asia/Kolkata")
            bars[t[:-3]] = df
    if not bars:
        return log("WARN: no 15-minute prices available")
    days = export.write_intraday_prices(pub, bars, now_ist().isoformat(timespec="seconds"))
    log(f"15-minute prices: {len(bars)} stocks, sessions {', '.join(str(d) for d in days)}")


if __name__ == "__main__":
    main()
