#!/usr/bin/env bash
# Runs the screener on GitHub and publishes the phone app's data (see .github/workflows/trade.yml).
# Clock times below are IST: the workflow sets TZ=Asia/Kolkata.
#   MODE=auto       before 3:30 PM -> morning, after -> preview for the next session
#   MODE=morning    live prices every minute from 9:00, the screen ~9:10, breakout scans every 5 min 9:31-11:00, until 1:30 PM
#   MODE=afternoon  live prices every minute from 1:30 PM to the close, with the 3:15 square-off reminder
#   MODE=live       live prices every minute from now until the close (manual start)
#   MODE=premarket  just the screen
#   MODE=orb        one breakout scan
#   MODE=squareoff  the 3:15 reminder (only on days the market traded)
#   MODE=market     just the all-market analysis (every NSE and BSE stock, for the app's Analyse button)
# NOTIFY=0 turns push notifications off (used when the workflow runs because the code changed).
set -u
cd "$(dirname "$0")"
PUB="${PUB:-$GITHUB_WORKSPACE/pub}"
MODE="${MODE:-auto}"
NOTIFY="${NOTIFY:-1}"

hhmm() { echo $((10#$(date +%H%M))); }
wait_until() { while [ "$(hhmm)" -lt "$((10#$1))" ]; do sleep 20; done; }

# The trade-data branch always holds a single commit with the contents of pub/. A git folder kept outside pub/ for the
# whole run remembers what GitHub already has, so publishing every minute only uploads the files that changed.
URL="${PUSH_URL:-https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git}"
GD="${RUNNER_TEMP:-/tmp}/pubgit"
g() { git --git-dir="$GD" --work-tree="$PUB" -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" "$@"; }
publish() {
  if [ ! -d "$GD" ]; then git init -q --bare "$GD" && g config core.bare false && { g fetch -q --depth 1 "$URL" trade-data:refs/remotes/origin/trade-data 2>/dev/null || true; }; fi
  rm -rf "$PUB/.git"
  ( cd "$PUB" && g add -A && tree=$(g write-tree) && c=$(echo "$1" | g commit-tree "$tree") &&
    g push -qf "$URL" "$c:refs/heads/trade-data" && g update-ref refs/remotes/origin/trade-data "$c" ) \
    && echo "published: $1" || echo "::warning::publish failed: $1"
}
notify() { [ "$NOTIFY" = 1 ] && python push.py "$1" "$PUB" || true; }
bars() { python prices.py intraday "$PUB" || true; }   # 15-minute prices for paper-trade results
screen() {  # announced as "screen ready" in the morning, or as a preview when built after the close (push.py decides)
  python run.py premarket --no-browser --json "$PUB" || return 1
  [ "$(hhmm)" -ge 1530 ] && bars   # after the close: the full day's 15-minute prices
  notify screen
  publish "screen $(date '+%F %H:%M')"
  [ "$(hhmm)" -ge 1530 ] && market
  return 0
}
market() {  # every other NSE and BSE stock against the same rules; never fails the run
  python market.py "$PUB" --max-minutes "${MARKET_MINUTES:-60}" && publish "market analysis $(date '+%F %H:%M')" || true
}

# Live session: every minute NSE prices (live.py); the screen at 9:10 if this run hasn't made it; breakout scans every
# 5 minutes 9:31-11:00; 15-minute prices for paper trades every 15 minutes; the square-off reminder at 3:14.
session() {  # session END_HHMM
  local end=$((10#$1)) last_orb=0 last_bars=0 screened=0 sq=0 empty=0 closed=0 t0 h code
  wait_until 0859
  while [ "$(hhmm)" -lt "$end" ]; do
    t0=$(date +%s); h=$(hhmm)
    python live.py "$PUB"; code=$?
    if [ "$code" -eq 3 ]; then closed=$((closed + 1)); else closed=0; fi
    if [ "$closed" -ge 3 ]; then echo "NSE says the market is closed today (holiday). Stopping."; publish "market closed $(date '+%H:%M')"; break; fi
    if [ "$MODE" = morning ] && [ "$screened" = 0 ] && [ "$h" -ge 910 ] && [ "$h" -lt 1300 ]; then
      screen && screened=1 || { echo "::warning::screen failed; retrying next minute"; [ "$h" -ge 1000 ] && screened=1; }
    fi
    if [ "$h" -ge 931 ] && [ "$h" -le 1100 ] && [ $((t0 - last_orb)) -ge 290 ]; then
      last_orb=$t0
      python run.py orb --no-browser --json "$PUB"; code=$?
      if [ "$code" -eq 3 ]; then empty=$((empty + 1)); else empty=0; fi
      notify screen      # only does something if the screen failed and the scan rebuilt it
      notify breakouts
    fi
    if [ "$h" -ge 930 ] && [ $((t0 - last_bars)) -ge 900 ]; then last_bars=$t0; bars; fi
    if [ "$h" -ge 1514 ] && [ "$sq" = 0 ]; then sq=1; bars; notify squareoff; fi
    publish "live $(date '+%H:%M')"
    sleep $(( (t0 + 60 - $(date +%s)) > 0 ? (t0 + 60 - $(date +%s)) : 1 ))
  done
  [ "$end" -ge 1530 ] && { bars; publish "close $(date '+%H:%M')"; }
  return 0
}

AUTO=0
if [ "$MODE" = auto ]; then
  AUTO=1
  if [ "$(hhmm)" -ge 1530 ]; then MODE=premarket; elif [ "$(hhmm)" -ge 1300 ]; then MODE=afternoon; else MODE=morning; fi
fi
# Scheduled runs have backup start times (see trade.yml). A backup that finds its job already done today stops here.
TODAY=$(date +%F)
done_today() { [ "$(cat "$PUB/state/$1" 2>/dev/null)" = "$TODAY" ]; }
mark_done() { mkdir -p "$PUB/state" && echo "$TODAY" > "$PUB/state/$1"; }
if [ "$AUTO" = 1 ] && [ "$(date +%u)" -le 5 ]; then
  if [ "$MODE" = morning ] && done_today morning; then echo "Morning run already done today; this was a backup start."; exit 0; fi
  if [ "$MODE" = afternoon ] && done_today afternoon; then echo "Afternoon run already done today; this was a backup start."; exit 0; fi
  if [ "$MODE" = premarket ] && done_today evening; then echo "Evening preview already done today; this was a backup start."; exit 0; fi
fi
echo "mode: $MODE, IST now $(date '+%a %F %H:%M')"

case "$MODE" in
  premarket) screen && [ "$AUTO" = 1 ] && mark_done evening && publish "evening done $(date '+%H:%M')" ;;
  market) market ;;
  orb)
    python run.py orb --no-browser --json "$PUB"; bars; notify breakouts; publish "scan $(date '+%H:%M')" ;;
  squareoff)
    wait_until 1514
    bars; notify squareoff; publish "square-off reminder $(date '+%H:%M')" ;;
  morning)
    mark_done morning     # published with the first update, so backup starts after this one stop
    session 1330 ;;
  afternoon)
    mark_done afternoon
    session 1531 ;;
  live) session 1531 ;;
  *) echo "unknown MODE $MODE"; exit 1 ;;
esac
