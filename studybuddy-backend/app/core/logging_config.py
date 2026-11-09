"""统一日志配置：控制台 + 文件轮转 + trace_id 注入。

用法（main.py 启动时调用一次）：
    from app.core.logging_config import setup_logging
    setup_logging(level="INFO", log_dir="/path/to/logs")

各业务模块（无需额外配置，trace_id 自动注入）：
    import logging
    logger = logging.getLogger(__name__)
    logger.info("用户登录 user_id=%s", user_id)
"""

import logging
import logging.handlers
import os
import sys
from contextvars import ContextVar

# trace_id 上下文：TraceIdMiddleware 设置，日志 Filter 读取，实现全链路追踪
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class TraceIdFilter(logging.Filter):
    """注入 trace_id 到每条日志记录，便于按请求排查全链路。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get("-")
        return True


def setup_logging(level: str = "INFO", log_dir: str | None = None) -> None:
    """统一日志配置。

    - 控制台：stdout，带 trace_id
    - 文件轮转：log_dir 指定时启用，10MB/文件，保留 5 份
    - 格式：时间 | 级别 | 模块 | trace_id | 消息
    - 降低第三方库噪音（urllib3/httpx）
    """
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | trace_id=%(trace_id)s | %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

    # 控制台
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(TraceIdFilter())
    root.addHandler(console)

    # 文件轮转
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "studybuddy.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(TraceIdFilter())
        root.addHandler(file_handler)

    # 降低第三方库噪音
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # 统一 uvicorn 日志走 root（带 trace_id，替代 uvicorn 默认格式）
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
        uv_logger.setLevel(level)
