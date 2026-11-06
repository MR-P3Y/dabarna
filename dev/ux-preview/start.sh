#!/usr/bin/env bash
# Local-only disconnected visual preview. Never serves the repository or production backend.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$ROOT/backend/app/static/mini"
PORT="${DAVARNA_UX_PREVIEW_PORT:-19090}"
PID_FILE="/tmp/davarna-ux-preview-${PORT}.pid"
DIR_FILE="/tmp/davarna-ux-preview-${PORT}.dir"
LOG_FILE="/tmp/davarna-ux-preview-${PORT}.log"

[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT >= 1024 && PORT <= 65535 )) || {
  echo "Invalid preview port: $PORT" >&2
  exit 1
}

for path in "$ROOT/dev/ux-preview/index.html" "$SRC/styles.css" "$SRC/ux-v2.css"; do
  [[ -f "$path" ]] || { echo "Missing required file: $path" >&2; exit 1; }
done

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE")"
  if [[ "$EXISTING_PID" =~ ^[0-9]+$ ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    EXISTING_CMD="$(ps -p "$EXISTING_PID" -o args= || true)"
    if [[ "$EXISTING_CMD" == *"http.server $PORT --bind 127.0.0.1 --directory /tmp/davarna-ui-preview."* ]]; then
      echo "Preview is already running on http://127.0.0.1:${PORT}/index.html"
      exit 0
    fi
  fi
fi

if ss -ltnH "( sport = :${PORT} )" | grep -q .; then
  echo "Port $PORT is already in use; refusing to affect existing services." >&2
  exit 1
fi

PREVIEW_DIR="$(mktemp -d /tmp/davarna-ui-preview.XXXXXX)"
install -m 0644 "$ROOT/dev/ux-preview/index.html" "$PREVIEW_DIR/index.html"
install -m 0644 "$SRC/styles.css" "$PREVIEW_DIR/styles.css"
install -m 0644 "$SRC/ux-v2.css" "$PREVIEW_DIR/ux-v2.css"
for name in assets fonts; do
  if [[ -d "$SRC/$name" ]]; then
    cp -a "$SRC/$name" "$PREVIEW_DIR/$name"
  fi
done

nohup python3 -m http.server "$PORT" \
  --bind 127.0.0.1 --directory "$PREVIEW_DIR" \
  </dev/null >"$LOG_FILE" 2>&1 &
PID="$!"
printf '%s\n' "$PID" > "$PID_FILE"
printf '%s\n' "$PREVIEW_DIR" > "$DIR_FILE"

for attempt in 1 2 3 4 5; do
  if curl -fsS --max-time 2 -o /dev/null "http://127.0.0.1:${PORT}/index.html"; then
    echo "READY: http://127.0.0.1:${PORT}/index.html"
    echo "Preview PID: $PID"
    echo "Only localhost is listening; no production API or database is used."
    exit 0
  fi
  sleep 0.5
done

echo "Preview failed to start; log follows:" >&2
cat "$LOG_FILE" >&2 || true
kill "$PID" 2>/dev/null || true
rm -f "$PID_FILE" "$DIR_FILE"
rm -rf -- "$PREVIEW_DIR"
exit 1
