#!/usr/bin/env bash
# Remove ONLY isolated finance UI staging resources; never touch Production.
set -Eeuo pipefail
[[ "$(id -u)" == 0 ]] || { echo "root required"; exit 2; }
[[ "${DAVARNA_FINANCE_UI_STAGE_CLEANUP_APPROVAL:-}" == "REMOVE_ISOLATED_FINANCE_STAGE" ]] || { echo "explicit cleanup approval required"; exit 2; }
for c in davarna-finance-ui-api davarna-finance-ui-redis; do
  if docker container inspect "$c" >/dev/null 2>&1; then
    docker rm -f "$c"
  fi
done
if docker network inspect davarna-finance-ui-isolated >/dev/null 2>&1; then
  docker network rm davarna-finance-ui-isolated
fi
# Deliberately keep /opt/davarna-finance-ui-staging for investigation.
echo "PASS: isolated containers removed. Staging test files retained."
