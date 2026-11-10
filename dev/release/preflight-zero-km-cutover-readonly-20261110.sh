#!/usr/bin/env bash
# READ-ONLY preflight for clean Davarna cutover. No compose up/down,
# no SQL writes, no git checkout, no env or credential dumps.
set -Eeuo pipefail
umask 077
[[ "${DAVARNA_ZERO_KM_PREFLIGHT_APPROVAL:-}" == "READ_ONLY_CUTOVER_PREFLIGHT" ]] || {
  echo "BLOCKED: explicit read-only approval required"; exit 2;
}
echo "===== CURRENT PRODUCTION CONTAINERS ====="
for svc in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  docker inspect -f '{{.Name}} | {{.Config.Image}} | {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$svc"
done
echo "===== LIVE CONFIGURATION (NO SECRETS) ====="
docker exec davarna-backend python -c '
from app.core import config as c
from sqlalchemy.engine import make_url
db = make_url(c.DATABASE_URL)
print("db_driver:", db.get_backend_name())
print("db_host:", db.host)
print("db_schema:", db.database)
for field in ("GAME_AUTO_DRAW_ENABLED","GAME_AUTOPILOT_RUNTIME_ENABLED","CRYPTO_PAYMENTS_ENABLED","CRYPTO_AUTO_CONFIRM_ENABLED","RBAC_OWNER_USER_ID"):
    print(field, getattr(c,field,None))
'
echo "===== LIVE DB COUNTS ONLY, NO PERSONAL DATA ====="
docker exec -i davarna-backend python - <<'PY'
from sqlalchemy import text
from app.core.db import SessionLocal
tables = (
    "users", "wallets", "wallet_txs", "games", "game_purchases",
    "crypto_deposit_requests", "deposit_requests", "withdraw_requests",
)
with SessionLocal() as db:
    for table in tables:
        n = db.execute(text("SELECT COUNT(*) FROM " + table)).scalar_one()
        print(f"{table}: {int(n)}")
    for table in ("games", "crypto_deposit_requests", "deposit_requests", "withdraw_requests"):
        rows = db.execute(text(
            "SELECT status, COUNT(*) FROM " + table + " GROUP BY status ORDER BY status"
        )).all()
        print(f"{table}_statuses:", {str(k): int(v) for k, v in rows})
    print("schema_head:", db.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
PY
echo "===== CURRENT DATA VOLUMES (DO NOT DELETE) ====="
docker inspect -f '{{.Name}} {{range .Mounts}}{{.Type}}:{{.Source}} -> {{.Destination}} {{end}}' davarna-mysql davarna-redis davarna-backend davarna-bot
echo "===== FREE DISK SPACE ====="
df -h /opt/davarna /var/lib/docker
echo "===== CURRENT V1.3 HEALTH ====="
curl -fsS --max-time 10 http://127.0.0.1:18080/health/db
echo
echo "===== CUTOVER PRE-FLIGHT READONLY FINISHED ====="
echo "No DB tables, Docker volumes, running containers or payment settings were modified."
