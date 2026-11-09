from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.user import User
from app.config import settings
from .schemas.learning_progress import LearningProgressMetrics
from app.features.growth import daily_record_service as daily_learning_record_service  # growth 域已迁
from .progress_service import build_progress_metrics

router = APIRouter(prefix="/api/learning-progress", tags=["learning-progress"])


@router.get("", response_model=LearningProgressMetrics)
def get_progress(
    student_id: int | None = None,
    as_of: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LearningProgressMetrics:
    sid = resolve_accessible_student_id(db, user, student_id)
    target = as_of or datetime.now(ZoneInfo(settings.WECHAT_TIMEZONE)).date()
    # 拉取足够长的历史，连续学习不能被 14 天窗口截断；周统计仍只消费最近 7 天。
    start = target - timedelta(days=366)
    records = daily_learning_record_service.list_by_range(db, sid, start, target)
    return build_progress_metrics(sid, target, records)
