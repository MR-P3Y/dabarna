import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
import pytest

from bot.routers.cards import _is_ended_game_expired
from bot.workers import notifier


def test_archive_uses_end_time_even_when_purchase_is_old():
    now = datetime(2026, 11, 11, tzinfo=timezone.utc)
    game = dict(status="ENDED", created_at=(now-timedelta(days=10)).isoformat(),
                ended_at=(now-timedelta(hours=1)).isoformat())
    assert not _is_ended_game_expired(game, now=now)
    game["ended_at"] = (now-timedelta(hours=48)).isoformat()
    assert _is_ended_game_expired(game, now=now)
    game["ended_at"] = None
    assert not _is_ended_game_expired(game, now=now)
    game["status"] = "RUNNING"
    assert not _is_ended_game_expired(game, now=now)


@pytest.mark.parametrize("rule,layout,kind", [("LINE",2,"PRIZE_COL"),("LINE",2,"PRIZE_ROW"),
                                          ("FULL_CARD",2,"PRIZE_ROW"),("LEGACY",1,"PRIZE_ROW")])
def test_multiple_winners_receive_only_verified_shares(rule, layout, kind):
    bucket = "col" if kind == "PRIZE_COL" else "row"
    game = dict(game_rule=rule, card_layout_version=layout,
                **{f"{bucket}_winner_card_ids":[1,2,3],f"{bucket}_winner_user_ids":[10,11,10],
                   f"{bucket}_winner_tg_user_ids":[100,110,100]})
    payload = dict(amount_total=1000, winner_users=[
        dict(card_id=3,user_id=10,tg_user_id=100,amount=300),
        dict(card_id=1,user_id=10,tg_user_id=100,amount=400),
        dict(card_id=2,user_id=11,tg_user_id=110,amount=300)])
    async def run():
        queue = asyncio.Queue()
        with patch.object(notifier.settings,"ADMIN_TOPIC_ENABLE_DM_FALLBACK",False):
            await notifier._queue_prize_notifications(queue,None,game_id=91,report={"game":game},
                                                       kind=kind,event={"payload_json":payload})
        jobs = [queue.get_nowait() for _ in range(queue.qsize())]
        return {j.user_id:j.text for j in jobs}
    actual = asyncio.run(run())
    assert "700 تومان" in actual[100] and "300 تومان" in actual[110]
    assert "1,000" not in actual[100]
    payload["winner_users"][0]["amount"] = None
    actual = asyncio.run(run())
    assert "مبلغ قابل تأیید نیست" in actual[100]
    assert "300 تومان" in actual[110]
    payload["winner_users"] = []
    actual = asyncio.run(run())
    assert all("مبلغ قابل تأیید نیست" in text for text in actual.values())


def test_zero_is_valid_and_wrong_owner_or_total_is_rejected():
    game = dict(row_winner_card_ids=[1],row_winner_user_ids=[10],row_winner_tg_user_ids=[100])
    row = dict(card_id=1,user_id=10,tg_user_id=100,amount=0)
    payload = dict(amount_total=0,winner_users=[row])
    assert notifier._personal_amount(notifier._winner_shares(game,payload,"row")[100]) == "0 تومان"
    row["tg_user_id"] = 101
    assert notifier._winner_shares(game,payload,"row")[100] == [(1,None)]
    row["tg_user_id"] = 100
    payload["amount_total"] = 1
    assert notifier._winner_shares(game,payload,"row")[100] == [(1,None)]
