from typing import Any

import hmac

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import reveal_secret, settings
from app.database import get_db
from app.models.user import User
from app.core.auth import access_service
from app.utils.security import decode_access_token

bearer_scheme = HTTPBearer()


def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload: dict[str, Any] = decode_access_token(cred.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="无效的 token")
    user = db.get(User, payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def require_teacher(user: User = Depends(get_current_user)) -> User:
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="需要老师权限")
    return user


def require_student(user: User = Depends(get_current_user)) -> User:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="需要学生权限")
    return user


def require_internal_token(request: Request) -> None:
    """内部服务调用鉴权：X-Internal-Token 与内部 token 常量时间比对。

    浏览器入口不需要它；服务端到服务端（微信 bot、个人工作台）走这条。
    """
    expected = reveal_secret(settings.WECHAT_BOT_INTERNAL_TOKEN)
    if not expected or not hmac.compare_digest(request.headers.get("X-Internal-Token", ""), expected):
        raise HTTPException(status_code=403, detail="内部鉴权失败")


def require_wechat_enabled() -> None:
    if not settings.WECHAT_ENABLED:
        raise HTTPException(status_code=503, detail="此实例未启用微信集成")


def resolve_accessible_student_id(db: Session, user: User, student_id: int | None) -> int:
    """校验当前用户是否可访问目标学生，并返回最终 student_id。"""
    if user.role == "student":
        if student_id is not None and student_id != user.id:
            raise HTTPException(status_code=403, detail="只能访问自己的数据")
        return user.id
    if student_id is None:
        raise HTTPException(status_code=400, detail="老师需指定 student_id")
    if not access_service.teacher_can_access_student(db, user.id, student_id):
        raise HTTPException(status_code=403, detail="无权访问该学生")
    return student_id
