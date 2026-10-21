"""Live data: NSE website/archives + Yahoo Finance (via yfinance).

Every method fails soft: if one source is down, it logs a warning and returns
empty data so the rest of the report still builds.
"""
import datetime as dt
import io
import time
import zipfile

import numpy as np
import pandas as pd
import requests

from .universe import FALLBACK_FNO

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
NSE = "https://www.nseindia.com"
ARCHIVES = "https://nsearchives.nseindia.com"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def now_ist():
    return dt.datetime.now(IST)


class NSEClient:
    """NSE blocks bare requests; warm up cookies from the home page first."""

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": NSE + "/",
        })
        self._warm = False

    def _warmup(self):
        if self._warm:
            return
        for path in ("/", "/market-data/live-equity-market"):
            try:
                self.s.get(NSE + path, timeout=10)
            except requests.RequestException:
                pass
        self._warm = True

    def api(self, path, params=None):
        self._warmup()
        last = None
        for attempt in range(3):
            try:
                r = self.s.get(NSE + path, params=params, timeout=15)
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP {r.status_code}"
                if r.status_code in (401, 403):
                    self._warm = False
                    self._warmup()
            except (requests.RequestException, ValueError) as e:
                last = str(e)
            time.sleep(1 + attempt)
        raise RuntimeError(f"NSE {path}: {last}")

    def archive(self, path):
        r = self.s.get(ARCHIVES + path, timeout=30)
        r.raise_for_status()
        return r.content


class LiveData:
    def __init__(self, log):
        self.log = log
        self.nse = NSEClient()

    # ---------------- F&O universe + open interest ----------------
    def fo_snapshot(self):
        """Latest F&O bhavcopy -> per-stock futures OI, OI change, lot size.

        Returns (DataFrame indexed by symbol, as_of_date). The bhavcopy for a
        session is published in the evening, so before the open this is the
        previous trading day's positioning.
        """
        today = now_ist().date()
        for back in range(0, 10):
            d = today - dt.timedelta(days=back)
            if d.weekday() >= 5:
                continue
            url = f"/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
            try:
                raw = self.nse.archive(url)
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    df = pd.read_csv(z.open(z.namelist()[0]))
            except Exception:
                continue
            fut = df[df["FinInstrmTp"].astype(str).str.upper() == "STF"].copy()
            if fut.empty:
                continue
            lot_col = "NewBrdLotQty" if "NewBrdLotQty" in fut.columns else None
            agg = {"oi": ("OpnIntrst", "sum"), "oi_chg": ("ChngInOpnIntrst", "sum")}
            if lot_col:
                agg["lot"] = (lot_col, "max")
            g = fut.groupby("TckrSymb").agg(**agg)
            if "lot" not in g:
                g["lot"] = np.nan
            prev = (g["oi"] - g["oi_chg"]).replace(0, np.nan)
            g["oi_chg_pct"] = g["oi_chg"] / prev * 100
            g.index.name = "symbol"
            self.log(f"F&O bhavcopy {d}: {len(g)} stock futures")
            return g, d
        self.log("WARN: F&O bhavcopy unavailable - trying lot-size file")
        try:
            raw = self.nse.archive("/content/fo/fo_mktlots.csv").decode("utf-8", "ignore")
            lots = pd.read_csv(io.StringIO(raw))
            lots.columns = [c.strip().upper() for c in lots.columns]
            syms = lots["SYMBOL"].astype(str).str.strip()
            syms = [s for s in syms if s and s.upper() != "SYMBOL"
                    and not s.startswith(("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"))]
            g = pd.DataFrame(index=pd.Index(syms, name="symbol"))
            for c in ("oi", "oi_chg", "oi_chg_pct", "lot"):
                g[c] = np.nan
            return g, None
        except Exception as e:
            self.log(f"WARN: lot-size file failed ({e}) - using built-in F&O list")
        g = pd.DataFrame(index=pd.Index(FALLBACK_FNO, name="symbol"))
        for c in ("oi", "oi_chg", "oi_chg_pct", "lot"):
            g[c] = np.nan
        return g, None

    # ---------------- industries ----------------
    def industries(self):
        try:
            raw = self.nse.archive("/content/indices/ind_nifty500list.csv").decode("utf-8", "ignore")
            df = pd.read_csv(io.StringIO(raw))
            return dict(zip(df["Symbol"].str.strip(), df["Industry"].str.strip()))
        except Exception as e:
            self.log(f"WARN: industry list failed ({e})")
            return {}

    # ---------------- prices (Yahoo) ----------------
    @staticmethod
    def _yf():
        try:
            import yfinance as yf  # imported lazily so --demo works without it
        except ImportError:
            raise SystemExit("yfinance is not installed. Run:  pip install -r requirements.txt")
        return yf

    def _download(self, tickers, **kw):
        yf = self._yf()
        out = {}
        for i in range(0, len(tickers), 60):
            chunk = tickers[i:i + 60]
            try:
                data = yf.download(chunk, group_by="ticker", auto_adjust=False,
                                   threads=True, progress=False, **kw)
            except Exception as e:
                self.log(f"WARN: Yahoo download failed for a batch ({e})")
                continue
            for t in chunk:
                try:
                    sub = data[t] if isinstance(data.columns, pd.MultiIndex) else data
                except KeyError:
                    continue
                sub = sub.rename(columns=lambda c: str(c).lower().replace(" ", "_"))
                cols = [c for c in ("open", "high", "low", "close", "volume") if c in sub]
                sub = sub[cols].dropna(subset=["close"])
                if not sub.empty:
                    out[t] = sub
        return out

    def daily(self, symbols):
        raw = self._download([s + ".NS" for s in symbols], period="1y", interval="1d")
        out = {}
        for s in symbols:
            df = raw.get(s + ".NS")
            if df is not None and len(df) >= 60:
                out[s] = _completed_daily(df)
        self.log(f"Yahoo daily history: {len(out)}/{len(symbols)} symbols")
        return out

    def index_daily(self):
        names = {"^NSEI": "NIFTY 50", "^NSEBANK": "BANK NIFTY", "^INDIAVIX": "INDIA VIX"}
        raw = self._download(list(names), period="1y", interval="1d")
        return {names[t]: _completed_daily(df) for t, df in raw.items()}

    def global_cues(self):
        names = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^N225": "Nikkei",
                 "^HSI": "Hang Seng", "USDINR=X": "USD/INR", "BZ=F": "Brent crude",
                 "GC=F": "Gold"}
        raw = self._download(list(names), period="10d", interval="1d")
        cues = []
        for t, label in names.items():
            df = raw.get(t)
            if df is None or len(df) < 2:
                continue
            last, prev = df["close"].iloc[-1], df["close"].iloc[-2]
            cues.append({"name": label, "last": float(last),
                         "chg_pct": float((last / prev - 1) * 100)})
        return cues

    def intraday(self, symbols):
        raw = self._download([s + ".NS" for s in symbols] + ["^NSEI"],
                             period="1d", interval="5m", prepost=False)
        out = {}
        for t, df in raw.items():
            idx = df.index
            if idx.tz is None:
                idx = idx.tz_localize("UTC")
            df.index = idx.tz_convert("Asia/Kolkata")
            df = df[df.index.date == now_ist().date()]
            if not df.empty:
                out["NIFTY 50" if t == "^NSEI" else t[:-3]] = df
        return out

    # ---------------- NSE flows, events, pre-open ----------------
    def fii_dii(self):
        try:
            rows = self.nse.api("/api/fiidiiTradeReact")
            out = []
            for r in rows:
                out.append({"category": r.get("category", "").replace("*", "").strip(),
                            "date": r.get("date", ""),
                            "net_cr": _num(r.get("netValue"))})
            return out
        except Exception as e:
            self.log(f"WARN: FII/DII failed ({e})")
            return []

    def events(self):
        try:
            rows = self.nse.api("/api/event-calendar")
            df = pd.DataFrame(rows)
            if df.empty:
                return df
            df = df.rename(columns={"symbol": "symbol", "purpose": "purpose", "date": "date"})
            df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce").dt.date
            keep = df["purpose"].astype(str).str.contains("result", case=False)
            return df.loc[keep, ["symbol", "date", "purpose"]].dropna()
        except Exception as e:
            self.log(f"WARN: event calendar failed ({e})")
            return pd.DataFrame(columns=["symbol", "date", "purpose"])

    def preopen(self):
        """Pre-open session (9:00-9:08) indicative prices for F&O stocks."""
        try:
            js = self.nse.api("/api/market-data-pre-open", {"key": "FO"})
            rows = []
            for item in js.get("data", []):
                m = item.get("metadata", {})
                rows.append({"symbol": m.get("symbol"),
                             "iep": _num(m.get("iep") or m.get("lastPrice")),
                             "gap_pct": _num(m.get("pChange"))})
            df = pd.DataFrame(rows).dropna(subset=["symbol"]).set_index("symbol")
            return df
        except Exception as e:
            self.log(f"WARN: pre-open data failed ({e})")
            return pd.DataFrame(columns=["iep", "gap_pct"])


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return np.nan


def _completed_daily(df):
    """Drop today's still-forming bar when running during market hours."""
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    n = now_ist()
    if len(df) and df.index[-1].date() == n.date() and n.time() < dt.time(15, 35):
        df = df.iloc[:-1]
    return df
