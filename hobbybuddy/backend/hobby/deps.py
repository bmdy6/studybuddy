"""兴趣空间依赖：当前用户解析（JWT）。"""

from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

from hobby.database import get_db
from hobby.models import User
from hobby.security import decode_access_token

bearer_scheme = HTTPBearer()


def get_current_user(
    cred=Depends(bearer_scheme),
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
