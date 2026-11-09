import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging_config import trace_id_var


class TraceIdMiddleware:
    """为每个请求注入 trace_id（优先复用上游 X-Trace-Id），响应头回写 + 写入日志上下文。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        trace_id = Headers(scope=scope).get("X-Trace-Id") or str(uuid.uuid4())
        scope.setdefault("state", {})["trace_id"] = trace_id
        token = trace_id_var.set(trace_id)

        async def send_with_trace_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Trace-Id"] = trace_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace_id)
        finally:
            trace_id_var.reset(token)
