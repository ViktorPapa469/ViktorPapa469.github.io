"""Indicators, market regime, sector strength and the four setups."""
import math

import numpy as np
import pandas as pd

import config as C


# swing setup rules (shared by the screen and by the app's "Analyse" checklist)
PB_OFF_HIGH = (-12, -1.5)   # % below the 15-day high
PB_VOL = 1.0                # pullback volume vs 20-day average, below
PB_EMA_TOL = 0.99           # price at least this fraction of the 20 EMA
BASE_DIST = -6              # % from the 52-week high, at least
BASE_TIGHT = 3.5            # 10-day range in ATRs, at most
BASE_DRYUP = 0.9            # 5-day volume vs 50-day, below


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
            "pullbacks": pullbacks, "bases": bases, "liquid_count": len(liquid), "top": top, "bottom": bottom}


# ------------------------------------------------------------------ "Analyse" checklist for the app
def rule_checks(r, top, bottom, fno=True):
    """Each screener rule for one stock: [label, passed (True/False/None), its value, what the rule needs, factor?].
    Factors only change the ranking score; they are not required. None means the data isn't available for this stock
    (open interest outside F&O, a sector outside the Nifty 500 list); such checks are left out of the score."""
    def ok(x, *deps):
        """True/False for a rule; None when any value it depends on is missing (too little history, no volume...)."""
        if any(d is None or (isinstance(d, float) and np.isnan(d)) for d in deps):
            return None
        return None if x is None or (isinstance(x, float) and np.isnan(x)) else bool(x)

    def num(x, fmt):
        return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else format(x, fmt)

    rs_ = lambda x: "₹" + num(x, ",.2f")
    liq = [
        ["Price", ok(r.price >= C.MIN_PRICE, r.price), rs_(r.price), f"₹{C.MIN_PRICE} or more", 0],
        ["Average daily turnover, 20 days", ok(r.turnover_cr >= C.MIN_TURNOVER_CR, r.turnover_cr), "₹" + num(r.turnover_cr, ",.0f") + " cr", f"₹{C.MIN_TURNOVER_CR} cr or more", 0],
        ["Daily range (ATR)", ok(r.atr_pct >= C.MIN_ATR_PCT, r.atr_pct), num(r.atr_pct, ".2f") + "%", f"{C.MIN_ATR_PCT}% or more", 0],
        ["Price history", ok(r.bars >= 60), f"{int(r.bars)} sessions", "60 or more", 0],
    ]

    def side(s):
        good, bad = (top, bottom) if s == 1 else (bottom, top)
        want = ("Long buildup", "Short covering") if s == 1 else ("Short buildup", "Long unwinding")
        word = "Stronger" if s == 1 else "Weaker"
        items = [
            [f"{word} than Nifty over 20 days", ok(s * r.rs20 > 0, r.rs20), num(r.rs20, "+.1f") + "%", "above 0%" if s == 1 else "below 0%", 0],
            [("Above" if s == 1 else "Below") + " its 20-day average", ok(s * (r.price - r.ema20) > 0, r.price, r.ema20), rs_(r.price) + " vs " + rs_(r.ema20), "price " + ("above" if s == 1 else "below"), 0],
            [f"{word} than Nifty over 5 days", ok(s * r.rs5 > 0, r.rs5), num(r.rs5, "+.1f") + "%", "above 0%" if s == 1 else "below 0%", 1],
            ["Volume vs 20-day average", ok(r.rvol >= 1.5, r.rvol), num(r.rvol, ".1f") + "x", "1.5x or more", 1],
            ["Closed near the day's " + ("high" if s == 1 else "low"), ok((r.close_pos if s == 1 else 1 - r.close_pos) >= 0.6, r.close_pos), num(r.close_pos * 100, ".0f") + "% of the range", "upper part" if s == 1 else "lower part", 1],
            (["Futures open interest", ok(r.buildup in want) if r.buildup else False,
              (r.buildup or "no clear change") + ("" if pd.isna(r.oi_chg_pct) else f" (OI {r.oi_chg_pct:+.1f}%)"), " or ".join(want), 1]
             if fno else ["Futures open interest", None, "Not available: not an F&O stock", " or ".join(want), 1]),
            ([f"Sector is among the {'strongest' if s == 1 else 'weakest'}", ok(r.industry in good), r.industry, "top 3" if s == 1 else "bottom 3", 1]
             if r.industry and r.industry != "Other" else
             [f"Sector is among the {'strongest' if s == 1 else 'weakest'}", None, "Not available: sector not classified", "top 3" if s == 1 else "bottom 3", 1]),
        ]
        for it in items[:5]:
            if it[1] is None:
                it[2] = "Not available: not enough price data"
        return items
    pb = [
        ["Above its 50-day average", ok(r.price > r.ema50, r.ema50), rs_(r.price) + " vs " + rs_(r.ema50), "price above", 0],
        ["20-day average above the 50-day", ok(r.ema20 > r.ema50, r.ema20, r.ema50), rs_(r.ema20) + " vs " + rs_(r.ema50), "20-day above", 0],
        ["20-day average rising", ok(r.ema20_slope > 0, r.ema20_slope), num(r.ema20_slope, "+.2f") + "% in 5 days", "rising", 0],
        ["Stronger than Nifty over 3 months", ok(r.rs63 > 0, r.rs63), num(r.rs63, "+.1f") + "%", "above 0%", 0],
        ["Dipped to the 20-day average (last 3 days)", ok(r.touched_ema20), "yes" if r.touched_ema20 else "no", "yes", 0],
        ["Holding the 20-day average", ok(r.price >= r.ema20 * PB_EMA_TOL, r.ema20), rs_(r.price) + " vs " + rs_(r.ema20), f"within {round((1 - PB_EMA_TOL) * 100)}% or above", 0],
        ["Below the 15-day high", ok(PB_OFF_HIGH[0] <= r.off_high15 <= PB_OFF_HIGH[1], r.off_high15), num(r.off_high15, ".1f") + "%", f"{PB_OFF_HIGH[1]:g}% to {PB_OFF_HIGH[0]:g}%", 0],
        ["Light volume on the dip", ok(r.pullback_vol < PB_VOL, r.pullback_vol), num(r.pullback_vol, ".2f") + "x average", f"below {PB_VOL:g}x", 0],
    ]
    base = [
        ["Near the 52-week high", ok(r.dist_52wh >= BASE_DIST, r.dist_52wh), num(r.dist_52wh, ".1f") + "%", f"within {abs(BASE_DIST)}%", 0],
        ["Tight 10-day range", ok(r.tight10 <= BASE_TIGHT, r.tight10), num(r.tight10, ".1f") + " ATR", f"{BASE_TIGHT:g} ATR or less", 0],
        ["Volume drying up (5 days vs 50)", ok(r.dryup < BASE_DRYUP, r.dryup), num(r.dryup, ".2f") + "x", f"below {BASE_DRYUP:g}x", 0],
        ["Above its 20-day average", ok(r.price > r.ema20, r.ema20), rs_(r.price) + " vs " + rs_(r.ema20), "price above", 0],
        ["20-day average above the 50-day", ok(r.ema20 > r.ema50, r.ema20, r.ema50), rs_(r.ema20) + " vs " + rs_(r.ema50), "20-day above", 0],
    ]
    for it in liq + pb + base:
        if it[1] is None:
            it[2] = "Not available: not enough price data"
    liq_ok = all(x[1] for x in liq)
    swing_liq = liq[:2]

    def group(name, items, need_liq):
        req = [x for x in items if not x[4]] + (need_liq if need_liq else [])
        return {"name": name, "pass": all(x[1] is True for x in req), "items": items}
    return [
        {"name": "Liquidity filters (intraday)", "pass": bool(liq_ok), "items": liq},
        group("Intraday long setup", side(1), liq),
        group("Intraday short setup", side(-1), liq),
        group("Swing: pullback to the 20-day average", pb, swing_liq),
        group("Swing: tight base near highs", base, swing_liq),
    ]


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
         & (df["rs63"] > 0) & df["touched_ema20"] & (df["price"] >= df["ema20"] * PB_EMA_TOL)
         & df["off_high15"].between(*PB_OFF_HIGH) & (df["pullback_vol"] < PB_VOL))
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
         & (df["dist_52wh"] >= BASE_DIST) & (df["tight10"] <= BASE_TIGHT) & (df["dryup"] < BASE_DRYUP)
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
            "warnings": [results_warning(r.event)] if r.event.startswith("Results") else []}


def results_warning(event):
    """Plain words for a results date that falls inside a swing trade's usual 2 to 10 day hold."""
    when = {"Results today": "today", "Results just out": "just announced"}.get(event, event.replace("Results in ", "in ").replace("d", " days").replace("in 1 days", "in 1 day"))
    if event == "Results just out":
        return "Quarterly results just announced: expect bigger swings than usual for a few days."
    return (f"Quarterly results {when}, during the usual 2-10 day hold: the price can gap past the stop on the "
            "announcement. Consider skipping, a smaller position, or waiting for the reaction.")
