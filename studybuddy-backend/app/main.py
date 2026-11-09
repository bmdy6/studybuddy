"""FastAPI 主应用入口：挂载全部路由 + 中间件。"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.logging_config import setup_logging
from app.middleware.request_logging import RequestLoggingMiddleware
from app.middleware.trace import TraceIdMiddleware
from app.features.exams.router_answer import router as answer_router
from app.core.auth.router import router as auth_router
from app.features.chat.router import router as chat_router
from app.features.growth.router_daily_records import router as daily_learning_record_router
from app.features.growth.router_daily_checkin import router as daily_checkin_router
from app.features.learning.router_diagnosis import router as diagnosis_router
from app.features.error_book.router import router as error_book_router
from app.features.exams.router import router as exam_router
from app.features.exams.router_exam_batch import router as exam_batch_router
from app.core.infra.router_health import router as health_router
from app.features.learning.router_learning_flow import router as learning_flow_router
from app.features.learning.router_learning_map import router as learning_map_router
from app.features.learning.router_learning_progress import router as learning_progress_router
from app.features.materials.router import router as material_router
from app.features.note.router import router as note_router
from app.core.infra.router_notification import router as notification_router
from app.features.p2.router_reminder import router as notification_reminder_router
from app.features.p2.router import router as p2_router
from app.features.question_bank.router import router as question_bank_router
from app.features.growth.router_supervision import router as supervision_router
from app.features.wechat.router import internal_router as wechat_internal_router
from app.features.memory.router import router as memory_router
from app.features.family_goal.router import router as family_goal_router
from app.features.family_goal.router_integration import router as family_goal_integration_router
from app.features.wechat.router import router as wechat_router

setup_logging(level=settings.LOG_LEVEL, log_dir=settings.LOG_DIR or None)

app = FastAPI(title=f"{settings.BRAND_NAME} API", version="0.1.0")


def _cors_origins() -> list[str]:
    """解析 CORS_ORIGINS，生产环境用逗号分隔域名，开发默认 *。"""
    raw = settings.CORS_ORIGINS.strip()
    if not raw or raw == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(TraceIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(exam_router)
app.include_router(answer_router)
app.include_router(error_book_router)
app.include_router(diagnosis_router)
app.include_router(learning_flow_router)
app.include_router(learning_map_router)
app.include_router(learning_progress_router)
app.include_router(material_router)
app.include_router(chat_router)
app.include_router(daily_learning_record_router)
app.include_router(daily_checkin_router)
app.include_router(note_router)
app.include_router(notification_router)
app.include_router(notification_reminder_router)
app.include_router(p2_router)
app.include_router(exam_batch_router)
app.include_router(question_bank_router)
app.include_router(supervision_router)
app.include_router(wechat_router)
app.include_router(wechat_internal_router)
app.include_router(memory_router)
app.include_router(family_goal_router)
app.include_router(family_goal_integration_router)

# 本地文件存储静态服务：material_service 返回的 /sb/uploads/... URL 会经 nginx 代理到这里
_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(_UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_UPLOAD_DIR), name="uploads")


@app.get("/")
def root() -> dict[str, str]:
    return {"name": f"{settings.BRAND_NAME} API", "docs": "/docs"}
