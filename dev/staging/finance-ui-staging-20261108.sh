#!/usr/bin/env bash
# Isolated finance Mini App staging: synthetic identity, SQLite, separate Redis.
# No production mounts/secrets/DB changes. Only listen on loopback.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
REF=90f66708e26d999617e130df5550119b8c2ff611
IMAGE=davarna-backend:forum-mini-e7517922-stage2
IMAGE_ID=sha256:b6d2709c3f78ce946a90aeb1b2bd6774acfa6b72a88cd604c370842cc3824850
DIR=/opt/davarna-finance-ui-staging
NET=davarna-finance-ui-isolated
CACHE=davarna-finance-ui-redis
API=davarna-finance-ui-api
die(){ echo "BLOCKER: $*" >&2; exit 2; }
[[ "$(id -u)" == 0 ]] || die "root required"
[[ "${DAVARNA_FINANCE_UI_STAGE_APPROVAL:-}" == ISOLATED_UI_ONLY ]] || die "isolated UI opt-in required"
cd "$ROOT"
git cat-file -e "$REF^{commit}" || die "source commit missing"
[[ "$(docker image inspect -f '{{.Id}}' "$IMAGE")" == "$IMAGE_ID" ]] || die "base image changed"
for c in "$API" "$CACHE"; do
  ! docker container inspect "$c" >/dev/null 2>&1 || die "container already exists: $c"
done
! docker network inspect "$NET" >/dev/null 2>&1 || die "staging network already exists"
[[ ! -e "$DIR" ]] || die "staging directory already exists"
! ss -lnt | grep -qE '127\\.0\\.0\\.1:18083[[:space:]]' || die "port 18083 occupied"
(( $(awk '/MemAvailable:/ {print $2}' /proc/meminfo) > 1000*1024 )) || die "not enough available RAM"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || die "Production service unhealthy: $c"
done
install -d -m 700 "$DIR" "$DIR/data"
git archive "$REF" -- backend | tar -x -C "$DIR"
cat > "$DIR/seed.py" <<'PY'
from pathlib import Path
import json
from app.core.db import Base, engine, SessionLocal
import app.models
from app.models.user import User
from app.models.rbac import Role, UserRole
from app.models.wallet import Wallet
from app.models.finance import DepositRequest, WithdrawRequest
from app.core.mini_security import issue_session_token
Base.metadata.create_all(engine)
with SessionLocal.begin() as db:
    db.add_all([
        User(id=91001,tg_user_id=990000000001,username="finance_preview",first_name="Staging Admin"),
        User(id=91002,tg_user_id=990000000002,username="preview_customer",first_name="Synthetic Customer"),
        Role(id=91001,name="SUPER_ADMIN"),
    ])
    db.flush()
    db.add_all([
        UserRole(id=91001,user_id=91001,role_id=91001),
        Wallet(id=91002,user_id=91002,balance=85000),
        DepositRequest(id=91001,user_id=91002,amount=12000,status="PENDING_REVIEW"),
        WithdrawRequest(id=91001,user_id=91002,amount=5000,
            full_name="Synthetic Customer",iban="IR000000000000000000000000",
            card_number="0000000000000000",account_number="000000",status="PENDING"),
    ])
token, expiry=issue_session_token(91001,ttl_sec=3600)
Path("/data/preview-session.json").write_text(json.dumps({"token":token,"tokenExp":expiry,"userId":91001}))
print("PASS: synthetic SuperAdmin seeded")
PY
docker network create --internal --driver bridge "$NET" >/dev/null
docker run -d --name "$CACHE" --network "$NET" --restart no \
  --memory 64m --cpus 0.25 --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /data:rw,nosuid,nodev \
  redis:7-alpine redis-server --save '' --appendonly no >/dev/null
COMMON=(--network "$NET" --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 384m --cpus 0.75 --pids-limit 128 \
  --tmpfs /tmp:rw,nosuid,nodev --tmpfs /run:rw,nosuid,nodev \
  -v "$DIR/backend:/app:ro" -v "$DIR/data:/data:rw" \
  -e 'DATABASE_URL=sqlite:////data/staging.sqlite' \
  -e "REDIS_URL=redis://$CACHE:6379/0" \
  -e 'TELEGRAM_BOT_TOKEN=000000000:STAGING_ONLY' \
  -e 'MINI_SESSION_SECRET=LOCAL_STAGING_ONLY_NOT_FOR_PRODUCTION_20261108' \
  -e 'RBAC_OWNER_USER_ID=91001' \
  -e 'SUPER_ADMIN_TG_USER_IDS=990000000001' \
  -e 'ADMIN_AUTH_ENABLED=true' \
  -e 'GAME_TAMBOLA_V2_ENABLED=false' \
  -e 'GAME_AUTO_DRAW_ENABLED=false' \
  -e 'GAME_AUTOPILOT_RUNTIME_ENABLED=false' \
  -e 'CRYPTO_PAYMENTS_ENABLED=false' \
  -e 'CRYPTO_AUTO_CONFIRM_ENABLED=false' \
  -e 'RECEIPTS_DIR=/tmp/receipts' \
  -e 'PYTHONDONTWRITEBYTECODE=1' -w /app)
docker run --rm "${COMMON[@]}" -v "$DIR/seed.py:/tmp/seed.py:ro" \
  --entrypoint python "$IMAGE" /tmp/seed.py
python3 - "$DIR/backend/app/static/mini/index.html" "$DIR/data/preview-session.json" <<'PY'
import json,pathlib,sys
page=pathlib.Path(sys.argv[1]); data=json.loads(pathlib.Path(sys.argv[2]).read_text())
html=page.read_text()
assert html.count("</head>")==1
inject="<script>sessionStorage.setItem('davarna_mini_session_v1',"+json.dumps(json.dumps(data,separators=(',',':')))+");</script>"
page.write_text(html.replace("</head>",inject+"\n</head>"))
PY
docker run -d --name "$API" "${COMMON[@]}" \
  -p 127.0.0.1:18083:8000 --entrypoint uvicorn "$IMAGE" \
  app.main:app --host 0.0.0.0 --port 8000 >/dev/null
for i in $(seq 1 30); do
  curl -fsS --max-time 2 http://127.0.0.1:18083/health/db >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS --max-time 5 http://127.0.0.1:18083/health/db || die "staging backend not ready"
curl -fsS --max-time 5 -o /dev/null http://127.0.0.1:18083/mini/index.html || die "staging Mini unavailable"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || die "Production unhealthy after staging"
done
echo "PASS: isolated staging http://127.0.0.1:18083/mini/index.html"
echo "Only synthetic test identity. No Production DB, secrets or runtime changes."
