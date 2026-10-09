#!/usr/bin/env bash
# Keep the N-ATLaS LLM and the ASR GPU warm for a pilot session, then back to scale-to-zero.
#
# Usage:   scripts/warm.sh 90          # minutes (default 60): min_containers=1 on both, pings, prints cold start
#          scripts/warm.sh off         # set both back to 0 now
#
# Costs two L4 GPUs for the whole window. The deployed default stays at min_containers=0.
# Ctrl+C, kill or an error all reset both to 0. Run inside the venv. Logic: scripts/warm.py.
set -euo pipefail
exec python "$(dirname "$0")/warm.py" "$@"
