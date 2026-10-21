#!/usr/bin/env bash
# Runs the screener on GitHub and publishes the phone app's data (see .github/workflows/trade.yml).
# Clock times below are IST: the workflow sets TZ=Asia/Kolkata.
#   MODE=auto       before 3:30 PM -> morning, after -> preview for the next session
#   MODE=morning    wait for the pre-open, publish the screen ~9:10, then scan breakouts every 5 min until 11:00
#   MODE=premarket  just the screen
#   MODE=orb        one breakout scan
#   MODE=squareoff  the 3:15 reminder (only on days the market traded)
# NOTIFY=0 turns push notifications off (used when the workflow runs because the code changed).
set -u
cd "$(dirname "$0")"
PUB="${PUB:-$GITHUB_WORKSPACE/pub}"
MODE="${MODE:-auto}"
NOTIFY="${NOTIFY:-1}"

hhmm() { echo $((10#$(date +%H%M))); }
wait_until() { while [ "$(hhmm)" -lt "$((10#$1))" ]; do sleep 20; done; }

publish() {  # the trade-data branch always holds a single commit with the contents of pub/
  ( cd "$PUB" && rm -rf .git && git init -q -b trade-data && git add -A &&
    git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" commit -qm "$1" &&
    git push -qf "${PUSH_URL:-https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git}" trade-data ) \
    && echo "published: $1" || echo "::warning::publish failed: $1"
  rm -rf "$PUB/.git"
}
notify() { [ "$NOTIFY" = 1 ] && python push.py "$1" "$PUB" || true; }
screen() {  # announced as "screen ready" in the morning, or as a preview when built after the close (push.py decides)
  python run.py premarket --no-browser --json "$PUB" || return 1
  notify screen
  publish "screen $(date '+%F %H:%M')"
}

if [ "$MODE" = auto ]; then
  if [ "$(hhmm)" -ge 1530 ]; then MODE=premarket; else MODE=morning; fi
fi
echo "mode: $MODE, IST now $(date '+%a %F %H:%M')"

case "$MODE" in
  premarket) screen ;;
  orb)
    python run.py orb --no-browser --json "$PUB"; notify breakouts; publish "scan $(date '+%H:%M')" ;;
  squareoff)
    wait_until 1514
    notify squareoff; publish "square-off reminder $(date '+%H:%M')" ;;
  morning)
    wait_until 0910
    screen || echo "::warning::morning screen failed; the breakout scan will retry it"
    wait_until 0931
    empty=0
    while [ "$(hhmm)" -le 1100 ]; do
      python run.py orb --no-browser --json "$PUB"; code=$?
      notify screen      # only does something if the screen above failed and the scan rebuilt it
      notify breakouts
      publish "scan $(date '+%H:%M')"
      if [ "$code" -eq 3 ]; then
        empty=$((empty + 1))
        if [ "$empty" -ge 3 ]; then echo "No intraday prices three times in a row: market holiday or data outage. Stopping."; break; fi
      else
        empty=0
      fi
      sleep 270
    done ;;
  *) echo "unknown MODE $MODE"; exit 1 ;;
esac
