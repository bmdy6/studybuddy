import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.config import SecretSettings, settings
from app.deps import require_internal_token
from app.main import app
from fastapi.testclient import TestClient


def test_wechat_is_optional_by_default(monkeypatch):
    for key in list(__import__('os').environ):
        if key.startswith('WECHAT_'):
            monkeypatch.delenv(key)
    value = SecretSettings(_env_file=None)
    assert value.WECHAT_ENABLED is False
    assert value.WECHAT_BOT_INTERNAL_TOKEN.get_secret_value() == ''


def test_enabling_wechat_requires_configuration(monkeypatch):
    for key in list(__import__('os').environ):
        if key.startswith('WECHAT_'):
            monkeypatch.delenv(key)
    with pytest.raises(ValidationError, match='WECHAT_BOT_SERVICE_URL'):
        SecretSettings(_env_file=None, WECHAT_ENABLED=True)


def test_empty_internal_token_cannot_authorize_anonymous_request(monkeypatch):
    monkeypatch.setattr(settings, 'WECHAT_BOT_INTERNAL_TOKEN', '')
    request = Request({'type': 'http', 'headers': []})
    with pytest.raises(HTTPException) as caught:
        require_internal_token(request)
    assert caught.value.status_code == 403


def test_disabled_wechat_routes_fail_before_accessing_user_data(monkeypatch):
    monkeypatch.setattr(settings, 'WECHAT_ENABLED', False)
    with TestClient(app) as client:
        response = client.get('/api/channels/wechat/account')
    assert response.status_code == 503
    assert response.json()['detail'] == '此实例未启用微信集成'
