#!/usr/bin/env bash
# Stop only the localhost demo server started by dev/ux-preview/start.sh.
set -Eeuo pipefail
PORT="${DAVARNA_UX_PREVIEW_PORT:-19090}"
[[ "$PORT" =~ ^[0-9]+$ ]] || { echo "Invalid port" >&2; exit 1; }
PID_FILE="/tmp/davarna-ux-preview-${PORT}.pid"
DIR_FILE="/tmp/davarna-ux-preview-${PORT}.dir"
if [[ ! -f "$PID_FILE" ]]; then
  echo "No saved preview process; nothing changed."
  exit 0
fi
PID="$(cat "$PID_FILE")"
[[ "$PID" =~ ^[0-9]+$ ]] || { echo "Invalid preview PID; nothing changed." >&2; exit 1; }
CMD="$(ps -p "$PID" -o args= || true)"
if [[ -n "$CMD" ]]; then
  [[ "$CMD" == *"http.server $PORT --bind 127.0.0.1 --directory /tmp/davarna-ui-preview."* ]] || {
    echo "Saved PID belongs to another process; refusing to kill it." >&2
    exit 1
  }
  kill "$PID"
fi
if [[ -f "$DIR_FILE" ]]; then
  PREVIEW_DIR="$(cat "$DIR_FILE")"
  case "$PREVIEW_DIR" in
    /tmp/davarna-ui-preview.*) [[ -d "$PREVIEW_DIR" ]] && rm -rf -- "$PREVIEW_DIR" ;;
    *) echo "Unsafe preview directory; leaving it untouched." >&2 ;;
  esac
fi
rm -f "$PID_FILE" "$DIR_FILE"
echo "Preview stopped. Production services were not touched."
