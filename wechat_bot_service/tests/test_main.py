import asyncio

import pytest

from wechat_bot_service.__main__ import initialize_app, load_config


def valid_environ() -> dict[str, str]:
    return {
        "WECHAT_BOT_ILINK_BASE_URL": "https://provider.test",
        "WECHAT_BOT_ILINK_TYPE": "3",
        "WECHAT_BOT_ILINK_APP_ID": "bot",
        "WECHAT_BOT_ILINK_CLIENT_VERSION": "132102",
        "WECHAT_BOT_AUTHORIZATION_TIMEOUT_SECONDS": "180",
        "WECHAT_BOT_AUTHORIZATION_POLL_TIMEOUT_SECONDS": "2",
        "WECHAT_BOT_REQUEST_TIMEOUT_SECONDS": "5",
        "WECHAT_BOT_BACKEND_MESSAGE_URL": "https://backend.test/messages",
        "WECHAT_BOT_BACKEND_ACCOUNTS_URL": "https://backend.test/accounts",
        "WECHAT_BOT_INTERNAL_TOKEN": "internal-secret",
        "HERMES_HOME": "/var/lib/wechat-bot/hermes",
        "WECHAT_BOT_SEND_CHUNK_RETRIES": "1",
        "WECHAT_BOT_SEND_CHUNK_DELAY_SECONDS": "0",
        "WECHAT_BOT_SEND_CHUNK_RETRY_DELAY_SECONDS": "0",
        "WECHAT_BOT_LISTEN_HOST": "127.0.0.1",
        "WECHAT_BOT_LISTEN_PORT": "8011",
    }


def test_load_config_fails_when_required_environment_is_missing() -> None:
    with pytest.raises(KeyError):
        load_config({})


def test_load_config_rejects_zero_send_chunk_retries() -> None:
    environ = valid_environ()
    environ["WECHAT_BOT_SEND_CHUNK_RETRIES"] = "0"

    with pytest.raises(ValueError, match="WECHAT_BOT_SEND_CHUNK_RETRIES"):
        load_config(environ)


def test_load_config_uses_native_hermes_home() -> None:
    config, host, port = load_config(valid_environ())

    assert config.hermes_home == "/var/lib/wechat-bot/hermes"
    assert config.authorization_poll_timeout_seconds == 2
    assert host == "127.0.0.1"
    assert port == 8011


def test_initialize_app_closes_runtime_when_restore_fails() -> None:
    async def scenario() -> None:
        closed = False

        class _Runtime:
            async def restore_accounts(self):
                raise RuntimeError("backend unavailable")

            async def close(self):
                nonlocal closed
                closed = True

        with pytest.raises(RuntimeError, match="backend unavailable"):
            await initialize_app(object(), runtime_factory=lambda _config: _Runtime())

        assert closed

    asyncio.run(scenario())


@pytest.mark.parametrize('token', ['', '   ', '\t'])
def test_load_config_rejects_blank_internal_token(token: str) -> None:
    environ = valid_environ()
    environ['WECHAT_BOT_INTERNAL_TOKEN'] = token
    with pytest.raises(ValueError, match='WECHAT_BOT_INTERNAL_TOKEN'):
        load_config(environ)
