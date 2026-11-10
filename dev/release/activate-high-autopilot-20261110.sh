#!/usr/bin/env bash
# One-time HIGH autopilot enablement; no payment or game-state mutation.
set -Eeuo pipefail
umask 077
die(){ echo "BLOCKER: $*" >&2; exit 2; }
ROOT=/opt/davarna-v2
REF="${DAVARNA_HIGH_AUTOPILOT_REF:?pinned commit required}"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || die "bad pinned SHA"
[[ "${DAVARNA_HIGH_AUTOPILOT_APPROVAL:-}" == "ENABLE_HIGH_AFTER_MEDIUM_AUDIT" ]] || die "explicit approval missing"
[[ "$(id -u)" == "0" ]] || die "root required"
cd "$ROOT"
git cat-file -e "$REF^{commit}" || die "pinned ref unavailable"
exec 9>/run/davarna-auto-draw-recovery.lock
flock -n 9 || die "another release holds lock"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
 [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || die "unhealthy container: $c"
done
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == davarna-backend:auto-clock-92471d0132b4 ]] || die "backend image drift"
[[ "$(docker exec davarna-backend python -c 'from app.core import config as c;print(int(c.GAME_AUTO_DRAW_ENABLED),int(c.GAME_AUTOPILOT_RUNTIME_ENABLED))')" == "1 1" ]] || die "both workers must be ON"

echo "===== HIGH PRECHECK AND MEDIUM GAME 90 SETTLEMENT GUARD ====="
docker exec -i davarna-backend python - <<'PY'
from decimal import Decimal
from sqlalchemy import select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game,GameCard,GameAutoDraw
from app.models.game_autopilot import GameAutopilotConfig
from app.models.user import User
from app.models.wallet import WalletTx,Wallet
from app.services.game_autopilot_config_service import GameAutopilotConfigService as S
assert int(cfg.USER_FORUM_CHAT_ID or cfg.DEFAULT_TG_GROUP_ID or 0)==-1003614031001,"Telegram group drift"
assert cfg.GAME_AUTOPILOT_SYSTEM_USER_ID is not None
expected={"LOW":(5000,5,60,6),"MEDIUM":(3000,10,30,8),"HIGH":(20000,15,30,10)}
with SessionLocal() as db:
 assert db.get(User,int(cfg.GAME_AUTOPILOT_SYSTEM_USER_ID)),"system user missing"
 rows={level:db.get(GameAutopilotConfig,level) for level in expected}
 assert all(rows.values()),"missing lane config"
 assert [int(rows[x].enabled) for x in expected]==[1,1,0],"lane state changed"
 for level,(price,interval,countdown,topic) in expected.items():
  r=rows[level]
  assert (str(r.scheduler_mode),str(r.start_mode),str(r.draw_mode))==("AUTO","AUTO","AUTO"),level
  assert (int(r.card_price),int(r.draw_interval_seconds),int(r.countdown_seconds),int(S.topic_id_for_level(level)))==(price,interval,countdown,topic),level
  assert int(r.min_unique_players)>=2,level
  assert Decimal(str(r.commission_rate))==Decimal("0.1000"),level
 active=db.execute(select(Game).where(Game.status.in_(("LOBBY","RUNNING")))).scalars().all()
 assert all(str(g.game_level) in ("LOW","MEDIUM") and int(g.tg_topic_id)=={"LOW":6,"MEDIUM":8}[str(g.game_level)] for g in active),"unexpected active game"
 assert len([x for x in active if str(x.game_level)=="LOW"])<=1,"duplicate active LOW"
 assert len([x for x in active if str(x.game_level)=="MEDIUM"])<=1,"duplicate active MEDIUM"
 g=db.get(Game,90)
 assert g and str(g.status)=="ENDED" and int(g.sold_amount)==6000 and int(g.commission_amount)==600 and int(g.prize_pool)==5400,"MEDIUM game 90 financial drift"
 a=db.get(GameAutoDraw,90)
 assert a and str(a.status)=="STOPPED","MEDIUM draw not stopped"
 state=g.payout_state_json or {}
 assert int(state.get("col_paid",0))==1 and int(state.get("row_paid",0))==1
 expect={}
 for kind in ("col","row"):
  data=state[kind]
  assert not bool(data.get("absorbed_into_row",False)),kind
  ids=data.get("winner_card_ids",[])
  users=data.get("winner_user_ids",[])
  amounts=data.get("amounts_by_card",[])
  assert len(ids)==len(users)==len(amounts)>0
  assert sum(int(v) for v in amounts)==int(data["amount_total"])
  for cid,uid,amount in zip(ids,users,amounts):
   card=db.get(GameCard,int(cid))
   assert card and int(card.game_id)==90 and int(card.user_id)==int(uid)
   key=f"PRIZE_{kind.upper()}:game:90:card:{cid}"
   assert key not in expect
   expect[key]=(int(uid),int(amount),"PRIZE_"+kind.upper())
 prize=db.execute(select(WalletTx,Wallet.user_id).join(Wallet,Wallet.id==WalletTx.wallet_id).where(
  WalletTx.ref_type=="GAME",WalletTx.ref_id==90,WalletTx.direction=="CREDIT",
  WalletTx.reason.in_(("PRIZE_COL","PRIZE_ROW"))
 )).all()
 assert len(prize)==2 and len(expect)==2,"wrong prize transaction count"
 assert {int(t.id) for t,_ in prize}=={364,367},"MEDIUM wallet tx drift"
 assert {str(t.idempotency_key) for t,_ in prize}==set(expect),"idempotency key drift"
 assert all((int(uid),int(tx.amount),str(tx.reason))==expect[str(tx.idempotency_key)] for tx,uid in prize),"MEDIUM prize owner or amount drift"
 assert sum(int(t.amount) for t,_ in prize)==5400
 print("PASS: MEDIUM #90 settlement 5400; exact wallet owners and keys")
 print("PASS: existing LOW/MEDIUM lanes safe; HIGH presently disabled")
PY

echo "===== ENABLE HIGH CONFIG ONLY; ATOMIC LOCK ====="
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
 items=db.execute(select(GameAutopilotConfig).where(
  GameAutopilotConfig.level.in_(("LOW","MEDIUM","HIGH"))
 ).order_by(GameAutopilotConfig.level).with_for_update()).scalars().all()
 by={str(x.level):x for x in items}
 assert set(by)=={"LOW","MEDIUM","HIGH"}
 assert [int(by[x].enabled) for x in ("LOW","MEDIUM","HIGH")]==[1,1,0],"lane state drift"
 h=by["HIGH"]
 assert (str(h.scheduler_mode),str(h.start_mode),str(h.draw_mode))==("AUTO","AUTO","AUTO")
 assert (int(h.card_price),int(h.draw_interval_seconds),int(h.countdown_seconds),int(S.topic_id_for_level("HIGH")))==(20000,15,30,10)
 assert int(h.min_unique_players)>=2 and Decimal(str(h.commission_rate))==Decimal("0.1000")
 active=db.execute(select(Game).where(Game.status.in_(("LOBBY","RUNNING")))).scalars().all()
 assert all(str(g.game_level) in ("LOW","MEDIUM") and int(g.tg_topic_id)=={"LOW":6,"MEDIUM":8}[str(g.game_level)] for g in active),"new unexpected active game"
 assert sum(str(g.game_level)=="LOW" for g in active)<=1
 assert sum(str(g.game_level)=="MEDIUM" for g in active)<=1
 h.enabled=1
 db.commit()
 print("PASS: only HIGH.enabled changed from 0 to 1; LOW/MEDIUM still enabled")
PY

echo "===== VERIFY ONE HIGH SYSTEM AUTO GAME CREATED ====="
verified=0
for _ in $(seq 1 20); do
 if docker exec -i davarna-backend python - <<'PY'
from sqlalchemy import select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game,GameAutoDraw
from app.models.game_autopilot import GameAutopilotConfig
assert cfg.GAME_AUTO_DRAW_ENABLED and cfg.GAME_AUTOPILOT_RUNTIME_ENABLED
with SessionLocal() as db:
 assert [int(db.get(GameAutopilotConfig,x).enabled) for x in ("LOW","MEDIUM","HIGH")]==[1,1,1],"lane config drift"
 active=db.execute(select(Game).where(Game.status.in_(("LOBBY","RUNNING")))).scalars().all()
 high=[g for g in active if str(g.game_level)=="HIGH" or int(g.tg_topic_id or 0)==10]
 assert len(high)==1,f"expected one active HIGH round; found {len(high)}"
 g=high[0]
 assert (str(g.game_level),str(g.execution_source),str(g.draw_mode),int(g.tg_topic_id),int(g.card_price))==("HIGH","SYSTEM","AUTO",10,20000),"HIGH game mismatch"
 a=db.get(GameAutoDraw,int(g.id))
 assert a and str(a.status) in ("ARMED","RUNNING","PAUSED"),"draw not armed"
 assert all(str(x.game_level) in ("LOW","MEDIUM","HIGH") for x in active),"unknown game lane"
 assert all(sum(str(x.game_level)==lvl for x in active)<=1 for lvl in ("LOW","MEDIUM","HIGH")),"duplicate active lane"
 print(f"PASS: HIGH SYSTEM game #{g.id}, {g.status}, topic 10, auto={a.status}")
 print("PASS: LOW and MEDIUM preserved; all 3 lanes configured ON")
PY
 then verified=1;break;fi
 sleep 2
done
if [[ "$verified" != 1 ]]; then
 echo "WARNING: verification failed. Disabling future HIGH scheduling only; any existing HIGH game remains untouched." >&2
 docker exec -i davarna-backend python - <<'PY'
from app.core.db import SessionLocal
from app.models.game_autopilot import GameAutopilotConfig
with SessionLocal() as db:
 h=db.get(GameAutopilotConfig,"HIGH",with_for_update=True)
 if h and int(h.enabled)==1:
  h.enabled=0
  db.commit()
 print("HIGH scheduler OFF; live game and wallet records untouched.")
PY
 exit 2
fi
echo "===== HIGH AUTOPILOT ENABLEMENT PASS ====="
echo "Audit first HIGH round to END and verify winner wallet credits before treating HIGH as fully tested."
