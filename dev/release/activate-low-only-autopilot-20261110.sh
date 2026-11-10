#!/usr/bin/env bash
# One-time controlled Production LOW-only autopilot activation.
# This WILL create a LOW system game and allows real users to buy cards.
# Does not issue purchases, call numbers, transfer money, or pay prizes directly.
set -Eeuo pipefail
umask 077
die(){ echo "BLOCKER: $*" >&2; exit 2; }
ROOT=/opt/davarna-v2
PROD=/opt/davarna
REF="${DAVARNA_LOW_AUTOPILOT_REF:?pinned ref required}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || die "invalid SHA"
[[ "${DAVARNA_LOW_AUTOPILOT_APPROVAL:-}" == "ENABLE_LOW_SYSTEM_GAME_ONLY" ]] || die "explicit LOW-only approval required"
[[ "$(id -u)" == 0 ]] || die "root required"
cd "$ROOT"
git cat-file -e "$REF^{commit}" || die "source ref unavailable"
exec 9>/run/davarna-auto-draw-recovery.lock
flock -n 9 || die "another release holds lock"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
 [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || die "$c not healthy"
done
[[ "$(docker exec davarna-backend python -c 'from app.core import config as c;print(int(c.GAME_AUTO_DRAW_ENABLED),int(c.GAME_AUTOPILOT_RUNTIME_ENABLED))')" == "1 0" ]] || die "expected auto draw ON and autopilot OFF"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == davarna-backend:auto-clock-92471d0132b4 ]] || die "deployed backend image changed"
echo "===== PRE-FLIGHT DB, CONFIG, AND NO ACTIVE GAMES ====="
docker exec -i davarna-backend python - <<'PY'
from sqlalchemy import select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game
from app.models.game_autopilot import GameAutopilotConfig
from app.models.user import User
from app.services.game_autopilot_config_service import GameAutopilotConfigService
assert cfg.GAME_AUTO_DRAW_ENABLED and not cfg.GAME_AUTOPILOT_RUNTIME_ENABLED
assert cfg.GAME_AUTOPILOT_SYSTEM_USER_ID is not None
assert int(cfg.USER_FORUM_CHAT_ID or cfg.DEFAULT_TG_GROUP_ID or 0)==-1003614031001, "Telegram group drift"
with SessionLocal() as db:
 assert db.get(User,int(cfg.GAME_AUTOPILOT_SYSTEM_USER_ID)), "system user missing"
 active=db.execute(select(Game.id).where(Game.status.in_(("LOBBY","RUNNING")))).scalars().all()
 assert not active, f"BLOCKER: live active games {active}"
 expected={"LOW":(5000,5,60,6),"MEDIUM":(3000,10,30,8),"HIGH":(20000,15,30,10)}
 for lvl,(price,interval,countdown,topic) in expected.items():
  c=db.get(GameAutopilotConfig,lvl)
  assert c and bool(c.enabled), f"config missing/disabled: {lvl}"
  assert (str(c.scheduler_mode),str(c.start_mode),str(c.draw_mode))==("AUTO","AUTO","AUTO"),lvl
  assert (int(c.card_price),int(c.draw_interval_seconds),int(c.countdown_seconds))==(price,interval,countdown),lvl
  assert int(c.min_unique_players)>=2 and int(GameAutopilotConfigService.topic_id_for_level(lvl))==topic,lvl
 print("PASS: no active games; all three expected level configs and system actor ready")
PY

LIVE_BACKEND="$(docker inspect -f '{{.Config.Image}}' davarna-backend)"
LIVE_BOT="$(docker inspect -f '{{.Config.Image}}' davarna-bot)"
[[ "$(docker image inspect -f '{{.Id}}' "$LIVE_BACKEND")" == "$(docker inspect -f '{{.Image}}' davarna-backend)" ]] || die "backend tag drift"
[[ "$(docker image inspect -f '{{.Id}}' "$LIVE_BOT")" == "$(docker inspect -f '{{.Image}}' davarna-bot)" ]] || die "bot tag drift"
export TAMBOLA_V2_BACKEND_IMAGE="$LIVE_BACKEND"
export TAMBOLA_V2_BOT_IMAGE="$LIVE_BOT"
export DAVARNA_UX5_BACKEND_IMAGE="$LIVE_BACKEND"
export DAVARNA_UX5_BOT_IMAGE="$LIVE_BOT"
chain="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-backend)"
[[ "$chain" == /* ]] || die "missing Compose chain"
IFS=',' read -r -a FILES <<< "$chain"
args=()
for f in "${FILES[@]}"; do
 [[ "$f" == /* && -f "$f" && ! -L "$f" ]] || die "unsafe Compose config layer"
 args+=(-f "$f")
done
compose(){ (cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" "${args[@]}" "$@"); }
BACKUP="/root/davarna-v2-release-backups/low-autopilot-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p -m 0700 "$BACKUP"
overlay="$BACKUP/low-only-live.yml"
printf '%s\n' 'services:' '  backend:' '    environment:' \
 '      GAME_AUTO_DRAW_ENABLED: "true"' \
 '      GAME_AUTOPILOT_RUNTIME_ENABLED: "true"' >"$overlay"
COMMITTED=0
RECREATE=0
cleanup(){
 rc=$?
 trap - EXIT
 rm -f "$BACKUP/before-config.json" "$BACKUP/after-config.json"
 if (( rc != 0 && COMMITTED == 1 )); then
  echo "WARNING: activation incomplete; restoring runtime OFF, LOW-only state retained for safety" >&2
  if (( RECREATE == 1 )); then compose up -d --no-deps --force-recreate backend || true; fi
 fi
 exit "$rc"
}
trap cleanup EXIT

echo "===== ASSERT ONLY RUNTIME FLAG CHANGES ====="
compose config --format json >"$BACKUP/before-config.json"
compose -f "$overlay" config --format json >"$BACKUP/after-config.json"
python3 - "$BACKUP/before-config.json" "$BACKUP/after-config.json" <<'PY'
import json,sys
old=json.load(open(sys.argv[1]))
new=json.load(open(sys.argv[2]))
oa=old["services"]["backend"]["environment"]
na=new["services"]["backend"]["environment"]
if str(oa.get("GAME_AUTO_DRAW_ENABLED","")).lower() not in ("true","1"):
 raise SystemExit("BLOCKER: draw worker not enabled in base Compose")
if str(oa.get("GAME_AUTOPILOT_RUNTIME_ENABLED","")).lower() not in ("false","0"):
 raise SystemExit("BLOCKER: autopilot already on")
if str(na.get("GAME_AUTO_DRAW_ENABLED","")).lower()!="true" or str(na.get("GAME_AUTOPILOT_RUNTIME_ENABLED","")).lower()!="true":
 raise SystemExit("BLOCKER: override not applied")
na["GAME_AUTOPILOT_RUNTIME_ENABLED"]=oa["GAME_AUTOPILOT_RUNTIME_ENABLED"]
if old!=new: raise SystemExit("BLOCKER: unexpected Compose changes besides autopilot flag")
print("PASS: only autopilot flag would change")
PY
rm -f "$BACKUP/before-config.json" "$BACKUP/after-config.json"

echo "===== SAVE CONFIG SNAPSHOT; DISABLE MEDIUM/HIGH ====="
docker exec -i davarna-backend python - <<'PY'
from sqlalchemy import select
from app.core.db import SessionLocal
from app.models.game_autopilot import GameAutopilotConfig
from app.models.game import Game
with SessionLocal() as db:
 rows=db.execute(select(GameAutopilotConfig).where(
  GameAutopilotConfig.level.in_(("LOW","MEDIUM","HIGH"))
 ).order_by(GameAutopilotConfig.level).with_for_update()).scalars().all()
 assert len(rows)==3
 active=db.execute(select(Game.id).where(Game.status.in_(("LOBBY","RUNNING")))).scalars().all()
 assert not active,f"BLOCKER: new active game {active}"
 assert all(int(x.enabled)==1 for x in rows),"BLOCKER: enabled flag drift"
 for row in rows:
  if row.level in ("MEDIUM","HIGH"):row.enabled=0
 db.flush()
 assert {(str(x.level),int(x.enabled)) for x in rows}=={("LOW",1),("MEDIUM",0),("HIGH",0)}
 db.commit()
 print("PASS: LOW enabled; MEDIUM and HIGH disabled atomically")
PY
COMMITTED=1
echo "===== START LOW-ONLY AUTOPILOT WORKER ====="
RECREATE=1
compose -f "$overlay" up -d --no-deps --force-recreate backend
healthy=0
for _ in $(seq 1 45); do
 if [[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend)" == healthy ]]; then healthy=1;break;fi
 sleep 2
done
[[ "$healthy" == 1 ]] || die "backend unhealthy, reverted to autopilot OFF"
docker exec davarna-backend python -c 'from app.core import config as c;assert c.GAME_AUTO_DRAW_ENABLED and c.GAME_AUTOPILOT_RUNTIME_ENABLED;print("PASS: both game workers ON")'
echo "===== CONFIRM ONLY LOW SYSTEM GAME CREATED ====="
created=0
for _ in $(seq 1 15); do
 if docker exec -i davarna-backend python - <<'PY'
from sqlalchemy import select
from app.core.db import SessionLocal
from app.models.game import Game
from app.models.game_autopilot import GameAutopilotConfig
with SessionLocal() as db:
 assert int(db.get(GameAutopilotConfig,"LOW").enabled)==1
 assert int(db.get(GameAutopilotConfig,"MEDIUM").enabled)==0
 assert int(db.get(GameAutopilotConfig,"HIGH").enabled)==0
 active=db.execute(select(Game).where(Game.status.in_(("LOBBY","RUNNING")))).scalars().all()
 assert active,"no game created yet"
 assert len(active)==1,f"unexpected active game count {len(active)}"
 g=active[0]
 assert (str(g.game_level),str(g.execution_source),str(g.draw_mode),int(g.tg_topic_id or 0),int(g.card_price))==("LOW","SYSTEM","AUTO",6,5000),(g.id,g.game_level,g.execution_source)
 print(f"PASS: SYSTEM LOW game #{g.id} {g.status}, in Telegram topic 6; no MEDIUM/HIGH active")
PY
 then created=1;break;fi
 sleep 2
done
[[ "$created" == 1 ]] || die "LOW system game did not appear or mismatched"
RECREATE=0
echo "===== LOW AUTOPILOT ACTIVATION PASS ====="
echo "BACKUP=$BACKUP"
echo "Production LOW creates games automatically; MEDIUM/HIGH stay disabled."
