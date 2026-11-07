"""NSE intraday / short-swing screener.

  python run.py premarket          # morning watchlist (run ~9:10 IST)
  python run.py orb                # one opening-range check (after 9:30)
  python run.py orb --watch        # re-check every few minutes until WATCH_UNTIL
  add --demo to either to use synthetic data (no internet needed)
  add --json DIR to also write the phone app's data files into DIR
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import webbrowser

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402
from screener import analysis, export, notify, orb as orbmod, report  # noqa: E402
from screener.data_live import LiveData, now_ist  # noqa: E402


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # emoji-safe on Windows consoles
except AttributeError:
    pass


NOTES = []  # short names of data sources that failed, shown in the app
NOTE_LABELS = [("F&O bhavcopy", "F&O open interest"), ("lot-size file", "NSE's F&O list (built-in list used)"),
               ("industry list", "sector groups"), ("FII/DII", "FII/DII flows"), ("event calendar", "results calendar"),
               ("pre-open", "pre-open gaps"), ("Yahoo download", "some prices")]


def log(msg):
    print(f"[{now_ist():%H:%M:%S}] {msg}", flush=True)
    if msg.startswith("WARN: "):
        text = msg[6:]
        for start, label in NOTE_LABELS:
            if text.startswith(start):
                if label:
                    NOTES.append(label)
                break
        else:
            NOTES.append(text.split(" (")[0])


def stamp():
    return now_ist().isoformat(timespec="seconds")


def source(demo):
    if demo:
        from screener.data_demo import DemoData
        return DemoData(log)
    return LiveData(log)


def outdir():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), C.OUTPUT_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def tag(day, demo):
    return f"{day}_demo" if demo else f"{day}"


def watch_path(day, demo):
    return os.path.join(outdir(), f"watchlist_{tag(day, demo)}.json")


def session_date(demo):
    """The trading day a screen is for: after the 3:30 close it's a preview for the next weekday."""
    n = now_ist()
    d = n.date()
    if not demo and n.time() >= dt.time(15, 30):
        d += dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
    return d


# ------------------------------------------------------------------ company earnings (CANSLIM)
def company_earnings(demo, json_dir, symbols):
    """Cached quarterly / yearly earnings, ROE and institutional holding. Refreshed (weekly per stock) by the
    evening run or when the cache is empty; the morning screen just reads it."""
    if demo:
        rng = np.random.default_rng(3)
        return {s: {"eps_q": float(rng.normal(40, 25)), "eps_q_prev": float(rng.normal(25, 20)),
                    "eps_3y": float(rng.normal(30, 12)), "roe": float(rng.normal(21, 6)), "inst": float(rng.uniform(10, 60))}
                for s in symbols}
    if not json_dir:
        return {}
    from screener import fundamentals
    cache = fundamentals.load(json_dir)
    if now_ist().hour >= 15 or not cache:
        try:
            cache = fundamentals.refresh(json_dir, symbols, log, max_minutes=8)
        except Exception as e:  # noqa: BLE001
            log(f"WARN: company earnings unavailable ({str(e)[:100]})")
    return cache


# ------------------------------------------------------------------ premarket
def premarket(demo, open_browser=True, json_dir=None):
    src = source(demo)
    today = now_ist().date()
    log("Fetching F&O universe and open interest...")
    fo, oi_date = src.fo_snapshot()
    universe = list(fo.index)
    log(f"Fetching price history for {len(universe)} stocks...")
    daily = src.daily(universe)
    indices = src.index_daily()
    if "NIFTY 50" not in indices or not daily:
        log("ERROR: could not get Nifty or stock prices - check your internet connection and try again.")
        sys.exit(1)
    log("Fetching industries, flows, results calendar, pre-open and global cues...")
    industries = src.industries()
    fii = src.fii_dii()
    events = src.events()
    pre = src.preopen()
    if session_date(demo) > today:   # built after the close for the next session: today's pre-open says nothing about it
        pre = pre.iloc[0:0]
    cues = src.global_cues()

    regime = analysis.market_regime(indices)
    fund = company_earnings(demo, json_dir, list(daily))
    res = analysis.screen(daily, indices["NIFTY 50"], fo, industries, events, pre, regime, today, fund)

    breadth = None
    if len(pre) and pre["gap_pct"].notna().any():
        g = pre["gap_pct"].dropna()
        breadth = {"adv": int((g > 0).sum()), "dec": int((g < 0).sum()), "avg": float(g.mean())}

    ev = events[events["symbol"].isin(universe)] if len(events) else events
    if len(ev):
        ev = ev[(ev["date"] >= today - dt.timedelta(days=1)) & (ev["date"] <= today + dt.timedelta(days=5))].sort_values("date")

    as_of = indices["NIFTY 50"].index[-1].date()
    ctx = {"today": f"{today:%a %d %b %Y}", "as_of": f"{as_of:%d %b}", "generated": f"{now_ist():%H:%M}",
           "date": session_date(demo).isoformat(), "as_of_date": as_of.isoformat(),
           "oi_date_iso": oi_date.isoformat() if oi_date else None,
           "demo": demo, "regime": regime, "result": res, "fii_dii": fii, "cues": cues, "events": ev,
           "preopen_breadth": breadth, "universe": len(universe), "priced": len(daily),
           "oi_date": f"{oi_date:%d %b}" if oi_date else None}

    out = outdir()
    html_path = os.path.join(out, f"watchlist_{tag(today, demo)}.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(report.premarket(ctx))

    # CSV of every pick + JSON watchlist for the ORB step
    rows = []
    for key in ("longs", "shorts", "pullbacks", "bases", "canslim", "minervini"):
        for p in res[key]:
            rows.append({"list": key, **{k: v for k, v in p.items() if k not in ("reasons", "warnings")},
                         "reasons": "; ".join(p["reasons"]), "warnings": "; ".join(p["warnings"])})
    pd.DataFrame(rows).to_csv(os.path.join(out, f"watchlist_{tag(today, demo)}.csv"), index=False)
    watch = [{"symbol": p["symbol"], "side": p["side"], "atr": float(p["atr"]), "industry": p["industry"],
              "lot": None if pd.isna(p["lot"]) else float(p["lot"])} for p in res["longs"] + res["shorts"]]
    with open(watch_path(today, demo), "w") as fh:
        json.dump({"size_mult": regime.get("size_mult", 1.0), "watch": watch}, fh, indent=1)

    if json_dir:
        export.write(json_dir, "premarket", export.premarket_payload(ctx, list(dict.fromkeys(NOTES)), stamp()))
        export.write_daily_prices(json_dir, daily, stamp())   # for paper-trade results in the app
        export.write_analysis(json_dir, ctx, res, stamp())     # for the app's Analyse button
        log(f"App data written to {json_dir}")

    summary = (f"<b>Watchlist {today:%d %b}</b> - {regime['label']}\n{regime['bias']}\n"
               f"Longs: {', '.join(p['symbol'] for p in res['longs']) or '-'}\n"
               f"Shorts: {', '.join(p['symbol'] for p in res['shorts']) or '-'}\n"
               f"Pullbacks: {', '.join(p['symbol'] for p in res['pullbacks']) or '-'}\n"
               f"Bases: {', '.join(p['symbol'] for p in res['bases']) or '-'}")
    print("\n" + summary.replace("<b>", "").replace("</b>", "") + "\n")
    notify.send_text(summary, log)
    notify.send_file(html_path, "Full report", log)
    log(f"Report saved: {html_path}")
    if open_browser:
        webbrowser.open("file://" + os.path.abspath(html_path))
    return html_path


# ------------------------------------------------------------------ live ORB
def run_orb(demo, watch_mode, open_browser=True, json_dir=None):
    today = now_ist().date()
    wp = watch_path(today, demo)
    if not os.path.exists(wp):
        log("No watchlist for today yet - running the premarket screen first.")
        premarket(demo, open_browser=False, json_dir=json_dir)
    with open(wp) as fh:
        wl = json.load(fh)
    if not wl["watch"]:
        log("Watchlist is empty today - nothing to scan.")
        return 0
    src = source(demo)
    alerted_path = os.path.join(outdir(), f"alerted_{tag(today, demo)}.json")
    try:  # remember alerts across separate runs so Telegram isn't spammed
        with open(alerted_path) as fh:
            alerted = set(json.load(fh))
    except (OSError, ValueError):
        alerted = set()
    first = True
    while True:
        NOTES.clear()
        bars = src.intraday([w["symbol"] for w in wl["watch"]])
        if not bars:
            msg = "No intraday data yet (market not open, holiday, or Yahoo delay)."
            log(msg)
            if json_dir:
                export.write(json_dir, "orb", export.empty_orb(today.isoformat(), wl.get("size_mult", 1.0),
                                                                msg, stamp(), demo))
        else:
            res = orbmod.evaluate(wl["watch"], bars, wl.get("size_mult", 1.0))
            ctx = {"today": f"{today:%a %d %b %Y}", "generated": f"{now_ist():%H:%M}", "demo": demo, "orb": res}
            path = os.path.join(outdir(), f"orb_{tag(today, demo)}.html")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(report.orb(ctx))
            pd.DataFrame(res["rows"]).to_csv(os.path.join(outdir(), f"orb_{tag(today, demo)}.csv"), index=False)
            for r in res["rows"]:
                key = f"{r['symbol']}-{r['status']}"
                if r["status"] == "TRIGGERED" and key not in alerted:
                    alerted.add(key)
                    msg = (f"{'🟢 LONG' if r['side'] == 'long' else '🔴 SHORT'} {r['symbol']} triggered {r['trigger_time']}\n"
                           f"Entry {r['entry']:.2f}  Stop {r['stop']:.2f}  T1 {r['t1']:.2f}  Qty {r['qty']}")
                    log(msg.replace("\n", " | "))
                    notify.send_text(msg, log)
            with open(alerted_path, "w") as fh:
                json.dump(sorted(alerted), fh)
            if json_dir:
                export.write(json_dir, "orb", export.orb_payload(today.isoformat(), res, wl.get("size_mult", 1.0),
                                                                 list(dict.fromkeys(NOTES)), stamp(), demo))
            log(f"Scan updated: {path}")
            if first and open_browser:
                webbrowser.open("file://" + os.path.abspath(path))
            first = False
        if not watch_mode or demo:
            return 0 if bars else 3  # 3 = no intraday data (lets the scheduler stop early on holidays)
        hh, mm = map(int, C.WATCH_UNTIL.split(":"))
        if now_ist().time() >= dt.time(hh, mm):
            log("Watch window over.")
            return 0
        time.sleep(C.WATCH_INTERVAL_MIN * 60)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["premarket", "orb"])
    ap.add_argument("--demo", action="store_true", help="use synthetic data")
    ap.add_argument("--watch", action="store_true", help="orb: keep re-checking until WATCH_UNTIL")
    ap.add_argument("--no-browser", action="store_true", help="don't open the report automatically")
    ap.add_argument("--json", metavar="DIR", help="also write the phone app's JSON data into DIR")
    a = ap.parse_args()
    np.seterr(all="ignore")
    if a.mode == "premarket":
        premarket(a.demo, not a.no_browser, a.json)
    else:
        sys.exit(run_orb(a.demo, a.watch, not a.no_browser, a.json) or 0)


if __name__ == "__main__":
    main()
