#!/usr/bin/env bash
# No Production changes. Pinned v1.1 superadmin UI offline gate.
set -Eeuo pipefail
umask 077
cd /opt/davarna-v2
BRANCH=feature/superadmin-live-dashboard-v11-20261109
REF="$(printenv DAVARNA_SUPERADMIN_V11_REF || true)"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || { echo "BLOCKER: pinned SHA required"; exit 2; }
[[ "$(git rev-parse "origin/$BRANCH")" == "$REF" ]] || { echo "BLOCKER: SHA changed"; exit 2; }
command -v node >/dev/null || { echo "BLOCKER: Node.js unavailable"; exit 2; }
TMP="$(mktemp -d /tmp/davarna-superadmin-v11.XXXXXX)"
trap 'rm -rf -- "$TMP"' EXIT
git archive "$REF" -- \
  backend/app/static/mini/index.html \
  backend/app/static/mini/app.js \
  backend/app/static/mini/ux-v2.css \
  backend/tests/js/test_superadmin_dashboard_v11.mjs | tar -x -C "$TMP"
echo "===== SYNTAX ====="
node --check "$TMP/backend/app/static/mini/app.js"
node --check "$TMP/backend/tests/js/test_superadmin_dashboard_v11.mjs"
echo "===== SUPERADMIN V1.1 CONTRACT ====="
node "$TMP/backend/tests/js/test_superadmin_dashboard_v11.mjs"
echo "===== SUPERADMIN V1.1 OFFLINE GATE COMPLETE ====="
