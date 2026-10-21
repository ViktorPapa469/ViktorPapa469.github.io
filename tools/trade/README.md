# NSE Intraday & Short-Swing Screener

**Phone app:** https://viktorpapa469.github.io/trade/ (open it on your phone and use
"Add to home screen"). GitHub runs this screener on weekdays via
`.github/workflows/trade.yml` + `ci.sh` and publishes the app's data to the
`trade-data` branch; you don't need a computer switched on. Capital and risk are
set in the app and stay on the phone. To run it by hand, open the repository's
Actions tab, pick "Opening Bell screener" and "Run workflow".

**Notifications:** turn them on in the app (Settings > Notifications). The phone saves its
push address in Firestore `trade_alerts/{id}`; `push.py` sends from GitHub with the
`VAPID_PRIVATE` secret Fovea already uses: screen ready (~9:12), each breakout (9:30–11:00),
square-off (3:15) and the evening preview. One-time setup: publish
`tools/firebase/firestore.rules` in the Firebase console (Firestore Database > Rules).

Everything below is for running it on your own computer instead.

Automates the morning routine: pulls same-day data from NSE and Yahoo Finance,
ranks F&O stocks, and writes a phone-friendly report. A second mode checks
opening-range breakouts live after 9:30.

## 1. Setup (once)

1. Install Python 3.10+ from python.org (on Windows tick **"Add Python to PATH"**).
2. Unzip this folder somewhere, e.g. `C:\nse-screener`.
3. Open a terminal in that folder and run:
   ```
   pip install -r requirements.txt
   ```
4. Open `config.py` and set your **CAPITAL** and **RISK_PCT**.
5. Try it with fake data first: `python run.py premarket --demo`

## 2. Daily timeline (IST)

| Time  | Command                      | What happens |
|-------|------------------------------|--------------|
| 9:10  | `python run.py premarket`    | Morning watchlist: regime, sectors, longs/shorts, swing setups, results calendar |
| 9:31  | `python run.py orb --watch`  | Rechecks the watchlist every 5 min until 11:00 and flags breakouts |

Running at 9:10 lets it include the 9:00–9:08 pre-open gaps. You can run it any
time from ~7 pm the previous evening; it will just skip pre-open data.

Reports open in your browser and are saved in `reports/` as HTML + CSV.

## 3. What's in the morning report

- **Market regime** – Nifty vs its 20/50 EMA → Uptrend / Downtrend / Range.
  India VIX above 20 halves suggested size. Plus pre-open breadth, FII/DII net
  flows, and overnight global cues.
- **Sector strength** – median 20-day return of each sector's F&O stocks vs Nifty.
- **Intraday longs/shorts** – liquid F&O stocks (turnover ≥ ₹50 cr, ATR ≥ 1.2%)
  scored on relative strength (20d + 5d), relative volume, close location,
  futures OI buildup, sector strength and pre-open gap. Counter-trend picks
  are capped and flagged.
- **Swing pullbacks** – uptrending leaders dipping to the 20 EMA on light volume.
  Trigger = above yesterday's high.
- **Swing tight bases** – narrow 10-day ranges within 6% of 52-week highs with
  volume drying up. Trigger = above the 10-day high.
- **Results calendar** – F&O names reporting in the next few days (also flagged
  on each card).

Every card shows levels and a **position size** from your risk settings.

## 4. The live opening-range scan

For each watchlist stock it computes the 15-minute opening range and VWAP, then
marks it **TRIGGERED** (broke the range, holding beyond VWAP, stronger/weaker than
Nifty), **WAITING**, or **FAILED**. Triggered names get entry, stop (tighter of
range edge and VWAP), 1.5R/3R targets and quantity. It warns you when price is
already more than 1R past entry so you don't chase.

## 5. Run it automatically

**Windows** (Command Prompt, adjust the path):
```
schtasks /create /tn "NSE premarket" /tr "C:\nse-screener\run_premarket.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 09:10
schtasks /create /tn "NSE ORB" /tr "C:\nse-screener\run_orb.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 09:31
```

**Mac / Linux** (`crontab -e`, computer clock on IST):
```
10 9 * * 1-5  /path/to/nse-screener/run_premarket.sh
31 9 * * 1-5  /path/to/nse-screener/run_orb.sh
```

On market holidays it simply reports that no fresh data is available.

## 6. Get it on your phone (optional)

Fill `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `config.py`. You'll then get
the morning summary + full HTML report, and a ping for each breakout trigger.

1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": ...}`.

## 7. Data sources and limits

| Data | Source |
|------|--------|
| F&O stock list, futures OI & OI change, lot sizes | NSE F&O bhavcopy (previous session) |
| Industries | NSE Nifty 500 constituent list |
| FII/DII flows, results calendar, pre-open prices | NSE website APIs |
| Daily & 5-minute prices, Nifty, Bank Nifty, VIX, global markets | Yahoo Finance |

- NSE's website sometimes blocks automated requests or changes formats. Each
  source fails independently and the report notes what's missing.
- Yahoo's NSE prices can lag by a few minutes. Treat the live scan as an alert
  and confirm on your broker's chart before entering. For true real-time data,
  `screener/data_live.py → intraday()` is the one function to swap for your
  broker's API (Zerodha Kite, Upstox, Dhan, etc.).
- GIFT Nifty isn't freely available via API; pre-open breadth and Asian markets
  stand in for it.

## 8. Tuning

All thresholds live in `config.py`. Scoring and setup rules are in
`screener/analysis.py` and are short and commented if you want to change them.
Paper-trade the signals for a few weeks and keep a journal of which setups
actually work for you before committing money.

*This is a screening tool, not investment advice.*
