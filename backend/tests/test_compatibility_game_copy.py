import pytest
from app.utils.messages import format_game_summary, stored_rule
from app.utils.bingo_v2 import generate_tambola_card
from app.utils.card_render import render_card_text

@pytest.mark.parametrize("rule,layout", [("LINE",2),("FULL_CARD",2),("LEGACY",1)])
@pytest.mark.parametrize("status", ["LOBBY","RUNNING","ENDED"])
def test_compatibility_messages_match_stored_rule_and_status(rule,layout,status):
    text = format_game_summary(dict(game_id=91,status=status,game_rule=rule,card_layout_version=layout,
                                   card_price=1000,prize_pool=10000,col_prize_amount=3000,row_prize_amount=7000))
    assert "Game is" not in text
    assert "تومان" in text
    if status == "ENDED": assert "پایان‌یافته" in text
    if rule == "FULL_CARD":
        assert "جایزه تورنا" not in text
        assert "۱۵ عدد" in text

def test_renderer_preserves_blank_columns_and_marks():
    nums = generate_tambola_card("integration-only")
    seen = [n for n in nums if n][:3]
    grid = render_card_text(nums, seen, "LINE", 2).splitlines()[:3]
    for row, offset in zip(grid,range(0,27,9)):
        for col,n in enumerate(nums[offset:offset+9]):
            cell=row[col*5:col*5+4]
            assert cell == (" -- " if not n else f"[{n:02d}]" if n in seen else f" {n:02d} ")
    assert "ناسازگار" in render_card_text(nums,seen,"LEGACY",2)
    assert stored_rule("LINE",1) == "UNKNOWN"
