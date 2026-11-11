from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone

from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

from wechat_bot_service.runtime import IlinkConfig, IlinkRuntime
from wechat_bot_service.service import create_app


class _Runtime:
    def __init__(self):
        self.sessions: dict[str, dict[str, str]] = {}
        self.removed_users: list[tuple[str, str]] = []
        self.adapter_connected = True
        self.active_user_count = 2

    async def create_authorization(self):
        session_id = f"session-{len(self.sessions) + 1}"
        session = {
            "session_id": session_id,
            "qr_value": f"https://example.test/{session_id}",
            "status": "pending",
        }
        self.sessions[session_id] = session
        return session

    async def get_authorization(self, session_id: str):
        return self.sessions.get(session_id)

    async def send_message(self, _payload):
        return {"status": "success"}

    async def disable_account(self, _provider_account_id: str):
        return None

    async def remove_user(self, provider_account_id: str, ilink_user_id: str):
        self.removed_users.append((provider_account_id, ilink_user_id))


def _ilink_config(base_url: str, backend_url: str = "https://backend.test/internal"):
    return IlinkConfig(
        base_url=base_url,
        bot_type="3",
        app_id="bot",
        client_version="132102",
        authorization_timeout_seconds=180,
        authorization_poll_timeout_seconds=5,
        request_timeout_seconds=5,
        backend_message_url=backend_url,
        backend_accounts_url="https://backend.test/accounts",
        internal_token="internal-secret",
        hermes_home="/tmp/wechat-bot-test",
        send_chunk_retries=0,
        send_chunk_delay_seconds=0,
        send_chunk_retry_delay_seconds=0,
    )


def test_internal_api_rejects_missing_token() -> None:
    async def scenario():
        client = TestClient(TestServer(create_app(_Runtime(), "internal-secret")))
        await client.start_server()
        try:
            response = await client.post("/v1/authorizations")
            assert response.status == 401
        finally:
            await client.close()

    asyncio.run(scenario())


def test_health_reports_shared_adapter_without_exposing_identities() -> None:
    async def scenario():
        client = TestClient(TestServer(create_app(_Runtime(), "internal-secret")))
        await client.start_server()
        try:
            unauthorized = await client.get("/health")
            response = await client.get(
                "/health", headers={"X-Internal-Token": "internal-secret"}
            )
            payload = await response.json()

            assert unauthorized.status == 401
            assert response.status == 200
            assert payload == {
                "status": "ok",
                "adapter_connected": True,
                "active_user_count": 2,
            }
            assert "provider_account_id" not in payload
            assert "ilink_user_ids" not in payload
        finally:
            await client.close()

    asyncio.run(scenario())


def test_internal_api_removes_one_user_without_disabling_adapter() -> None:
    async def scenario():
        runtime = _Runtime()
        client = TestClient(TestServer(create_app(runtime, "internal-secret")))
        await client.start_server()
        try:
            response = await client.delete(
                "/v1/accounts/shared-bot@im.bot/users/student@im.wechat",
                headers={"X-Internal-Token": "internal-secret"},
            )

            assert response.status == 204
            assert runtime.removed_users == [
                ("shared-bot@im.bot", "student@im.wechat")
            ]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_authorization_sessions_are_isolated() -> None:
    async def scenario():
        client = TestClient(TestServer(create_app(_Runtime(), "internal-secret")))
        await client.start_server()
        headers = {"X-Internal-Token": "internal-secret"}
        try:
            first = await (await client.post("/v1/authorizations", headers=headers)).json()
            second = await (await client.post("/v1/authorizations", headers=headers)).json()
            first_status = await (
                await client.get(f"/v1/authorizations/{first['session_id']}", headers=headers)
            ).json()

            assert first["session_id"] != second["session_id"]
            assert first["qr_value"] != second["qr_value"]
            assert first_status == first
        finally:
            await client.close()

    asyncio.run(scenario())


def test_ilink_authorization_uses_current_post_contract() -> None:
    async def scenario():
        captured: dict[str, object] = {}

        async def create_qr(request: web.Request):
            captured["method"] = request.method
            captured["headers"] = dict(request.headers)
            captured["body"] = await request.json()
            return web.Response(
                body=json.dumps(
                    {"qrcode": "qr-code-1", "qrcode_img_content": "https://example.test/qr-1"}
                ).encode(),
                content_type="application/octet-stream",
            )

        provider = web.Application()
        provider.router.add_post("/ilink/bot/get_bot_qrcode", create_qr)
        server = TestServer(provider)
        await server.start_server()
        runtime = IlinkRuntime(_ilink_config(str(server.make_url(""))))
        try:
            result = await runtime.create_authorization()
            assert captured["method"] == "POST"
            assert captured["body"] == {"local_token_list": []}
            assert captured["headers"]["iLink-App-ClientVersion"] == "132102"
            assert result["qr_value"] == "https://example.test/qr-1"
            assert result["status"] == "pending"
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_restore_account_uses_shared_hermes_credentials() -> None:
    async def scenario():
        connected: list[tuple[str, str, str]] = []

        class _Adapter:
            async def connect(self):
                return True

            async def disconnect(self):
                return None

        def adapter_factory(account_id, token, _base_url, user_id, _handler):
            connected.append((account_id, token, user_id))
            return _Adapter()

        runtime = IlinkRuntime(
            _ilink_config("https://provider.test"),
            adapter_factory=adapter_factory,
            credential_loader=lambda _home, _account_id: {
                "token": "saved-token",
                "base_url": "https://provider.test",
            },
        )
        try:
            assert await runtime.restore_account(
                "bot-restore@im.bot", "user-restore@im.wechat"
            )
            assert connected == [
                ("bot-restore@im.bot", "saved-token", "user-restore@im.wechat")
            ]
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_expired_provider_qr_refreshes_same_authorization_session() -> None:
    async def scenario():
        created = 0

        async def create_qr(_request: web.Request):
            nonlocal created
            created += 1
            return web.json_response(
                {
                    "qrcode": f"qr-code-{created}",
                    "qrcode_img_content": f"https://example.test/qr-{created}",
                }
            )

        async def get_status(_request: web.Request):
            return web.json_response({"status": "expired"})

        provider = web.Application()
        provider.router.add_post("/ilink/bot/get_bot_qrcode", create_qr)
        provider.router.add_get("/ilink/bot/get_qrcode_status", get_status)
        server = TestServer(provider)
        await server.start_server()
        runtime = IlinkRuntime(_ilink_config(str(server.make_url(""))))
        try:
            first = await runtime.create_authorization()
            refreshed = await runtime.get_authorization(first["session_id"])
            assert refreshed["session_id"] == first["session_id"]
            assert refreshed["qr_value"] == "https://example.test/qr-2"
            assert refreshed["status"] == "pending"
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_provider_poll_timeout_keeps_authorization_pending() -> None:
    async def scenario():
        async def create_qr(_request: web.Request):
            return web.json_response(
                {"qrcode": "qr-code", "qrcode_img_content": "https://example.test/qr"}
            )

        async def get_status(_request: web.Request):
            await asyncio.sleep(0.1)
            return web.json_response({"status": "wait"})

        provider = web.Application()
        provider.router.add_post("/ilink/bot/get_bot_qrcode", create_qr)
        provider.router.add_get("/ilink/bot/get_qrcode_status", get_status)
        server = TestServer(provider)
        await server.start_server()
        runtime = IlinkRuntime(
            replace(
                _ilink_config(str(server.make_url(""))),
                authorization_poll_timeout_seconds=0.01,
            )
        )
        try:
            authorization = await runtime.create_authorization()
            result = await runtime.get_authorization(authorization["session_id"])

            assert result == authorization
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_concurrent_polls_share_one_provider_request() -> None:
    async def scenario():
        poll_count = 0

        async def create_qr(_request: web.Request):
            return web.json_response(
                {"qrcode": "qr-code", "qrcode_img_content": "https://example.test/qr"}
            )

        async def get_status(_request: web.Request):
            nonlocal poll_count
            poll_count += 1
            await asyncio.sleep(0.02)
            return web.json_response(
                {
                    "status": "confirmed",
                    "ilink_bot_id": "shared-bot@im.bot",
                    "ilink_user_id": "user@im.wechat",
                    "bot_token": "bot-token",
                    "baseurl": "https://provider.test",
                }
            )

        class _Adapter:
            async def connect(self):
                return True

            async def disconnect(self):
                return None

        provider = web.Application()
        provider.router.add_post("/ilink/bot/get_bot_qrcode", create_qr)
        provider.router.add_get("/ilink/bot/get_qrcode_status", get_status)
        server = TestServer(provider)
        await server.start_server()
        runtime = IlinkRuntime(
            _ilink_config(str(server.make_url(""))),
            adapter_factory=lambda *_args: _Adapter(),
        )
        try:
            authorization = await runtime.create_authorization()
            first, second = await asyncio.gather(
                runtime.get_authorization(authorization["session_id"]),
                runtime.get_authorization(authorization["session_id"]),
            )

            assert first["status"] == second["status"] == "confirmed"
            assert poll_count == 1
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_concurrent_authorizations_connect_only_one_shared_adapter() -> None:
    async def scenario():
        adapter_count = 0

        class _Adapter:
            async def connect(self):
                nonlocal adapter_count
                adapter_count += 1
                await asyncio.sleep(0.02)
                return True

            async def disconnect(self):
                return None

        runtime = IlinkRuntime(
            _ilink_config("https://provider.test"),
            adapter_factory=lambda *_args: _Adapter(),
        )
        try:
            first, second = await asyncio.gather(
                runtime._connect_account(
                    "shared-bot@im.bot", "user-1@im.wechat", "token-1", "https://provider.test"
                ),
                runtime._connect_account(
                    "shared-bot@im.bot", "user-2@im.wechat", "token-2", "https://provider.test"
                ),
            )

            assert first and second
            assert adapter_count == 1
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_provider_redirect_host_is_used_for_followup_poll() -> None:
    async def scenario():
        redirected_polls = 0

        async def create_qr(_request: web.Request):
            return web.json_response(
                {"qrcode": "qr-code", "qrcode_img_content": "https://example.test/qr"}
            )

        async def initial_status(_request: web.Request):
            return web.json_response(
                {
                    "status": "scaned_but_redirect",
                    "redirect_host": redirected_server.make_url("").authority,
                }
            )

        async def redirected_status(_request: web.Request):
            nonlocal redirected_polls
            redirected_polls += 1
            return web.json_response({"status": "wait"})

        redirected = web.Application()
        redirected.router.add_get("/ilink/bot/get_qrcode_status", redirected_status)
        redirected_server = TestServer(redirected)
        await redirected_server.start_server()

        provider = web.Application()
        provider.router.add_post("/ilink/bot/get_bot_qrcode", create_qr)
        provider.router.add_get("/ilink/bot/get_qrcode_status", initial_status)
        provider_server = TestServer(provider)
        await provider_server.start_server()
        runtime = IlinkRuntime(_ilink_config(str(provider_server.make_url(""))))
        try:
            authorization = await runtime.create_authorization()
            await runtime.get_authorization(authorization["session_id"])
            await runtime.get_authorization(authorization["session_id"])

            assert redirected_polls == 1
        finally:
            await runtime.close()
            await provider_server.close()
            await redirected_server.close()

    asyncio.run(scenario())


def test_disabling_adapter_only_clears_its_user_whitelists() -> None:
    async def scenario():
        class _Adapter:
            async def connect(self):
                return True

            async def disconnect(self):
                return None

        runtime = IlinkRuntime(
            _ilink_config("https://provider.test"),
            adapter_factory=lambda *_args: _Adapter(),
        )
        try:
            assert await runtime._connect_account(
                "shared-bot@im.bot", "user@im.wechat", "token", "https://provider.test"
            )
            runtime._active_users.update(
                {
                    ("shared-bot@im.bot", "active@im.wechat"),
                    ("other-bot@im.bot", "other@im.wechat"),
                }
            )
            runtime._temporary_users[
                ("shared-bot@im.bot", "temporary@im.wechat")
            ] = datetime.now(timezone.utc)

            await runtime.disable_account("shared-bot@im.bot")

            assert runtime.active_user_count == 1
            assert runtime._active_users == {
                ("other-bot@im.bot", "other@im.wechat")
            }
            assert runtime._temporary_users == {}
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_confirmed_authorization_forwards_inbound_identity_and_persists_after_binding() -> None:
    async def scenario():
        backend_payload: dict[str, str] = {}
        saved: list[dict[str, str]] = []

        async def create_qr(_request: web.Request):
            return web.json_response(
                {"qrcode": "qr-code", "qrcode_img_content": "https://example.test/qr"}
            )

        async def get_status(_request: web.Request):
            return web.json_response(
                {
                    "status": "confirmed",
                    "ilink_bot_id": "bot-1@im.bot",
                    "ilink_user_id": "user-1@im.wechat",
                    "bot_token": "bot-token-1",
                    "baseurl": "https://provider.test",
                }
            )

        async def receive_message(request: web.Request):
            backend_payload.update(await request.json())
            return web.json_response({"reply": "绑定成功", "persist_credentials": True})

        provider = web.Application()
        provider.router.add_post("/ilink/bot/get_bot_qrcode", create_qr)
        provider.router.add_get("/ilink/bot/get_qrcode_status", get_status)
        provider_server = TestServer(provider)
        backend = web.Application()
        backend.router.add_post("/internal", receive_message)
        backend_server = TestServer(backend)
        await provider_server.start_server()
        await backend_server.start_server()

        class _Adapter:
            async def connect(self):
                return True

            async def disconnect(self):
                return None

            async def send(self, _user_id, _content):
                return type("Result", (), {"success": True, "error": None})()

        handlers = {}

        def adapter_factory(account_id, _token, _base_url, user_id, handler):
            handlers[(account_id, user_id)] = handler
            return _Adapter()

        runtime = IlinkRuntime(
            _ilink_config(
                str(provider_server.make_url("")), str(backend_server.make_url("/internal"))
            ),
            adapter_factory=adapter_factory,
            credential_saver=lambda **values: saved.append(values),
        )
        try:
            authorization = await runtime.create_authorization()
            await runtime.get_authorization(authorization["session_id"])
            event = type(
                "Event",
                (),
                {
                    "text": "WABC123",
                    "source": type("Source", (), {"user_id": "user-1@im.wechat"})(),
                },
            )()
            reply = await handlers[("bot-1@im.bot", "user-1@im.wechat")](event)

            assert backend_payload == {
                "provider_account_id": "bot-1@im.bot",
                "ilink_user_id": "user-1@im.wechat",
                "content": "WABC123",
            }
            assert reply == "绑定成功"
            assert saved[0]["account_id"] == "bot-1@im.bot"
            assert saved[0]["user_id"] == ""
        finally:
            await runtime.close()
            await provider_server.close()
            await backend_server.close()

    asyncio.run(scenario())


def test_shared_adapter_uses_runtime_whitelist_instead_of_static_allowlist() -> None:
    async def scenario():
        runtime = IlinkRuntime(_ilink_config("https://provider.test"))
        try:
            adapter = runtime._create_adapter(
                "shared-bot@im.bot",
                "shared-token",
                "https://provider.test",
                "first-user@im.wechat",
                lambda _event: None,
            )

            assert adapter._dm_policy == "open"
            assert adapter._allow_from == []
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_shared_adapter_only_forwards_authorized_users_for_binding_code_validation() -> None:
    async def scenario():
        created_qr_count = 0
        backend_payloads: list[dict[str, str]] = []

        async def create_qr(_request: web.Request):
            nonlocal created_qr_count
            created_qr_count += 1
            return web.json_response(
                {
                    "qrcode": f"qr-code-{created_qr_count}",
                    "qrcode_img_content": f"https://example.test/qr-{created_qr_count}",
                }
            )

        async def get_status(request: web.Request):
            qr_index = request.query["qrcode"].rsplit("-", 1)[1]
            return web.json_response(
                {
                    "status": "confirmed",
                    "ilink_bot_id": "shared-bot@im.bot",
                    "ilink_user_id": f"user-{qr_index}@im.wechat",
                    "bot_token": "shared-bot-token",
                    "baseurl": "https://provider.test",
                }
            )

        async def receive_message(request: web.Request):
            backend_payloads.append(await request.json())
            return web.json_response({"reply": "已接收"})

        provider = web.Application()
        provider.router.add_post("/ilink/bot/get_bot_qrcode", create_qr)
        provider.router.add_get("/ilink/bot/get_qrcode_status", get_status)
        provider_server = TestServer(provider)
        backend = web.Application()
        backend.router.add_post("/internal", receive_message)
        backend_server = TestServer(backend)
        await provider_server.start_server()
        await backend_server.start_server()

        handlers = []

        class _Adapter:
            async def connect(self):
                return True

            async def disconnect(self):
                return None

        def adapter_factory(_account_id, _token, _base_url, _user_id, handler):
            handlers.append(handler)
            return _Adapter()

        runtime = IlinkRuntime(
            _ilink_config(
                str(provider_server.make_url("")), str(backend_server.make_url("/internal"))
            ),
            adapter_factory=adapter_factory,
        )
        try:
            first = await runtime.create_authorization()
            second = await runtime.create_authorization()
            await runtime.get_authorization(first["session_id"])
            await runtime.get_authorization(second["session_id"])

            assert len(handlers) == 1
            handler = handlers[0]

            def event(user_id: str):
                return type(
                    "Event",
                    (),
                    {
                        "text": "WABC123",
                        "source": type("Source", (), {"user_id": user_id})(),
                    },
                )()

            assert await handler(event("user-1@im.wechat")) == "已接收"
            assert await handler(event("user-2@im.wechat")) == "已接收"
            assert await handler(event("unknown@im.wechat")) is None
            assert [payload["ilink_user_id"] for payload in backend_payloads] == [
                "user-1@im.wechat",
                "user-2@im.wechat",
            ]
        finally:
            await runtime.close()
            await provider_server.close()
            await backend_server.close()

    asyncio.run(scenario())


def test_binding_activation_controls_outbound_and_user_removal() -> None:
    async def scenario():
        async def create_qr(_request: web.Request):
            return web.json_response(
                {"qrcode": "qr-code", "qrcode_img_content": "https://example.test/qr"}
            )

        async def get_status(_request: web.Request):
            return web.json_response(
                {
                    "status": "confirmed",
                    "ilink_bot_id": "shared-bot@im.bot",
                    "ilink_user_id": "student@im.wechat",
                    "bot_token": "shared-bot-token",
                    "baseurl": "https://provider.test",
                }
            )

        async def receive_message(_request: web.Request):
            return web.json_response({"reply": "绑定成功", "activate_user": True})

        provider = web.Application()
        provider.router.add_post("/ilink/bot/get_bot_qrcode", create_qr)
        provider.router.add_get("/ilink/bot/get_qrcode_status", get_status)
        provider_server = TestServer(provider)
        backend = web.Application()
        backend.router.add_post("/internal", receive_message)
        backend_server = TestServer(backend)
        await provider_server.start_server()
        await backend_server.start_server()

        handlers = []

        class _Adapter:
            async def connect(self):
                return True

            async def disconnect(self):
                return None

            async def send(self, _user_id, _content):
                return type("Result", (), {"success": True, "error": None})()

        def adapter_factory(_account_id, _token, _base_url, _user_id, handler):
            handlers.append(handler)
            return _Adapter()

        runtime = IlinkRuntime(
            _ilink_config(
                str(provider_server.make_url("")), str(backend_server.make_url("/internal"))
            ),
            adapter_factory=adapter_factory,
        )
        try:
            authorization = await runtime.create_authorization()
            await runtime.get_authorization(authorization["session_id"])
            event = type(
                "Event",
                (),
                {
                    "text": "WABC123",
                    "source": type("Source", (), {"user_id": "student@im.wechat"})(),
                },
            )()
            assert await handlers[0](event) == "绑定成功"

            active_payload = {
                "provider_account_id": "shared-bot@im.bot",
                "ilink_user_id": "student@im.wechat",
                "content": "学习提醒",
            }
            unknown_payload = {
                **active_payload,
                "ilink_user_id": "unknown@im.wechat",
            }
            assert await runtime.send_message(active_payload) == {"status": "success"}
            assert await runtime.send_message(unknown_payload) == {"status": "not_allowed"}

            runtime._active_users.add(("other-bot@im.bot", "student@im.wechat"))

            await runtime.remove_user("shared-bot@im.bot", "student@im.wechat")

            assert await runtime.send_message(active_payload) == {"status": "not_allowed"}
            assert ("other-bot@im.bot", "student@im.wechat") in runtime._active_users
        finally:
            await runtime.close()
            await provider_server.close()
            await backend_server.close()

    asyncio.run(scenario())


def test_second_provider_account_connects_without_replacing_first_adapter() -> None:
    async def scenario():
        created_qr_count = 0

        async def create_qr(_request: web.Request):
            nonlocal created_qr_count
            created_qr_count += 1
            return web.json_response(
                {
                    "qrcode": f"qr-code-{created_qr_count}",
                    "qrcode_img_content": f"https://example.test/qr-{created_qr_count}",
                }
            )

        async def get_status(request: web.Request):
            qr_index = request.query["qrcode"].rsplit("-", 1)[1]
            return web.json_response(
                {
                    "status": "confirmed",
                    "ilink_bot_id": f"bot-{qr_index}@im.bot",
                    "ilink_user_id": f"user-{qr_index}@im.wechat",
                    "bot_token": f"bot-token-{qr_index}",
                    "baseurl": "https://provider.test",
                }
            )

        provider = web.Application()
        provider.router.add_post("/ilink/bot/get_bot_qrcode", create_qr)
        provider.router.add_get("/ilink/bot/get_qrcode_status", get_status)
        provider_server = TestServer(provider)
        await provider_server.start_server()
        adapter_count = 0

        class _Adapter:
            async def connect(self):
                return True

            async def disconnect(self):
                return None

        def adapter_factory(_account_id, _token, _base_url, _user_id, _handler):
            nonlocal adapter_count
            adapter_count += 1
            return _Adapter()

        runtime = IlinkRuntime(
            _ilink_config(str(provider_server.make_url(""))),
            adapter_factory=adapter_factory,
        )
        try:
            first = await runtime.create_authorization()
            second = await runtime.create_authorization()

            assert (await runtime.get_authorization(first["session_id"]))["status"] == "confirmed"
            assert (await runtime.get_authorization(second["session_id"]))["status"] == "confirmed"
            assert adapter_count == 2
        finally:
            await runtime.close()
            await provider_server.close()

    asyncio.run(scenario())


def test_restore_accounts_connects_multiple_adapters_and_isolates_active_users() -> None:
    async def scenario():
        async def list_accounts(_request: web.Request):
            return web.json_response(
                {
                    "accounts": [
                        {
                            "provider_account_id": "bot-a@im.bot",
                            "ilink_user_ids": ["user-1@im.wechat", "user-2@im.wechat"],
                        },
                        {
                            "provider_account_id": "bot-b@im.bot",
                            "ilink_user_ids": ["user-3@im.wechat"],
                        },
                    ]
                }
            )

        backend = web.Application()
        backend.router.add_get("/accounts", list_accounts)
        backend_server = TestServer(backend)
        await backend_server.start_server()
        connected_accounts: list[str] = []

        class _Adapter:
            async def connect(self):
                return True

            async def disconnect(self):
                return None

            async def send(self, _user_id, _content):
                return type("Result", (), {"success": True, "error": None})()

        def adapter_factory(account_id, _token, _base_url, _user_id, _handler):
            connected_accounts.append(account_id)
            return _Adapter()

        config = replace(
            _ilink_config("https://provider.test"),
            backend_accounts_url=str(backend_server.make_url("/accounts")),
        )
        runtime = IlinkRuntime(
            config,
            adapter_factory=adapter_factory,
            credential_loader=lambda _home, _account_id: {
                "token": "saved-shared-token",
                "base_url": "https://provider.test",
            },
        )
        try:
            await runtime.restore_accounts()

            assert connected_accounts == ["bot-a@im.bot", "bot-b@im.bot"]
            assert runtime.active_user_count == 3
            for user_id in ("user-1@im.wechat", "user-2@im.wechat"):
                assert await runtime.send_message(
                    {
                        "provider_account_id": "bot-a@im.bot",
                        "ilink_user_id": user_id,
                        "content": "学习提醒",
                    }
                ) == {"status": "success"}
            assert await runtime.send_message(
                {
                    "provider_account_id": "bot-b@im.bot",
                    "ilink_user_id": "user-3@im.wechat",
                    "content": "学习提醒",
                }
            ) == {"status": "success"}
            assert await runtime.send_message(
                {
                    "provider_account_id": "bot-b@im.bot",
                    "ilink_user_id": "user-1@im.wechat",
                    "content": "学习提醒",
                }
            ) == {"status": "not_allowed"}
        finally:
            await runtime.close()
            await backend_server.close()

    asyncio.run(scenario())


def test_restore_accounts_connects_shared_adapter_without_active_users() -> None:
    async def scenario():
        async def list_accounts(_request: web.Request):
            return web.json_response(
                {
                    "accounts": [
                        {
                            "provider_account_id": "idle-bot@im.bot",
                            "ilink_user_ids": [],
                        }
                    ]
                }
            )

        backend = web.Application()
        backend.router.add_get("/accounts", list_accounts)
        backend_server = TestServer(backend)
        await backend_server.start_server()
        connected_users: list[str] = []

        class _Adapter:
            async def connect(self):
                return True

            async def disconnect(self):
                return None

        def adapter_factory(_account_id, _token, _base_url, user_id, _handler):
            connected_users.append(user_id)
            return _Adapter()

        runtime = IlinkRuntime(
            replace(
                _ilink_config("https://provider.test"),
                backend_accounts_url=str(backend_server.make_url("/accounts")),
            ),
            adapter_factory=adapter_factory,
            credential_loader=lambda _home, _account_id: {
                "token": "saved-shared-token",
                "base_url": "https://provider.test",
            },
        )
        try:
            await runtime.restore_accounts()

            assert runtime.adapter_connected is True
            assert runtime.active_user_count == 0
            assert connected_users == [""]
        finally:
            await runtime.close()
            await backend_server.close()

    asyncio.run(scenario())


def test_service_rejects_blank_internal_token() -> None:
    import pytest

    for token in ('', '   ', '\t'):
        with pytest.raises(ValueError, match='WECHAT_BOT_INTERNAL_TOKEN'):
            create_app(_Runtime(), token)
