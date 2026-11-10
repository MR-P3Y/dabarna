#!/usr/bin/env bash
# Build V1.2 wallet backend + V1.3 Superadmin UI as a detached, NON-DEPLOYED
# candidate. Fail closed on any patch conflict. Production is never modified.
set -Eeuo pipefail
umask 077
REF="${DAVARNA_ZERO_KM_COMBINED_REF:?Pin exact V1.2 source commit}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo "BLOCKED: invalid SHA" >&2; exit 2; }
[[ "${DAVARNA_ZERO_KM_BUILD_APPROVAL:-}" == "BUILD_NONDEPLOYED_CANDIDATE_ONLY" ]] || {
  echo "BLOCKED: build-only approval missing" >&2; exit 2;
}
ROOT=/opt/davarna-v2
BASE=cf7652dc7b6b4ddfcab167214dacae37aa874ea8
UI_HEAD=247c2bee78f85d54aabec35078312b94c9efcc92
UI_MERGE=13467120109c941bc1f4a5b4e88be1fdabddb479
TAG="davarna-backend:zero-km-combined-${REF:0:12}"
cd "$ROOT"
for sha in "$REF" "$BASE" "$UI_HEAD" "$UI_MERGE"; do
  git cat-file -e "$sha^{commit}" || { echo "BLOCKED: missing source $sha"; exit 2; }
done
[[ -n "$(git diff --name-only "$BASE" "$UI_HEAD" -- backend/app/static/mini/index.html backend/app/static/mini/app.js backend/app/static/mini/ux-v2.css)" ]] || {
  echo "BLOCKED: no V1.3 overlay diff"; exit 3;
}
WORK="$(mktemp -d /tmp/davarna-zero-combined.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git archive "$REF" | tar -x -C "$WORK"
echo "===== MERGE V1.3 SUPERVISOR UI WITH V1.2 WALLET CONTROLS ====="
git show "$UI_HEAD:backend/app/static/mini/index.html" > "$WORK/v13-index.html"
git show "$UI_HEAD:backend/app/static/mini/app.js" > "$WORK/v13-app.js"
python3 - "$WORK" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
mini = root / "backend/app/static/mini"

def one(text, token, label):
    count = text.count(token)
    if count != 1:
        raise SystemExit(f"BLOCKED: {label} marker count={count}")
    return text.index(token)

def section(src, start, end, label):
    i = one(src, start, label + " start")
    j = src.find(end, i + len(start))
    if j < 0:
        raise SystemExit(f"BLOCKED: {label} end marker missing")
    return i, j

old_html = (mini / "index.html").read_text()
v13_html = (root / "v13-index.html").read_text()
begin = '              <details id="superAdminSection"'
end = '\n            </div>\n          </article>'
old_i, old_j = section(old_html, begin, end, "V1.2 superadmin")
new_i, new_j = section(v13_html, begin, end, "V1.3 superadmin")
old_section = old_html[old_i:old_j]
new_section = v13_html[new_i:new_j]

# V1.2 has owner-controlled wallet proposals absent from the older V1.3 UI.
# Preserve all such form IDs/handlers while inserting the V1.3 five-panel layout.
wallet_start = '                  <details id="superCryptoWalletSection"'
wallet_end = '\n                  </details>'
a, b = section(old_section, wallet_start, wallet_end, "V1.2 crypto wallet")
c, d = section(new_section, wallet_start, wallet_end, "V1.3 crypto wallet")
v12_wallet = old_section[a:b + len(wallet_end)]
v13_wallet = new_section[c:d + len(wallet_end)]
assert v12_wallet.count('superCryptoProposalSubmitBtn') == 1
assert v13_wallet.count('superCryptoProposalSubmitBtn') == 0
new_section = new_section.replace(v13_wallet, v12_wallet, 1)
merged_html = old_html[:old_i] + new_section + old_html[old_j:]
for required in (
    'superadmin-workspace-v13', 'superPanelPayments', 'superPanelAccounts',
    'superPanelRoles', 'superPanelSecurity', 'superCryptoProposalSubmitBtn',
    'superCryptoProposalsList',
):
    if merged_html.count(required) < 1:
        raise SystemExit(f"BLOCKED: merged HTML missing {required}")
(mini / "index.html").write_text(merged_html)

old_js = (mini / "app.js").read_text()
new_js = (root / "v13-app.js").read_text()
js_start = 'function showSuperAdminPanelV13('
js_old_start = 'function wireAdminQuickNavigationV2()'
js_end = 'function syncAdminSelectedGameListV2()'
x, y = section(new_js, js_start, js_end, "V1.3 navigation")
p, q = section(old_js, js_old_start, js_end, "V1.2 navigation")
if 'function showSuperAdminPanelV13(' in old_js:
    raise SystemExit("BLOCKED: V1.3 navigation already exists in V1.2")
merged_js = old_js[:p] + new_js[x:y] + old_js[q:]
for required in ('showSuperAdminPanelV13(', 'superCryptoProposalSubmitBtn', 'wireAdminQuickNavigationV2()'):
    if required not in merged_js:
        raise SystemExit(f"BLOCKED: merged JS missing {required}")
(mini / "app.js").write_text(merged_js)
print("PASS: V1.3 five-panel UI merged with V1.2 wallet proposal editor")
PY
git show "$UI_HEAD:backend/app/static/mini/ux-v2.css" \
  | awk '/^\/\* Superadmin v1\.3:/ {found=1} found {print}' > "$WORK/v13.css"
[[ -s "$WORK/v13.css" ]] || { echo "BLOCKED: V1.3 CSS missing"; exit 4; }
grep -Fq 'Superadmin v1.3:' "$WORK/v13.css"
if grep -Fq 'Superadmin v1.3:' "$WORK/backend/app/static/mini/ux-v2.css"; then
  echo "BLOCKED: V1.3 CSS already present unexpectedly"; exit 4
fi
cat "$WORK/v13.css" >> "$WORK/backend/app/static/mini/ux-v2.css"
git show "$UI_HEAD:backend/tests/js/test_superadmin_sections_v13.mjs" \
  > "$WORK/backend/tests/js/test_superadmin_sections_v13.mjs"

echo "===== COMBINED CONTRACT CHECKS ====="
node --check "$WORK/backend/app/static/mini/app.js"
node "$WORK/backend/tests/js/test_superadmin_sections_v13.mjs"
grep -Fq 'superadmin-workspace-v13' "$WORK/backend/app/static/mini/index.html"
grep -Fq 'DAVARNA_CRYPTO_ROTATION_PRODUCTION' "$WORK/backend/app/services/crypto_destination_state.py"
grep -Fq 'destination_address' "$WORK/backend/app/services/crypto_chain_service.py"
echo "===== BUILD NON-DEPLOYED BACKEND IMAGE ====="
# No direct production mounts, names, ports, DB connections, or Bot startup.
docker build --pull=false --tag "$TAG" -f "$WORK/backend/Dockerfile" "$WORK/backend"
echo "===== VERIFY CANDIDATE IMAGE ====="
for file in \
  app/static/mini/index.html \
  app/static/mini/app.js \
  app/static/mini/ux-v2.css \
  app/services/crypto_destination_state.py \
  app/services/crypto_chain_service.py; do
  a="$(sha256sum "$WORK/backend/$file" | cut -d' ' -f1)"
  b="$(docker run --rm --network none --read-only --entrypoint sha256sum "$TAG" "/app/$file" | cut -d' ' -f1)"
  [[ "$a" == "$b" ]] || { echo "BLOCKED: image mismatch $file"; exit 5; }
  echo "PASS: $file"
done
echo "===== NON-DEPLOYED ZERO-KM COMBINED IMAGE READY ====="
echo "IMAGE=$TAG"
docker image inspect -f 'IMAGE_ID={{.Id}}' "$TAG"
echo "PRODUCTION_UNCHANGED=true"
