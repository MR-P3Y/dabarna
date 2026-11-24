import time
import pytest
from fastapi import HTTPException
from app.core import mini_security as security
from app.utils.tg_webapp import verify_init_data, TelegramInitDataError

@pytest.mark.parametrize("token", ["سلام.signature", "payload.سلام", "é.x", "x.é"])
def test_non_ascii_bearer_is_401_not_server_error(token):
    with pytest.raises(HTTPException) as error:
        security.verify_session_token(token)
    assert error.value.status_code == 401

@pytest.mark.parametrize("value", ["سلام", "é", "z" * 64, "a" * 63])
def test_invalid_telegram_hash_is_validation_error(value):
    with pytest.raises(TelegramInitDataError):
        verify_init_data("auth_date=123&hash=" + value, "offline-token")

def test_session_expires_at_expiry_instant(monkeypatch):
    monkeypatch.setattr(security.time, "time", lambda: 1000)
    token, expires = security.issue_session_token(1, 60)
    monkeypatch.setattr(security.time, "time", lambda: expires)
    with pytest.raises(HTTPException) as error:
        security.verify_session_token(token)
    assert error.value.status_code == 401


def test_valid_session_and_tamper(monkeypatch):
    monkeypatch.setattr(security.time, "time", lambda: 1000)
    token, _ = security.issue_session_token(42, 60)
    assert security.verify_session_token(token) == 42
    with pytest.raises(HTTPException):
        security.verify_session_token(token[:-1] + ("A" if token[-1] != "A" else "B"))

@pytest.mark.parametrize("payload", [[], {"uid": True, "exp": 2000}, {"uid": 1, "exp": True}])
def test_signed_invalid_payload_rejected(payload, monkeypatch):
    import json
    monkeypatch.setattr(security.time, "time", lambda: 1000)
    body = security._b64url_encode(json.dumps(payload).encode())
    with pytest.raises(HTTPException) as error:
        security.verify_session_token(body + "." + security._token_sign(body))
    assert error.value.status_code == 401
