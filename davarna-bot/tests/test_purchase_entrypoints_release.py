from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from bot.routers import purchase
from bot.routers.game import _build_game_flow_body

class PurchaseEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_select_quantity_confirm_for_all_stored_rules(self):
        for rule,layout in (("LINE",2),("FULL_CARD",2),("LEGACY",1)):
            with self.subTest(rule=rule):
                state=FSMContext(MemoryStorage(),StorageKey(bot_id=1,chat_id=10,user_id=10))
                cq=SimpleNamespace(data="buy:game:91",bot=None,answer=AsyncMock(),
                                   message=SimpleNamespace(edit_text=AsyncMock()))
                game=dict(id=91,status="LOBBY",game_level="LOW",game_rule=rule,
                          card_layout_version=layout,card_price=5000,draw_mode="MANUAL")
                api=SimpleNamespace(bot_list_games=AsyncMock(return_value={"items":[game]}),
                    bot_get_wallet=AsyncMock(return_value={"balance":20000}),
                    bot_purchase_cards=AsyncMock(return_value=dict(game_id=91,order_id=1,cards_created=2,
                        total_amount=10000,wallet_balance=10000,wallet_tx_id=1)))
                with patch.object(purchase,"configured_join_group_id",return_value=None),patch.object(purchase,"is_subscribed",return_value=False):
                    await purchase.buy_select_game(cq,state,api,10)
                    text=cq.message.edit_text.call_args.args[0]
                    self.assertIn("5,000",text)
                    self.assertIn("تومان",text)
                    cq.data="buy:qty:91:2"
                    await purchase.buy_select_qty(cq,state,api,10)
                    self.assertIn("10,000",cq.message.edit_text.call_args.args[0])
                    cq.data="buy:confirm:91:2"
                    await purchase.buy_confirm(cq,state,api,10)
                    api.bot_purchase_cards.assert_awaited_once()
                    self.assertEqual(api.bot_purchase_cards.call_args.kwargs["quantity"],2)
                    self.assertIn("موفقیت",cq.message.edit_text.call_args.args[0])

    async def test_unknown_pair_does_not_reach_purchase(self):
        cq=SimpleNamespace(data="buy:game:91",answer=AsyncMock(),message=SimpleNamespace(edit_text=AsyncMock()))
        api=SimpleNamespace(bot_list_games=AsyncMock(return_value={"items":[dict(id=91,game_rule="LINE",card_layout_version=1)]}))
        state=FSMContext(MemoryStorage(),StorageKey(bot_id=1,chat_id=10,user_id=10))
        await purchase.buy_select_game(cq,state,api,10)
        cq.message.edit_text.assert_not_awaited()
        self.assertIsNone(await state.get_state())

    def test_game_details_all_states_and_rules(self):
        for rule,layout in (("LINE",2),("FULL_CARD",2),("LEGACY",1)):
            for status in ("LOBBY","RUNNING","ENDED"):
                with self.subTest(rule=rule,status=status):
                    body=_build_game_flow_body(91,dict(game_rule=rule,card_layout_version=layout,status=status,
                        card_price=5000,prize_pool=9000,sold_amount=10000,commission_rate=.1,
                        execution_source="SYSTEM",draw_mode="AUTO",col_paid=0,row_paid=0))
                    self.assertIn("هنوز ثبت نشده",body)
                    self.assertIn("تومان",body)
                    self.assertNotIn("❌",body)
                    if rule=="FULL_CARD":self.assertNotIn("تورنا: هنوز ثبت نشده",body)

