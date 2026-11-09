"""每日学习记录路由：查询和受控刷新（spec 3.1/5.1）。

权限：student 只能操作自己的；parent 只能操作绑定学生（复用 resolve_accessible_student_id）。
仅开放服务端本地日期的受控 refresh；不开放任意日期写入或覆盖事实快照。
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.user import User
from app.config import settings
from .schemas.daily_records import DailyLearningRecordItem
from . import daily_record_service as daily_learning_record_service

router = APIRouter(prefix="/api/daily-records", tags=["daily-records"])


@router.post("/refresh", response_model=DailyLearningRecordItem)
async def api_refresh(
    student_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyLearningRecordItem:
    """刷新服务端本地日期的每日记录，唯一写入入口仍是 service.refresh。"""
    sid = resolve_accessible_student_id(db, user, student_id)
    target_date = datetime.now(ZoneInfo(settings.WECHAT_TIMEZONE)).date()
    record = await daily_learning_record_service.refresh(db, sid, target_date)
    return DailyLearningRecordItem.model_validate(record)


@router.get("", response_model=list[DailyLearningRecordItem] | DailyLearningRecordItem)
def api_list(
    student_id: int | None = None,
    date: date | None = Query(default=None, description="单日查询；与 start_date/end_date 二选一"),
    start_date: date | None = Query(default=None, description="范围起始（含）"),
    end_date: date | None = Query(default=None, description="范围结束（含）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DailyLearningRecordItem] | DailyLearningRecordItem:
    """查每日学习记录。

    - 单日：传 date，返回单条；无记录 -> 404（不自动创建）。
    - 范围：传 start_date + end_date，返回数组（按日期升序）；无记录 -> 空数组。
    student 只读自己的；parent 须指定 student_id 且只能读绑定学生。
    """
    sid = resolve_accessible_student_id(db, user, student_id)

    if date is not None:
        if start_date is not None or end_date is not None:
            raise HTTPException(status_code=400, detail="date 与 start_date/end_date 不能同时使用")
        record = daily_learning_record_service.get_by_date(db, student_id=sid, record_date=date)
        if record is None:
            raise HTTPException(status_code=404, detail="当日无学习记录")
        return DailyLearningRecordItem.model_validate(record)

    if start_date is None or end_date is None:
        raise HTTPException(status_code=400, detail="需提供 date 或 start_date+end_date")
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")
    records = daily_learning_record_service.list_by_range(db, student_id=sid, start_date=start_date, end_date=end_date)
    return [DailyLearningRecordItem.model_validate(r) for r in records]


# spec 5.1：除受控 refresh 外不开放任何前端写接口。PATCH/DELETE 带路径参数，若不显式注册，
# FastAPI 会因无匹配路由返回 404 而非 405，无法表达“方法不允许”的契约；故显式拒绝写。
@router.post("", status_code=405)
def api_create_not_allowed() -> None:
    """本 PR 只读，不开放创建接口。"""
    raise HTTPException(status_code=405, detail="本接口只读，不开放写入")


@router.patch("/{record_id}", status_code=405)
def api_update_not_allowed(record_id: int) -> None:
    """本 PR 只读，不开放覆盖事实快照接口。"""
    raise HTTPException(status_code=405, detail="本接口只读，不开放写入")


@router.delete("/{record_id}", status_code=405)
def api_delete_not_allowed(record_id: int) -> None:
    """本 PR 只读，不开放删除接口。"""
    raise HTTPException(status_code=405, detail="本接口只读，不开放写入")
