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
DAILY_LOSS_LIMIT_R = 3     # shown in the report as your stop-trading line

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
