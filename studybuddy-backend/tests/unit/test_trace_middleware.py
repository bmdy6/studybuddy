import asyncio

from app.core.logging_config import trace_id_var
from app.middleware.trace import TraceIdMiddleware


def test_trace_id_stays_set_until_response_start_is_sent() -> None:
    observed_trace_ids: list[str] = []
    response_messages: list[dict[str, object]] = []

    async def downstream_app(scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            observed_trace_ids.append(trace_id_var.get())
        response_messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/ping",
        "raw_path": b"/ping",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"x-trace-id", b"request-trace-123")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8001),
    }

    asyncio.run(TraceIdMiddleware(downstream_app)(scope, receive, send))

    assert observed_trace_ids == ["request-trace-123"]
    assert trace_id_var.get() == "-"
    assert response_messages[0]["type"] == "http.response.start"
