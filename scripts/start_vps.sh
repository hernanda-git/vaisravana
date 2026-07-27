#!/usr/bin/env bash
# Start Vaiśravaṇa on a bare VPS (Tencent / any Linux).
# Robust: restarts on crash, logs to data/vaisravana.log, runs in the background.
#
# Usage:
#   ./scripts/start_vps.sh          # start (detached)
#   ./scripts/start_vps.sh stop     # stop
#   ./scripts/start_vps.sh status   # show pid
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="$ROOT/data/vaisravana.pid"
LOGFILE="$ROOT/data/vaisravana.log"
PY="$ROOT/.venv/bin/python"

case "${1:-start}" in
  stop)
    if [[ -f "$PIDFILE" ]]; then
      kill "$(cat "$PIDFILE")" 2>/dev/null && echo "stopped"
      rm -f "$PIDFILE"
    fi
    ;;
  status)
    if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "running (pid $(cat "$PIDFILE"))"
    else
      echo "not running"
    fi
    ;;
  start|*)
    mkdir -p "$ROOT/data"
    if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "already running (pid $(cat "$PIDFILE"))"
      exit 0
    fi
    cd "$ROOT"
    nohup "$PY" scripts/bot_paper.py >>"$LOGFILE" 2>&1 &
    echo $! >"$PIDFILE"
    echo "started (pid $!) — tail -f $LOGFILE"
    ;;
esac
