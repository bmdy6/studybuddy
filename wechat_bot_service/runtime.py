from __future__ import annotations

import asyncio
import base64
import secrets
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin
from uuid import uuid4

import aiohttp


@dataclass(frozen=True)
class IlinkConfig:
    base_url: str
    bot_type: str
    app_id: str
    client_version: str
    authorization_timeout_seconds: int
    authorization_poll_timeout_seconds: float
    request_timeout_seconds: int
    backend_message_url: str
    backend_accounts_url: str
    internal_token: str
    hermes_home: str
    send_chunk_retries: int
    send_chunk_delay_seconds: float
    send_chunk_retry_delay_seconds: float


@dataclass
class _Authorization:
    session_id: str
    qrcode: str
    qr_value: str
    expires_at: datetime
    status: str = "pending"
    provider_account_id: str | None = None
    ilink_user_id: str | None = None
    bot_token: str | None = None
    provider_base_url: str | None = None
    status_base_url: str | None = None

    def response(self) -> dict[str, str | None]:
        return {
            "session_id": self.session_id,
            "qr_value": self.qr_value,
            "status": self.status,
            "provider_account_id": self.provider_account_id,
            "ilink_user_id": self.ilink_user_id,
            "expires_at": self.expires_at.isoformat(),
        }


class IlinkRuntime:
    """管理 iLink 授权会话，消息 adapter 在授权确认后接入。"""

    def __init__(
        self,
        config: IlinkConfig,
        *,
        adapter_factory=None,
        credential_saver=None,
        credential_loader=None,
    ):
        from gateway.platforms.weixin import _make_ssl_connector

        self.config = config
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=config.request_timeout_seconds),
            trust_env=True,
            connector=_make_ssl_connector(),
        )
        self._authorizations: dict[str, _Authorization] = {}
        self._authorization_locks: dict[str, asyncio.Lock] = {}
        self._adapters: dict[str, object] = {}
        self._adapter_lock = asyncio.Lock()
        self._temporary_users: dict[tuple[str, str], datetime] = {}
        self._active_users: set[tuple[str, str]] = set()
        self._adapter_factory = adapter_factory or self._create_adapter
        self._credential_saver = credential_saver or self._save_credentials
        self._credential_loader = credential_loader or self._load_credentials

    def _create_adapter(self, account_id, token, base_url, user_id, handler):
        from gateway.config import PlatformConfig
        from gateway.platforms.weixin import WeixinAdapter

        adapter = WeixinAdapter(
            PlatformConfig(
                enabled=True,
                token=token,
                extra={
                    "account_id": account_id,
                    "base_url": base_url,
                    "dm_policy": "open",
                    "group_policy": "disabled",
                    "send_chunk_retries": self.config.send_chunk_retries,
                    "send_chunk_delay_seconds": self.config.send_chunk_delay_seconds,
                    "send_chunk_retry_delay_seconds": self.config.send_chunk_retry_delay_seconds,
                },
            )
        )
        adapter.set_message_handler(handler)
        return adapter

    @property
    def adapter_connected(self) -> bool:
        """返回共享微信 adapter 是否已连接。"""
        return bool(self._adapters)

    @property
    def active_user_count(self) -> int:
        """返回当前长期白名单用户数量。"""
        return len(self._active_users)

    def _save_credentials(self, **values):
        from gateway.platforms.weixin import save_weixin_account

        save_weixin_account(self.config.hermes_home, **values)

    @staticmethod
    def _load_credentials(hermes_home: str, account_id: str):
        from gateway.platforms.weixin import load_weixin_account

        return load_weixin_account(hermes_home, account_id)

    async def _connect_account(
        self, account_id: str, user_id: str, token: str, base_url: str
    ) -> bool:
        if not account_id or not token or not base_url:
            return False
        async with self._adapter_lock:
            if account_id in self._adapters:
                return True

            async def handle_inbound(event):
                inbound_user_id = str(event.source.user_id or "").strip()
                identity = (account_id, inbound_user_id)
                temporary_expires_at = self._temporary_users.get(identity)
                if temporary_expires_at and temporary_expires_at <= datetime.now(timezone.utc):
                    self._temporary_users.pop(identity, None)
                    temporary_expires_at = None
                if identity not in self._active_users and temporary_expires_at is None:
                    return None
                payload = {
                    "provider_account_id": account_id,
                    "ilink_user_id": inbound_user_id,
                    "content": event.text,
                }
                async with self._session.post(
                    self.config.backend_message_url,
                    json=payload,
                    headers={"X-Internal-Token": self.config.internal_token},
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                if result.get("activate_user"):
                    self._active_users.add(identity)
                    self._temporary_users.pop(identity, None)
                if result.get("deactivate_user"):
                    await self.remove_user(account_id, inbound_user_id)
                if result.get("persist_credentials"):
                    self._credential_saver(
                        account_id=account_id,
                        token=token,
                        base_url=base_url,
                        user_id="",
                    )
                return str(result.get("reply") or "") or None

            adapter = self._adapter_factory(account_id, token, base_url, user_id, handle_inbound)
            if not await adapter.connect():
                return False
            self._adapters[account_id] = adapter
            return True

    async def restore_account(self, account_id: str, user_id: str) -> bool:
        credentials = self._credential_loader(self.config.hermes_home, account_id)
        if not credentials:
            return False
        return await self._connect_account(
            account_id,
            user_id,
            str(credentials.get("token") or ""),
            str(credentials.get("base_url") or ""),
        )

    async def restore_accounts(self) -> None:
        async with self._session.get(
            self.config.backend_accounts_url,
            headers={"X-Internal-Token": self.config.internal_token},
        ) as response:
            response.raise_for_status()
            accounts = await response.json()
        for item in accounts.get("accounts", []):
            account_id = str(item.get("provider_account_id") or "")
            user_ids = {
                str(user_id).strip()
                for user_id in item.get("ilink_user_ids", [])
                if str(user_id).strip()
            }
            if account_id and await self.restore_account(
                account_id, min(user_ids) if user_ids else ""
            ):
                self._active_users.update((account_id, user_id) for user_id in user_ids)

    def _headers(self, *, json_request: bool = False) -> dict[str, str]:
        headers = {
            "iLink-App-Id": self.config.app_id,
            "iLink-App-ClientVersion": self.config.client_version,
        }
        if json_request:
            value = struct.unpack(">I", secrets.token_bytes(4))[0]
            headers.update(
                {
                    "Content-Type": "application/json",
                    "AuthorizationType": "ilink_bot_token",
                    "X-WECHAT-UIN": base64.b64encode(str(value).encode()).decode(),
                }
            )
        return headers

    async def _create_provider_qr(self) -> tuple[str, str]:
        endpoint = f"ilink/bot/get_bot_qrcode?bot_type={self.config.bot_type}"
        async with self._session.post(
            urljoin(self.config.base_url.rstrip("/") + "/", endpoint),
            json={"local_token_list": []},
            headers=self._headers(json_request=True),
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
        qrcode = str(payload.get("qrcode") or "")
        qr_value = str(payload.get("qrcode_img_content") or "")
        if not qrcode or not qr_value:
            raise RuntimeError("iLink 授权二维码响应不完整")
        return qrcode, qr_value

    async def create_authorization(self) -> dict[str, str | None]:
        qrcode, qr_value = await self._create_provider_qr()
        authorization = _Authorization(
            session_id=str(uuid4()),
            qrcode=qrcode,
            qr_value=qr_value,
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=self.config.authorization_timeout_seconds),
        )
        self._authorizations[authorization.session_id] = authorization
        self._authorization_locks[authorization.session_id] = asyncio.Lock()
        return authorization.response()

    async def get_authorization(self, session_id: str) -> dict[str, str | None] | None:
        authorization = self._authorizations.get(session_id)
        if authorization is None:
            return None
        async with self._authorization_locks[session_id]:
            if authorization.status in {"confirmed", "failed", "expired"}:
                return authorization.response()
            if authorization.expires_at <= datetime.now(timezone.utc):
                authorization.status = "expired"
                return authorization.response()
            endpoint = f"ilink/bot/get_qrcode_status?qrcode={authorization.qrcode}"
            status_base_url = authorization.status_base_url or self.config.base_url
            try:
                async with self._session.get(
                    urljoin(status_base_url.rstrip("/") + "/", endpoint),
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(
                        total=self.config.authorization_poll_timeout_seconds
                    ),
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
            except asyncio.TimeoutError:
                return authorization.response()
            status = str(payload.get("status") or "wait")
            if status == "expired":
                authorization.qrcode, authorization.qr_value = await self._create_provider_qr()
                authorization.status = "pending"
                authorization.status_base_url = None
            elif status == "scaned_but_redirect":
                redirect_host = str(payload.get("redirect_host") or "").strip()
                if redirect_host:
                    authorization.status_base_url = urljoin(
                        self.config.base_url, f"//{redirect_host}"
                    )
            elif status == "confirmed":
                authorization.status = "confirmed"
                authorization.provider_account_id = str(payload.get("ilink_bot_id") or "")
                authorization.ilink_user_id = str(payload.get("ilink_user_id") or "")
                authorization.bot_token = str(payload.get("bot_token") or "")
                authorization.provider_base_url = str(
                    payload.get("baseurl") or authorization.status_base_url or self.config.base_url
                )
                connected = await self._connect_account(
                    authorization.provider_account_id,
                    authorization.ilink_user_id,
                    authorization.bot_token,
                    authorization.provider_base_url,
                )
                if not connected:
                    authorization.status = "failed"
                if authorization.status == "confirmed":
                    self._temporary_users[
                        (authorization.provider_account_id, authorization.ilink_user_id)
                    ] = authorization.expires_at
            return authorization.response()

    async def send_message(self, payload: dict[str, str]) -> dict[str, str]:
        account_id = str(payload.get("provider_account_id") or "")
        user_id = str(payload.get("ilink_user_id") or "")
        content = str(payload.get("content") or "").strip()
        adapter = self._adapters.get(account_id)
        if (account_id, user_id) not in self._active_users:
            return {"status": "not_allowed"}
        if not adapter or not user_id or not content:
            return {"status": "failed"}
        result = await adapter.send(user_id, content)
        if result.success:
            return {"status": "success"}
        error = str(result.error or "").lower()
        if "ret=-2" in error or "rate limited" in error:
            return {"status": "window_closed"}
        if "session expired" in error or "errcode=-14" in error:
            return {"status": "session_expired"}
        return {"status": "failed"}

    async def remove_user(self, provider_account_id: str, ilink_user_id: str) -> None:
        """从临时和长期白名单移除指定微信用户。"""
        account_id = provider_account_id.strip()
        user_id = ilink_user_id.strip()
        identity = (account_id, user_id)
        self._temporary_users.pop(identity, None)
        self._active_users.discard(identity)

    async def disable_account(self, provider_account_id: str) -> None:
        async with self._adapter_lock:
            adapter = self._adapters.pop(provider_account_id, None)
            if adapter:
                await adapter.disconnect()
            self._temporary_users = {
                identity: expires_at
                for identity, expires_at in self._temporary_users.items()
                if identity[0] != provider_account_id
            }
            self._active_users = {
                identity
                for identity in self._active_users
                if identity[0] != provider_account_id
            }

    async def close(self) -> None:
        for adapter in list(self._adapters.values()):
            await adapter.disconnect()
        self._adapters.clear()
        self._temporary_users.clear()
        self._active_users.clear()
        await self._session.close()
