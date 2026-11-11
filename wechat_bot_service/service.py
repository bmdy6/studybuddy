from __future__ import annotations

import hmac

from aiohttp import web


def create_app(runtime, internal_token: str) -> web.Application:
    """创建只暴露微信渠道能力的 HTTP 服务。"""

    if not internal_token.strip():
        raise ValueError("WECHAT_BOT_INTERNAL_TOKEN 不能为空")

    @web.middleware
    async def authenticate(request: web.Request, handler):
        supplied = request.headers.get("X-Internal-Token", "")
        if not hmac.compare_digest(supplied, internal_token):
            raise web.HTTPUnauthorized()
        return await handler(request)

    async def health(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "adapter_connected": runtime.adapter_connected,
                "active_user_count": runtime.active_user_count,
            }
        )

    async def create_authorization(_request: web.Request) -> web.Response:
        return web.json_response(await runtime.create_authorization())

    async def get_authorization(request: web.Request) -> web.Response:
        session = await runtime.get_authorization(request.match_info["session_id"])
        if session is None:
            raise web.HTTPNotFound()
        return web.json_response(session)

    async def send_message(request: web.Request) -> web.Response:
        return web.json_response(await runtime.send_message(await request.json()))

    async def disable_account(request: web.Request) -> web.Response:
        await runtime.disable_account(request.match_info["provider_account_id"])
        return web.Response(status=204)

    async def remove_user(request: web.Request) -> web.Response:
        await runtime.remove_user(
            request.match_info["provider_account_id"],
            request.match_info["ilink_user_id"],
        )
        return web.Response(status=204)

    app = web.Application(middlewares=[authenticate])
    app.router.add_get("/health", health)
    app.router.add_post("/v1/authorizations", create_authorization)
    app.router.add_get("/v1/authorizations/{session_id}", get_authorization)
    app.router.add_post("/v1/messages", send_message)
    app.router.add_delete(
        "/v1/accounts/{provider_account_id}/users/{ilink_user_id}", remove_user
    )
    app.router.add_post("/v1/accounts/{provider_account_id}/disable", disable_account)
    return app
