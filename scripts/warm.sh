#!/usr/bin/env bash
# Keep one N-ATLaS GPU container warm for a pilot session, then return to scale-to-zero.
#
# Usage:   scripts/warm.sh 90          # minutes (default 60)
#          scripts/warm.sh off         # set min_containers back to 0 now
#
# Costs GPU time for the whole window (one L4). The default deployment stays at min_containers=0.
# Ctrl+C, an error or the end of the window all reset min_containers to 0. Run inside the venv.
set -euo pipefail

APP="natlas-serve"
FUNCTION="serve"

set_min() {
  python - "$1" <<'PY'
import sys
import modal

settings = modal.Function.from_name("natlas-serve", "serve").update_autoscaler(min_containers=int(sys.argv[1]))
print(f"natlas-serve/serve min_containers={settings.min_containers}")
PY
}

if [[ "${1:-}" == "off" ]]; then
  set_min 0
  exit 0
fi

minutes="${1:-60}"
if ! [[ "$minutes" =~ ^[0-9]+$ ]] || (( minutes < 1 || minutes > 480 )); then
  echo "minutes must be 1..480" >&2
  exit 2
fi

trap 'set_min 0' EXIT
trap 'exit 130' INT TERM
set_min 1
echo "$APP/$FUNCTION warm until $(date -d "+${minutes} min" '+%H:%M %Z'); Ctrl+C to stop early."
# sleep in the background + wait, so Ctrl+C/kill run the EXIT trap at once (bash defers traps while a
# foreground child runs).
sleep "$((minutes * 60))" &
wait $!
