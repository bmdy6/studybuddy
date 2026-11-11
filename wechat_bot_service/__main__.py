from __future__ import annotations

import os
from collections.abc import Mapping

from aiohttp import web

from wechat_bot_service.runtime import IlinkConfig, IlinkRuntime
from wechat_bot_service.service import create_app


def load_config(environ: Mapping[str, str]) -> tuple[IlinkConfig, str, int]:
    """从环境读取微信 Bot 微服务必填配置。"""
    send_chunk_retries = int(environ["WECHAT_BOT_SEND_CHUNK_RETRIES"])
    if send_chunk_retries < 1:
        raise ValueError("WECHAT_BOT_SEND_CHUNK_RETRIES 必须至少为 1")

    if not environ["WECHAT_BOT_INTERNAL_TOKEN"].strip():
        raise ValueError("WECHAT_BOT_INTERNAL_TOKEN 不能为空")

    return (
        IlinkConfig(
            base_url=environ["WECHAT_BOT_ILINK_BASE_URL"],
            bot_type=environ["WECHAT_BOT_ILINK_TYPE"],
            app_id=environ["WECHAT_BOT_ILINK_APP_ID"],
            client_version=environ["WECHAT_BOT_ILINK_CLIENT_VERSION"],
            authorization_timeout_seconds=int(
                environ["WECHAT_BOT_AUTHORIZATION_TIMEOUT_SECONDS"]
            ),
            authorization_poll_timeout_seconds=float(
                environ["WECHAT_BOT_AUTHORIZATION_POLL_TIMEOUT_SECONDS"]
            ),
            request_timeout_seconds=int(environ["WECHAT_BOT_REQUEST_TIMEOUT_SECONDS"]),
            backend_message_url=environ["WECHAT_BOT_BACKEND_MESSAGE_URL"],
            backend_accounts_url=environ["WECHAT_BOT_BACKEND_ACCOUNTS_URL"],
            internal_token=environ["WECHAT_BOT_INTERNAL_TOKEN"],
            hermes_home=environ["HERMES_HOME"],
            send_chunk_retries=send_chunk_retries,
            send_chunk_delay_seconds=float(
                environ["WECHAT_BOT_SEND_CHUNK_DELAY_SECONDS"]
            ),
            send_chunk_retry_delay_seconds=float(
                environ["WECHAT_BOT_SEND_CHUNK_RETRY_DELAY_SECONDS"]
            ),
        ),
        environ["WECHAT_BOT_LISTEN_HOST"],
        int(environ["WECHAT_BOT_LISTEN_PORT"]),
    )


async def initialize_app(
    config: IlinkConfig, *, runtime_factory=IlinkRuntime
) -> web.Application:
    runtime = runtime_factory(config)
    try:
        await runtime.restore_accounts()
    except Exception:
        await runtime.close()
        raise
    app = create_app(runtime, config.internal_token)

    async def close_runtime(_app: web.Application) -> None:
        await runtime.close()

    app.on_cleanup.append(close_runtime)
    return app


def main() -> None:
    """启动微信 Bot 微服务并恢复已绑定账号。"""
    config, host, port = load_config(os.environ)

    web.run_app(initialize_app(config), host=host, port=port)


if __name__ == "__main__":
    main()
