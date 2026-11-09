"""安全工具单测：hash/verify 密码、JWT 编解码。"""

from datetime import datetime, timezone

import jwt
import pytest

from app.config import settings
from app.utils.security import create_access_token, decode_access_token, hash_password, verify_password


def test_hash_and_verify_password():
    hashed = hash_password("secret123")
    assert hashed != "secret123"
    assert verify_password("secret123", hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("secret123")
    assert verify_password("wrong", hashed) is False


def test_hash_is_unique():
    # 同一密码两次 hash 不同（salt 随机）
    assert hash_password("x") != hash_password("x")


def test_create_and_decode_token():
    token = create_access_token(42, "student")
    payload = decode_access_token(token)
    assert payload["user_id"] == 42
    assert payload["role"] == "student"


def test_decode_invalid_token():
    with pytest.raises(Exception):
        decode_access_token("invalid.token.here")


def test_decode_tampered_token():
    token = create_access_token(1, "teacher")
    # 篡改 payload 后签名校验应失败
    with pytest.raises(Exception):
        decode_access_token(token + "x")
