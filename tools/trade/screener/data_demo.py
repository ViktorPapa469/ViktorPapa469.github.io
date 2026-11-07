"""Synthetic data so you can see the full report offline: python run.py premarket --demo
Prices are random, not real quotes."""
import datetime as dt

import numpy as np
import pandas as pd

from .data_live import now_ist

SECTORS = {
    "Automobile and Auto Components": ["MARUTI", "M&M", "TVSMOTOR", "EICHERMOT", "BAJAJ-AUTO", "HEROMOTOCO"],
    "Financial Services": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "BAJFINANCE", "CHOLAFIN"],
    "Information Technology": ["INFY", "TCS", "HCLTECH", "WIPRO", "TECHM", "PERSISTENT", "COFORGE"],
    "Metals & Mining": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "SAIL", "NMDC"],
    "Healthcare": ["SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN", "AUROPHARMA", "DIVISLAB"],
    "Fast Moving Consumer Goods": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR"],
    "Capital Goods": ["LT", "BEL", "HAL", "SIEMENS", "ABB", "POLYCAB"],
    "Oil Gas & Consumable Fuels": ["RELIANCE", "ONGC", "BPCL", "IOC", "GAIL"],
}
SECTOR_DRIFT = {  # daily drift per sector so some sectors lead and some lag
    "Automobile and Auto Components": 0.0016, "Capital Goods": 0.0013,
    "Financial Services": 0.0006, "Healthcare": 0.0004,
    "Fast Moving Consumer Goods": -0.0002, "Oil Gas & Consumable Fuels": 0.0,
    "Metals & Mining": -0.0010, "Information Technology": -0.0014,
}


class DemoData:
    def __init__(self, log, seed=7):
        self.log = log
        self.rng = np.random.default_rng(seed)
        self.sym_sector = {s: sec for sec, syms in SECTORS.items() for s in syms}
        self.dates = pd.bdate_range(end=now_ist().date() - dt.timedelta(days=1), periods=500)
        self._daily = {s: self._make_stock(s) for s in self.sym_sector}

    def _make_stock(self, sym):
        r = self.rng
        n = len(self.dates)
        drift = SECTOR_DRIFT[self.sym_sector[sym]] + r.normal(0, 0.0008)
        vol = r.uniform(0.012, 0.024)
        rets = r.normal(drift, vol, n)
        style = r.choice(["pullback", "base", "plain", "plain"])
        if style == "pullback" and drift > 0:  # rally then 4-bar dip on light volume
            rets[-20:-5] = np.abs(rets[-20:-5]) * 0.9
            rets[-7:-1] = -np.abs(r.normal(0.011, 0.003, 6))
            rets[-1] = abs(r.normal(0.006, 0.002))
        elif style == "base" and drift > 0:  # tight 10-day range near highs
            rets[-30:-12] = np.abs(rets[-30:-12])
            rets[-12:] = r.normal(0, vol * 0.25, 12)
        close = r.uniform(300, 4000) * np.exp(np.cumsum(rets))
        open_ = close * (1 + r.normal(0, vol / 3, n))
        high = np.maximum(open_, close) * (1 + np.abs(r.normal(0, vol / 2, n)))
        low = np.minimum(open_, close) * (1 - np.abs(r.normal(0, vol / 2, n)))
        base_vol = r.uniform(8e5, 6e6) * 1000 / close.mean()
        volume = base_vol * np.exp(r.normal(0, 0.35, n)) * (1 + 8 * np.abs(rets))
        if style in ("pullback", "base"):
            volume[-5:] *= 0.6
        if r.random() < 0.25:
            volume[-1] *= r.uniform(1.8, 3.0)
        return pd.DataFrame({"open": open_, "high": high, "low": low,
                             "close": close, "volume": volume.round()}, index=self.dates)

    def fo_snapshot(self):
        syms = list(self.sym_sector)
        chg1 = {s: self._daily[s]["close"].pct_change().iloc[-1] for s in syms}
        oi_chg_pct = [np.sign(chg1[s]) * self.rng.uniform(-4, 12) for s in syms]
        df = pd.DataFrame({"oi": self.rng.uniform(5e6, 6e7, len(syms)),
                           "oi_chg_pct": oi_chg_pct,
                           "lot": self.rng.choice([75, 125, 250, 400, 550, 1100, 1500], len(syms))},
                          index=pd.Index(syms, name="symbol"))
        df["oi_chg"] = df["oi"] * df["oi_chg_pct"] / 100
        return df, self.dates[-1].date()

    def industries(self):
        return dict(self.sym_sector)

    def daily(self, symbols):
        return {s: self._daily[s] for s in symbols if s in self._daily}

    def index_daily(self):
        closes = pd.concat([d["close"] / d["close"].iloc[0] for d in self._daily.values()], axis=1).mean(axis=1)
        nifty = closes * 25000
        df = pd.DataFrame({"open": nifty.shift(1).fillna(nifty), "high": nifty * 1.004,
                           "low": nifty * 0.996, "close": nifty, "volume": 0})
        bank = df * 2.25
        vix = pd.DataFrame({"close": 13 + self.rng.normal(0, 1, len(df)).cumsum() * 0.2}, index=df.index)
        for c in ("open", "high", "low"):
            vix[c] = vix["close"]
        vix["volume"] = 0
        return {"NIFTY 50": df, "BANK NIFTY": bank, "INDIA VIX": vix}

    def global_cues(self):
        items = [("S&P 500", 6650), ("Nasdaq", 22400), ("Nikkei", 47800), ("Hang Seng", 25900),
                 ("USD/INR", 88.4), ("Brent crude", 64.2), ("Gold", 4100)]
        return [{"name": n, "last": v, "chg_pct": float(self.rng.normal(0, 0.7))} for n, v in items]

    def fii_dii(self):
        d = now_ist().date() - dt.timedelta(days=1)
        return [{"category": "FII/FPI", "date": f"{d:%d-%b-%Y}", "net_cr": -1834.6},
                {"category": "DII", "date": f"{d:%d-%b-%Y}", "net_cr": 2611.2}]

    def events(self):
        today = now_ist().date()
        rows = [("HDFCBANK", today, "Financial Results"), ("INFY", today - dt.timedelta(days=1), "Financial Results"),
                ("MARUTI", today + dt.timedelta(days=1), "Financial Results"),
                ("BEL", today + dt.timedelta(days=2), "Financial Results/Dividend")]
        return pd.DataFrame(rows, columns=["symbol", "date", "purpose"])

    def preopen(self):
        syms = list(self.sym_sector)
        return pd.DataFrame({"gap_pct": self.rng.normal(0.2, 0.8, len(syms))},
                            index=pd.Index(syms, name="symbol"))

    def intraday(self, symbols):
        """5-minute bars from 9:15 to 10:30 today, some of them breaking out."""
        start = pd.Timestamp.combine(now_ist().date(), dt.time(9, 15)).tz_localize("Asia/Kolkata")
        idx = pd.date_range(start, periods=16, freq="5min")
        out = {}
        for s in list(symbols) + ["NIFTY 50"]:
            base = 25000 if s == "NIFTY 50" else float(self._daily[s]["close"].iloc[-1])
            drift = self.rng.choice([0.0012, -0.0012, 0.0]) if s != "NIFTY 50" else 0.0003
            rets = self.rng.normal(0, 0.0018, len(idx))
            rets[3:] += drift
            close = base * np.exp(np.cumsum(rets))
            open_ = np.r_[base, close[:-1]]
            high = np.maximum(open_, close) * (1 + np.abs(self.rng.normal(0, 0.0008, len(idx))))
            low = np.minimum(open_, close) * (1 - np.abs(self.rng.normal(0, 0.0008, len(idx))))
            vol = self.rng.uniform(2e4, 9e4, len(idx)) * (1 + 40 * np.abs(rets))
            out[s] = pd.DataFrame({"open": open_, "high": high, "low": low,
                                   "close": close, "volume": vol}, index=idx)
        return out
