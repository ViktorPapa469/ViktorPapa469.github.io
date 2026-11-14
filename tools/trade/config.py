# ---------------------------------------------------------------
#  Settings for the NSE morning screener. Edit freely.
#  (In the phone app, capital and risk are set on the Settings tab instead;
#   the values here only affect the HTML reports.)
# ---------------------------------------------------------------
import os

# --- Money & risk -------------------------------------------------
CAPITAL = 500_000          # trading capital in rupees
RISK_PCT = 0.5             # % of capital risked per trade (0.5 = 0.5%)
MAX_POSITION_PCT = 100     # cap a single position's value at this % of capital
DAILY_LOSS_LIMIT_R = 3     # once the day's closed setups have lost this many R, the live scan takes no more breakouts
MAX_OPEN_POSITIONS = 3     # breakouts still running at the same time; further ones are skipped until one closes
ONE_PER_SECTOR = True      # never two open breakouts in the same sector (they tend to win or lose together)

# --- Universe filters ---------------------------------------------
MIN_PRICE = 100            # skip stocks below this price (rupees)
MIN_TURNOVER_CR = 50       # min 20-day average daily turnover, in crores
MIN_ATR_PCT = 1.2          # min daily ATR as % of price (enough movement to trade)

# --- How many names to show -----------------------------------------
MAX_INTRADAY_PICKS = 8     # per side (longs / shorts)
MAX_SWING_PICKS = 8        # per swing setup

# --- Live opening-range mode ----------------------------------------
ORB_MINUTES = 15           # opening range length after 9:15
WATCH_INTERVAL_MIN = 5     # how often `orb --watch` refreshes
WATCH_UNTIL = "11:00"      # stop watching for breakouts after this time (IST)
ORB_MIN_RVOL = 1.5         # the opening range's volume vs the stock's own average for those minutes: at least this
ORB_RVOL_DAYS = 10         # sessions in that average
ORB_MAX_CHASE_R = 0.5      # skip a breakout when price is already this many R past the level when the scan sees it

# --- Track record (track.py) -------------------------------------------
# Taken off every result: brokerage, STT, exchange and SEBI fees, stamp duty, GST, plus a little slippage on the exit,
# for a round trip, as a % of the trade's value. Intraday statutory charges alone come to about 0.04%; a flat-fee
# broker adds little on large trades and up to 0.07% on small ones. Delivery (swing) pays 0.1% STT on each side.
COST_INTRADAY_PCT = 0.10
COST_SWING_PCT = 0.30

# --- Market regime ---------------------------------------------------
HIGH_VIX = 20              # India VIX above this -> report suggests half size

# --- Output ------------------------------------------------------------
OUTPUT_DIR = "reports"

# --- Optional: Telegram alerts ------------------------------------------
# Create a bot with @BotFather, paste its token, then send the bot a message
# and get your chat id from https://api.telegram.org/bot<TOKEN>/getUpdates
# On GitHub these come from the repository secrets of the same names.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
