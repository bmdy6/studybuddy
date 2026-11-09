from __future__ import annotations

import hashlib
import secrets

import httpx

from app.config import reveal_secret, settings


def is_valid_signature(token: str, signature: str, timestamp: str, nonce: str) -> bool:
    if not token or not signature or not timestamp or not nonce:
        return False
    expected = hashlib.sha1("".join(sorted([token, timestamp, nonce])).encode()).hexdigest()
    return secrets.compare_digest(expected, signature)


def send_customer_text(openid: str, content: str) -> None:
    """调用微信公众号客服消息接口发送文本。"""
    token_response = httpx.get(
        settings.WECHAT_ACCESS_TOKEN_URL,
        params={
            "grant_type": "client_credential",
            "appid": settings.WECHAT_APP_ID,
            "secret": reveal_secret(settings.WECHAT_APP_SECRET),
        },
        timeout=settings.WECHAT_API_TIMEOUT_SECONDS,
    )
    token_response.raise_for_status()
    access_token = token_response.json().get("access_token")
    if not access_token:
        raise RuntimeError("获取微信 access_token 失败")
    response = httpx.post(
        settings.WECHAT_CUSTOMER_MESSAGE_URL,
        params={"access_token": access_token},
        json={"touser": openid, "msgtype": "text", "text": {"content": content}},
        timeout=settings.WECHAT_API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    if response.json().get("errcode") != 0:
        raise RuntimeError("微信客服消息发送失败")


def send_ilink_text(provider_account_id: str, ilink_user_id: str, content: str) -> str:
    """通过微信 Bot 微服务向一个白名单用户发送文本。"""
    response = httpx.post(
        f"{settings.WECHAT_BOT_SERVICE_URL.rstrip('/')}/v1/messages",
        headers={"X-Internal-Token": reveal_secret(settings.WECHAT_BOT_INTERNAL_TOKEN)},
        json={
            "provider_account_id": provider_account_id,
            "ilink_user_id": ilink_user_id,
            "content": content,
        },
        timeout=settings.WECHAT_BOT_API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return str(response.json().get("status") or "failed")


def mask_openid(openid: str) -> str:
    if len(openid) <= 8:
        return openid[:2] + "***"
    return f"{openid[:6]}***{openid[-4:]}"
