from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.services.finance_service import normalize_withdraw_rejection_reason


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MINI_DIR = BACKEND_ROOT / "app" / "static" / "mini"


def test_withdraw_rejection_reason_is_trimmed_and_required() -> None:
    assert normalize_withdraw_rejection_reason("  اطلاعات بانکی نامعتبر است.  ") == "اطلاعات بانکی نامعتبر است."

    for bad in ("", " ", "ab", "  a  "):
        try:
            normalize_withdraw_rejection_reason(bad)
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError(f"expected rejection for {bad!r}")


def test_withdraw_rejection_reason_max_length() -> None:
    assert normalize_withdraw_rejection_reason("x" * 500) == "x" * 500
    try:
        normalize_withdraw_rejection_reason("x" * 501)
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("expected rejection for >500 characters")


def test_mini_reject_modal_and_cache_tokens_exist() -> None:
    index = (MINI_DIR / "index.html").read_text(encoding="utf-8")
    app = (MINI_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="withdrawRejectModal"' in index
    assert 'id="withdrawRejectReasonInput"' in index
    assert 'id="withdrawRejectSubmitBtn"' in index
    assert "./app.js?v=mini-withdraw-reject-20261009-1" in index
    assert "./styles.css?v=mini-withdraw-reject-20261009-1" in index

    assert "openWithdrawRejectModal(id, item)" in app
    assert "body: { reason: cleanReason }" in app
    assert 'body: { reason: "رد توسط ادمین" }' not in app


def test_withdraw_rejection_is_persisted_in_model_and_migration() -> None:
    model = (BACKEND_ROOT / "app" / "models" / "finance.py").read_text(encoding="utf-8")
    migration = (
        BACKEND_ROOT
        / "alembic"
        / "versions"
        / "20261009_0008_withdraw_rejection_reason.py"
    ).read_text(encoding="utf-8")

    assert "rejection_reason" in model
    assert 'op.add_column(' in migration
    assert '"withdraw_requests"' in migration
    assert '"rejection_reason"' in migration
