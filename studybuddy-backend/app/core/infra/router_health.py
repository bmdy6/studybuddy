from fastapi import APIRouter, Response
from sqlalchemy import text

from app.config import has_secret, settings
from app.database import engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health(response: Response) -> dict[str, str]:
    status: dict[str, str] = {"status": "ok"}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["db"] = "ok"
    except Exception:
        status["db"] = "down"
        status["status"] = "down"
        response.status_code = 503  # DB 挂了才 503
        return status

    # COS 检查（轻量：只检查配置是否齐全，不真连）
    if has_secret(settings.COS_SECRET_ID) and has_secret(settings.COS_SECRET_KEY) and settings.COS_BUCKET:
        status["cos"] = "ok"
    else:
        status["cos"] = "degraded"
        status["status"] = "degraded"
    # degraded 仍返 200（约束 #21，防 LB 摘流）
    return status
