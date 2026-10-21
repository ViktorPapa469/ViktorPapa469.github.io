"""Indicators, market regime, sector strength and the four setups."""
import math

import numpy as np
import pandas as pd

import config as C


# ------------------------------------------------------------------ indicators
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def pct(a, b):
    return (a / b - 1) * 100 if b else np.nan


def pct_rank(s):
    return s.rank(pct=True).fillna(0.5)


# ------------------------------------------------------------------ per-stock features
def stock_features(df, nifty):
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    nf = nifty.reindex(df.index).ffill()
    e20, e50, a = ema(c, 20), ema(c, 50), atr(df)
    last, n = c.iloc[-1], len(df)

    def ret(series, k):
        return pct(series.iloc[-1], series.iloc[-1 - k]) if len(series) > k else np.nan

    rng_today = h.iloc[-1] - l.iloc[-1]
    vol20 = v.iloc[-21:-1].mean()
    return {
        "price": last,
        "chg1": ret(c, 1),
        "ret5": ret(c, 5), "ret20": ret(c, 20), "ret63": ret(c, 63),
        "rs5": ret(c, 5) - ret(nf, 5),
        "rs20": ret(c, 20) - ret(nf, 20),
        "rs63": ret(c, 63) - ret(nf, 63),
        "ema20": e20.iloc[-1], "ema50": e50.iloc[-1],
        "ema20_slope": pct(e20.iloc[-1], e20.iloc[-6]),
        "atr": a.iloc[-1], "atr_pct": a.iloc[-1] / last * 100,
        "rvol": v.iloc[-1] / vol20 if vol20 else np.nan,
        "turnover_cr": (c * v).iloc[-20:].mean() / 1e7,
        "dist_52wh": pct(last, h.iloc[-250:].max()),
        "tight10": (h.iloc[-10:].max() - l.iloc[-10:].min()) / a.iloc[-1],
        "dryup": v.iloc[-5:].mean() / v.iloc[-50:].mean(),
        "close_pos": (last - l.iloc[-1]) / rng_today if rng_today > 0 else 0.5,
        "pdh": h.iloc[-1], "pdl": l.iloc[-1],
        "high10": h.iloc[-10:].max(), "low5": l.iloc[-5:].min(),
        "off_high15": pct(last, h.iloc[-15:].max()),
        "touched_ema20": bool((l.iloc[-3:] <= (e20 + 0.5 * a).iloc[-3:]).any()),
        "pullback_vol": v.iloc[-4:-1].mean() / vol20 if vol20 else np.nan,
        "bars": n,
    }


def buildup(chg1, oi_chg_pct, threshold=3.0):
    if pd.isna(oi_chg_pct) or pd.isna(chg1) or abs(oi_chg_pct) < threshold:
        return ""
    if chg1 >= 0:
        return "Long buildup" if oi_chg_pct > 0 else "Short covering"
    return "Short buildup" if oi_chg_pct > 0 else "Long unwinding"


# ------------------------------------------------------------------ market regime
def market_regime(indices):
    nifty = indices.get("NIFTY 50")
    out = {"label": "Unknown", "bias": "No index data - trade small", "size_mult": 0.5}
    if nifty is None or len(nifty) < 60:
        return out
    c = nifty["close"]
    e20, e50 = ema(c, 20), ema(c, 50)
    last = c.iloc[-1]
    out.update(nifty=last, nifty_chg=pct(last, c.iloc[-2]), nifty_vs20=pct(last, e20.iloc[-1]),
               nifty_vs50=pct(last, e50.iloc[-1]), nifty_ret5=pct(last, c.iloc[-6]))
    if last > e20.iloc[-1] > e50.iloc[-1] and e20.iloc[-1] > e20.iloc[-6]:
        out.update(label="Uptrend", bias="Favour longs; shorts only in clearly weak stocks", size_mult=1.0)
    elif last < e20.iloc[-1] < e50.iloc[-1] and e20.iloc[-1] < e20.iloc[-6]:
        out.update(label="Downtrend", bias="Favour shorts; longs only in standout leaders", size_mult=1.0)
    else:
        out.update(label="Range / choppy", bias="Fewer trades; wait for clean opening-range breaks", size_mult=0.75)
    bank = indices.get("BANK NIFTY")
    if bank is not None and len(bank) > 6:
        out["bank"] = bank["close"].iloc[-1]
        out["bank_chg"] = pct(bank["close"].iloc[-1], bank["close"].iloc[-2])
    vix = indices.get("INDIA VIX")
    if vix is not None and len(vix) > 2:
        out["vix"] = vix["close"].iloc[-1]
        out["vix_chg"] = pct(vix["close"].iloc[-1], vix["close"].iloc[-2])
        if out["vix"] > C.HIGH_VIX:
            out["size_mult"] = min(out["size_mult"], 0.5)
            out["bias"] += f" - VIX above {C.HIGH_VIX}, halve size"
    return out


# ------------------------------------------------------------------ sectors
def sector_strength(feat):
    g = feat.groupby("industry").agg(n=("rs20", "size"), rs20=("rs20", "median"),
                                     rs5=("rs5", "median"), chg1=("chg1", "median"))
    g = g[(g["n"] >= 2) & (g.index != "Other")]
    g["score"] = 0.6 * g["rs20"] + 0.4 * g["rs5"]
    return g.sort_values("score", ascending=False)


# ------------------------------------------------------------------ sizing
def size(entry, stop, mult=1.0):
    risk_amt = C.CAPITAL * C.RISK_PCT / 100 * mult
    per_share = abs(entry - stop)
    if not per_share or math.isnan(per_share):
        return 0
    qty = int(risk_amt // per_share)
    cap = int(C.CAPITAL * C.MAX_POSITION_PCT / 100 // entry)
    return max(0, min(qty, cap))


# ------------------------------------------------------------------ main screen
def screen(daily, nifty_df, fo, industries, events, preopen, regime, today):
    nifty = nifty_df["close"]
    rows = []
    for sym, df in daily.items():
        f = stock_features(df, nifty)
        f["symbol"] = sym
        f["industry"] = industries.get(sym, "Other")
        rows.append(f)
    feat = pd.DataFrame(rows).set_index("symbol")
    feat = feat.join(fo[["oi_chg_pct", "lot"]], how="left")
    feat["buildup"] = [buildup(a, b) for a, b in zip(feat["chg1"], feat["oi_chg_pct"])]
    feat["gap_pct"] = preopen["gap_pct"].reindex(feat.index) if len(preopen) else np.nan

    # earnings flags
    feat["event"] = ""
    if len(events):
        for _, e in events.iterrows():
            if e["symbol"] in feat.index and pd.notna(e["date"]):
                days = (e["date"] - today).days
                if -2 <= days < 0:
                    feat.loc[e["symbol"], "event"] = "Results just out"
                elif days == 0:
                    feat.loc[e["symbol"], "event"] = "Results today"
                elif 0 < days <= 3:
                    feat.loc[e["symbol"], "event"] = f"Results in {days}d"

    sectors = sector_strength(feat)
    top = set(sectors.index[:3])
    bottom = set(sectors.index[-3:]) if len(sectors) >= 6 else set()
    mult = regime.get("size_mult", 1.0)

    liquid = feat[(feat["price"] >= C.MIN_PRICE) & (feat["turnover_cr"] >= C.MIN_TURNOVER_CR)
                  & (feat["atr_pct"] >= C.MIN_ATR_PCT) & (feat["bars"] >= 60)].copy()

    longs = _intraday_side(liquid, top, bottom, mult, side="long", regime=regime)
    shorts = _intraday_side(liquid, top, bottom, mult, side="short", regime=regime)
    pullbacks = _pullbacks(feat, top, mult)
    bases = _bases(feat.drop(index=[p["symbol"] for p in pullbacks]), top, mult)
    return {"features": feat, "sectors": sectors, "longs": longs, "shorts": shorts,
            "pullbacks": pullbacks, "bases": bases, "liquid_count": len(liquid)}


def _intraday_side(df, top, bottom, mult, side, regime):
    if df.empty:
        return []
    s = 1 if side == "long" else -1
    cand = df[(s * df["rs20"] > 0) & (s * (df["price"] - df["ema20"]) > 0)].copy()
    if cand.empty:
        return []
    want = {1: ("Long buildup", "Short covering", "Short buildup", "Long unwinding"),
            -1: ("Short buildup", "Long unwinding", "Long buildup", "Short covering")}[s]
    score = (30 * pct_rank(s * cand["rs20"]) + 20 * pct_rank(s * cand["rs5"])
             + 15 * cand["rvol"].clip(0, 3).fillna(1) / 3
             + 10 * (cand["close_pos"] if s == 1 else 1 - cand["close_pos"]))
    score += cand["buildup"].map({want[0]: 15, want[1]: 8, want[2]: -15, want[3]: -10}).fillna(0)
    good, bad = (top, bottom) if s == 1 else (bottom, top)
    score += cand["industry"].map(lambda x: 10 if x in good else (-5 if x in bad else 0))
    gap = cand["gap_pct"].fillna(0) * s
    score += np.where(gap > 3, -5, np.where(gap > 0.2, 3, np.where(gap < -1.5, -5, 0)))
    cand["score"] = score.clip(0, 100)
    against = (regime.get("label") == "Downtrend" and s == 1) or (regime.get("label") == "Uptrend" and s == -1)
    limit = C.MAX_INTRADAY_PICKS // 2 if against else C.MAX_INTRADAY_PICKS
    cand = cand.sort_values("score", ascending=False).head(limit)

    picks = []
    for sym, r in cand.iterrows():
        reasons = [f"RS {r.rs20:+.1f}% vs Nifty (20d)", f"5d RS {r.rs5:+.1f}%"]
        if r.rvol >= 1.5:
            reasons.append(f"Volume {r.rvol:.1f}x avg")
        if r.buildup:
            reasons.append(f"{r.buildup} (OI {r.oi_chg_pct:+.1f}%)")
        if r.industry in good:
            reasons.append(f"{'Strong' if s == 1 else 'Weak'} sector")
        if r.event:
            reasons.append(r.event)
        warn = []
        if pd.notna(r.gap_pct) and abs(r.gap_pct) >= 2:
            warn.append(f"Pre-open gap {r.gap_pct:+.1f}% - let the opening range form, don't chase")
        if against:
            warn.append("Counter-trend to the index - half size or skip")
        if r.event in ("Results today", "Results in 1d"):
            warn.append("Results event risk")
        stop_dist = 0.5 * r.atr
        picks.append({
            "symbol": sym, "industry": r.industry, "price": r.price, "chg1": r.chg1,
            "score": r.score, "reasons": reasons, "warnings": warn,
            "pdh": r.pdh, "pdl": r.pdl, "atr": r.atr, "lot": r.lot, "gap_pct": r.gap_pct,
            "est_stop_dist": stop_dist,
            "est_qty": size(r.price, r.price - s * stop_dist, mult * (0.5 if against else 1)),
            "side": side,
        })
    return picks


def _pullbacks(df, top, mult):
    """Uptrending leader dipping to its 20 EMA on lighter volume."""
    m = ((df["price"] >= C.MIN_PRICE) & (df["turnover_cr"] >= C.MIN_TURNOVER_CR)
         & (df["price"] > df["ema50"]) & (df["ema20"] > df["ema50"]) & (df["ema20_slope"] > 0)
         & (df["rs63"] > 0) & df["touched_ema20"] & (df["price"] >= df["ema20"] * 0.99)
         & df["off_high15"].between(-12, -1.5) & (df["pullback_vol"] < 1.0))
    cand = df[m].copy()
    if cand.empty:
        return []
    cand["score"] = (40 * pct_rank(cand["rs63"]) + 20 * (1 - cand["pullback_vol"].clip(0, 1))
                     + 15 * cand["close_pos"] + cand["industry"].map(lambda x: 15 if x in top else 0)
                     + 10 * pct_rank(cand["ema20_slope"])).clip(0, 100)
    out = []
    for sym, r in cand.sort_values("score", ascending=False).head(C.MAX_SWING_PICKS).iterrows():
        entry = r.pdh * 1.001
        stop = min(r.low5, r.ema20 - 0.5 * r.atr)
        out.append(_swing_row(sym, r, entry, stop, mult, "Pullback to 20 EMA",
                              [f"3-month RS {r.rs63:+.1f}%", f"{r.off_high15:.1f}% off 15-day high",
                               f"Pullback volume {r.pullback_vol:.2f}x avg"]))
    return out


def _bases(df, top, mult):
    """Tight sideways range near 52-week highs with volume drying up."""
    m = ((df["price"] >= C.MIN_PRICE) & (df["turnover_cr"] >= C.MIN_TURNOVER_CR)
         & (df["dist_52wh"] >= -6) & (df["tight10"] <= 3.5) & (df["dryup"] < 0.9)
         & (df["price"] > df["ema20"]) & (df["ema20"] > df["ema50"]))
    cand = df[m].copy()
    if cand.empty:
        return []
    cand["score"] = (35 * (1 - cand["tight10"] / 3.5) + 25 * (1 - cand["dryup"].clip(0, 1))
                     + 25 * pct_rank(cand["rs63"])
                     + cand["industry"].map(lambda x: 15 if x in top else 0)).clip(0, 100)
    out = []
    for sym, r in cand.sort_values("score", ascending=False).head(C.MAX_SWING_PICKS).iterrows():
        entry = r.high10 * 1.001
        stop = max(r.low5, entry - 1.5 * r.atr)
        out.append(_swing_row(sym, r, entry, stop, mult, "Tight base near highs",
                              [f"{r.dist_52wh:.1f}% from 52-week high",
                               f"10-day range {r.tight10:.1f}x ATR", f"Volume {r.dryup:.2f}x of 50-day avg"]))
    return out


def _swing_row(sym, r, entry, stop, mult, setup, reasons):
    risk = entry - stop
    if r.event:
        reasons.append(r.event)
    return {"symbol": sym, "industry": r.industry, "price": r.price, "chg1": r.chg1,
            "score": r.score, "setup": setup, "reasons": reasons,
            "entry": entry, "stop": stop, "t1": entry + 2 * risk, "t2": entry + 3 * risk,
            "risk_pct": risk / entry * 100, "qty": size(entry, stop, mult), "lot": r.lot,
            "warnings": ["Results inside the holding window"] if r.event.startswith("Results") else []}
