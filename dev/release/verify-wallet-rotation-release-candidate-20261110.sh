#!/usr/bin/env bash
# Consolidated wallet release candidate verification. Tests only.
# Requires explicitly pinned Git HEAD. No production DB, compose or deploy.
set -Eeuo pipefail
umask 077
REF="${DAVARNA_WALLET_RELEASE_TEST_REF:?Set SHA of release candidate}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo "BLOCKED: invalid SHA"; exit 2; }
[[ "${DAVARNA_WALLET_RELEASE_TEST_APPROVAL:-}" == "RUN_ISOLATED_WALLET_RELEASE_TESTS" ]] || {
  echo "BLOCKED: isolated test opt-in missing"; exit 2;
}
cd /opt/davarna-v2
git cat-file -e "$REF^{commit}"
echo "===== PINNED ISOLATED MINI/BOT/BACKEND TESTS ====="
runner_a="$(mktemp /tmp/davarna-wallet-release-isolated.XXXXXX.sh)"
runner_b="$(mktemp /tmp/davarna-wallet-release-mysql.XXXXXX.sh)"
trap 'rm -f -- "$runner_a" "$runner_b"' EXIT
git show "$REF:dev/release/test-superadmin-command-v12-20261110.sh" > "$runner_a"
git show "$REF:dev/release/test-wallet-rotation-mysql-disposable-20261110.sh" > "$runner_b"
bash -n "$runner_a"
bash -n "$runner_b"
DAVARNA_V12_TEST_REF="$REF" bash "$runner_a"
echo "===== DISPOSABLE MYSQL INTEGRATION ====="
DAVARNA_WALLET_MYSQL_TEST_REF="$REF" \
 DAVARNA_WALLET_MYSQL_TEST_APPROVAL=RUN_DISPOSABLE_MYSQL_ONLY bash "$runner_b"
echo "===== WALLET ROTATION CANDIDATE ISOLATED PASS ====="
echo "SOURCE=$REF"
echo "No production database, wallet settings, images, or services were changed."
