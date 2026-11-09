"""HTTP 请求/响应日志中间件：记录每个请求的 method/path/status/耗时。

trace_id 由 TraceIdMiddleware 注入（需在外层先执行），本中间件在内层记录。
慢请求（>3s）和 5xx 用 WARNING 级别，方便筛选。
"""
import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

_SKIP_PATHS = frozenset({"/sb/health", "/health", "/favicon.ico"})
_SKIP_PREFIXES = ("/sb/docs", "/openapi.json", "/redoc")
_SLOW_THRESHOLD_MS = 3000


class RequestLoggingMiddleware:
    """记录每个 HTTP 请求的 method/path/status/耗时，慢请求和 5xx 特别标记。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in _SKIP_PATHS or any(path.startswith(p) for p in _SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        started_at = time.time()
        status_code = 0

        async def send_with_logging(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_logging)
        finally:
            elapsed_ms = int((time.time() - started_at) * 1000)
            slow = elapsed_ms > _SLOW_THRESHOLD_MS
            err = status_code >= 500
            tags = ""
            if slow:
                tags += " [慢请求]"
            if err:
                tags += " [服务器错误]"
            level = logging.WARNING if (slow or err) else logging.INFO
            logger.log(level, "HTTP %s %s -> %d %dms%s", method, path, status_code, elapsed_ms, tags)
