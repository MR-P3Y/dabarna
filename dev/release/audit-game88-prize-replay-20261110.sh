#!/usr/bin/env bash
# Audit actual game-88 prize-credit ownership READ ONLY and replay the exact
# PRIZE_ROW/PRIZE_COL award keys against disposable SQLite, never Production.
set -Eeuo pipefail
umask 077
die(){ echo "BLOCKER: $*" >&2; exit 2; }
ROOT=/opt/davarna-v2
REF="${DAVARNA_GAME88_AUDIT_REF:?pinned SHA required}"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || die "invalid ref"
cd "$ROOT"
git cat-file -e "$REF^{commit}" || die "pinned ref unavailable"
[[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend)" == "healthy" ]] || die "backend unhealthy"
exec 9>/run/davarna-game88-financial-audit.lock
flock -n 9 || die "audit already active"

echo "===== PRODUCTION READ-ONLY AWARD OWNERSHIP AND EXACT KEYS ====="
docker exec -i davarna-backend python - <<'PY'
from sqlalchemy import select,func
from app.core.db import SessionLocal
from app.models.game import Game,GameCard
from app.models.wallet import Wallet,WalletTx

with SessionLocal() as db:
 g=db.get(Game,88)
 assert g and str(g.status)=="ENDED","BLOCKER: game state differs"
 state=g.payout_state_json
 assert isinstance(state,dict) and int(state.get("col_paid",0))==1 and int(state.get("row_paid",0))==1
 expect={}
 for stage in ("col","row"):
  item=state.get(stage)
  assert isinstance(item,dict),f"BLOCKER: {stage} payload missing"
  card_ids=item.get("winner_card_ids",[])
  user_ids=item.get("winner_user_ids",[])
  amounts=item.get("amounts_by_card",[])
  assert isinstance(card_ids,list) and len(card_ids)==len(user_ids)==len(amounts)>0
  assert sum(int(x) for x in amounts)==int(item["amount_total"])
  for cid,uid,amount in zip(card_ids,user_ids,amounts):
   card=db.get(GameCard,int(cid))
   assert card and int(card.game_id)==88 and int(card.user_id)==int(uid),f"BLOCKER: winner/card ownership {cid}"
   key=f"PRIZE_{stage.upper()}:game:88:card:{cid}"
   assert key not in expect,f"BLOCKER: duplicate expected key {key}"
   expect[key]=(int(uid),int(amount),"PRIZE_"+stage.upper(),int(cid))
 actual=db.execute(select(WalletTx,Wallet.user_id).join(Wallet,Wallet.id==WalletTx.wallet_id).where(
    WalletTx.ref_type=="GAME",WalletTx.ref_id==88,
    WalletTx.direction=="CREDIT",WalletTx.reason.in_(("PRIZE_ROW","PRIZE_COL"))
 )).all()
 assert len(actual)==len(expect),f"BLOCKER: award tx count {len(actual)} vs expected {len(expect)}"
 seen=set()
 for tx,uid in actual:
  key=str(tx.idempotency_key)
  assert key in expect,f"BLOCKER: unexpected award key {key}"
  assert key not in seen,f"BLOCKER: repeated award key {key}"
  seen.add(key)
  expected_uid,amount,reason,card_id=expect[key]
  assert int(uid)==expected_uid,f"BLOCKER: wrong prize wallet owner on tx {tx.id}"
  assert int(tx.amount)==amount and str(tx.reason)==reason,f"BLOCKER: incorrect prize amount on tx {tx.id}"
  assert (str(tx.direction),str(tx.ref_type),int(tx.ref_id))==("CREDIT","GAME",88)
  print(f"PASS: prize tx={tx.id} user={uid} card={card_id} amount={amount} reason={reason}; exact idempotency key")
 assert seen==set(expect)
 assert sum(int(tx.amount) for tx,_ in actual)==int(g.prize_pool)
 assert len(actual)==2 and {int(tx.id) for tx,_ in actual}=={354,355}
 print("PASS: GAME 88 WINNER-WALLET OWNERSHIP, AMOUNTS, KEYS AND POOL MATCH")
 print("NOTE: Read-only reconciliation; it does not re-run game payout")
PY

echo "===== DISPOSABLE PAYOUT REPLAY REGRESSION ====="
LIVE_IMAGE="$(docker inspect -f '{{.Config.Image}}' davarna-backend)"
[[ "$(docker image inspect -f '{{.Id}}' "$LIVE_IMAGE")" == "$(docker inspect -f '{{.Image}}' davarna-backend)" ]] || die "deployed image mismatch"
WORK="$(mktemp -d /tmp/davarna-prize-replay.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git show "$REF:backend/tests/test_game_prize_replay_isolated_20261110.py" > "$WORK/test_game_prize_replay_isolated_20261110.py"
python3 - "$WORK/test_game_prize_replay_isolated_20261110.py" <<'PY'
import ast,sys
ast.parse(open(sys.argv[1]).read())
print("PASS: isolated replay test syntax")
PY
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
 --tmpfs /tmp:rw,nosuid,size=128m \
 -e DATABASE_URL=sqlite+pysqlite:///:memory: \
 -e REDIS_URL=redis://127.0.0.1:6379/15 \
 -e RECEIPTS_DIR=/tmp/receipts \
 -e GAME_AUTO_DRAW_ENABLED=false -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
 -v "$WORK:/app/tests:ro" --entrypoint python "$LIVE_IMAGE" \
 -m unittest discover -s /app/tests -p test_game_prize_replay_isolated_20261110.py -v
echo "===== GAME 88 AWARDS AND REPLAY AUDIT PASS ====="
echo "SOURCE=$REF"
echo "No production wallets, games, or flags modified."
