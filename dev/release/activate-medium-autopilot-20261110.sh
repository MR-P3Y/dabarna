#!/usr/bin/env bash
# Controlled one-time MEDIUM lane enablement on live NODE2.
# No direct purchases, awards, refund, or edits of existing games.
set -Eeuo pipefail
umask 077
die(){ echo "BLOCKER: $*" >&2; exit 2; }
ROOT=/opt/davarna-v2
REF="${DAVARNA_MEDIUM_AUTOPILOT_REF:?pinned commit required}"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || die "bad SHA"
[[ "${DAVARNA_MEDIUM_AUTOPILOT_APPROVAL:-}" == "ENABLE_MEDIUM_KEEP_HIGH_OFF" ]] || die "approval missing"
[[ "$(id -u)" == "0" ]] || die "root required"
cd "$ROOT"
git cat-file -e "$REF^{commit}" || die "commit not fetched"
exec 9>/run/davarna-auto-draw-recovery.lock
flock -n 9 || die "another release is running"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis;do
 [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == "healthy" ]] || die "unhealthy: $c"
done
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "davarna-backend:auto-clock-92471d0132b4" ]] || die "live backend image changed"
[[ "$(docker exec davarna-backend python -c 'from app.core import config as c;print(int(c.GAME_AUTO_DRAW_ENABLED),int(c.GAME_AUTOPILOT_RUNTIME_ENABLED))')" == "1 1" ]] || die "both workers must already be enabled"
echo "===== MEDIUM ACTIVATION PRECHECK ====="
docker exec -i davarna-backend python - <<'PY'
from decimal import Decimal
from sqlalchemy import select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game
from app.models.game_autopilot import GameAutopilotConfig
from app.models.user import User
from app.services.game_autopilot_config_service import GameAutopilotConfigService as S
assert int(cfg.USER_FORUM_CHAT_ID or cfg.DEFAULT_TG_GROUP_ID or 0)==-1003614031001,"group drift"
assert cfg.GAME_AUTOPILOT_SYSTEM_USER_ID
with SessionLocal() as db:
 assert db.get(User,int(cfg.GAME_AUTOPILOT_SYSTEM_USER_ID)),"system actor missing"
 rows={lvl:db.get(GameAutopilotConfig,lvl) for lvl in ("LOW","MEDIUM","HIGH")}
 assert all(rows.values()),"missing config"
 assert [int(rows[x].enabled) for x in ("LOW","MEDIUM","HIGH")]==[1,0,0],"lane enablement drift"
 expected={"LOW":(5000,5,60,6),"MEDIUM":(3000,10,30,8),"HIGH":(20000,15,30,10)}
 for lvl,(price,interval,countdown,topic) in expected.items():
  c=rows[lvl]
  assert (str(c.scheduler_mode),str(c.start_mode),str(c.draw_mode))==("AUTO","AUTO","AUTO"),lvl
  assert (int(c.card_price),int(c.draw_interval_seconds),int(c.countdown_seconds),int(S.topic_id_for_level(lvl)))==(price,interval,countdown,topic),lvl
  assert int(c.min_unique_players)>=2,lvl
  assert Decimal(str(c.commission_rate))==Decimal("0.1000"),lvl
 active=db.execute(select(Game).where(Game.status.in_(("LOBBY","RUNNING")))).scalars().all()
 assert all(str(g.game_level)=="LOW" and int(g.tg_topic_id)==6 for g in active),f"other active games present: {[(x.id,x.game_level,x.tg_topic_id) for x in active]}"
 assert len(active)<=1,"more than one active LOW game"
 print("PASS: runtime ready, exact config; active LOW unaffected; no MEDIUM/HIGH game")
PY

# Only one DB config flag changes; no service restart and no schema change.
# The live worker will detect the new lane at its next tick.
echo "===== ENABLE MEDIUM ONLY WITH DB LOCK ====="
docker exec -i davarna-backend python - <<'PY'
from decimal import Decimal
from sqlalchemy import select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game
from app.models.game_autopilot import GameAutopilotConfig
from app.services.game_autopilot_config_service import GameAutopilotConfigService as S
assert cfg.GAME_AUTO_DRAW_ENABLED and cfg.GAME_AUTOPILOT_RUNTIME_ENABLED
with SessionLocal() as db:
 rows=db.execute(select(GameAutopilotConfig).where(
  GameAutopilotConfig.level.in_(("LOW","MEDIUM","HIGH"))
 ).order_by(GameAutopilotConfig.level).with_for_update()).scalars().all()
 by={str(x.level):x for x in rows}
 assert set(by)=={"LOW","MEDIUM","HIGH"}
 assert [int(by[x].enabled) for x in ("LOW","MEDIUM","HIGH")]==[1,0,0],"BLOCKER: status changed"
 m=by["MEDIUM"]
 assert (str(m.scheduler_mode),str(m.start_mode),str(m.draw_mode))==("AUTO","AUTO","AUTO")
 assert (int(m.card_price),int(m.draw_interval_seconds),int(m.countdown_seconds),int(S.topic_id_for_level("MEDIUM")))==(3000,10,30,8)
 assert int(m.min_unique_players)>=2 and Decimal(str(m.commission_rate))==Decimal("0.1000")
 active=db.execute(select(Game).where(Game.status.in_(("LOBBY","RUNNING")))).scalars().all()
 assert all(str(x.game_level)=="LOW" and int(x.tg_topic_id)==6 for x in active),"BLOCKER: other game started"
 m.enabled=1
 db.commit()
 print("PASS: MEDIUM enabled atomically; HIGH disabled; LOW unchanged")
PY

echo "===== VERIFY SYSTEM MEDIUM APPEARS; STOP NEW MEDIUM CREATION ON FAILURE ====="
verified=0
for _ in $(seq 1 20);do
 if docker exec -i davarna-backend python - <<'PY'
from sqlalchemy import select
from app.core.db import SessionLocal
from app.models.game import Game,GameAutoDraw
from app.models.game_autopilot import GameAutopilotConfig
from app.core import config as cfg
with SessionLocal() as db:
 assert cfg.GAME_AUTO_DRAW_ENABLED and cfg.GAME_AUTOPILOT_RUNTIME_ENABLED
 assert [int(db.get(GameAutopilotConfig,x).enabled) for x in ("LOW","MEDIUM","HIGH")]==[1,1,0]
 games=db.execute(select(Game).where(Game.status.in_(("LOBBY","RUNNING")))).scalars().all()
 assert not any(str(x.game_level)=="HIGH" or int(x.tg_topic_id or 0)==10 for x in games),"HIGH active"
 medium=[x for x in games if str(x.game_level)=="MEDIUM" or int(x.tg_topic_id or 0)==8]
 assert len(medium)==1,f"expected one active MEDIUM game, found {len(medium)}"
 g=medium[0]; auto=db.get(GameAutoDraw,int(g.id))
 assert (str(g.game_level),str(g.execution_source),str(g.draw_mode),int(g.tg_topic_id),int(g.card_price))==("MEDIUM","SYSTEM","AUTO",8,3000),"MEDIUM mismatch"
 assert auto and str(auto.status) in ("ARMED","RUNNING","PAUSED"),"auto draw not armed"
 print(f"PASS: MEDIUM SYSTEM game #{g.id} status={g.status} auto={auto.status} topic=8; HIGH remains off")
PY
 then verified=1;break;fi
 sleep 2
done
if [[ "$verified" != "1" ]];then
 echo "WARNING: verification failed: disable future MEDIUM creation, retain any existing game for separate review" >&2
 docker exec -i davarna-backend python - <<'PY'
from app.core.db import SessionLocal
from app.models.game_autopilot import GameAutopilotConfig
with SessionLocal() as db:
 row=db.get(GameAutopilotConfig,"MEDIUM",with_for_update=True)
 if row and int(row.enabled)==1:
  row.enabled=0
  db.commit()
 print("MEDIUM scheduler disabled; NO live game/refund/payout was modified.")
PY
 exit 2
fi
echo "===== MEDIUM AUTOPILOT ENABLEMENT PASS ====="
echo "LOW and MEDIUM enabled, HIGH disabled. Audit first MEDIUM game's lifecycle and finances before HIGH."
