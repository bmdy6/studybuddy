"""兴趣空间安全工具：密码 hash + JWT。

模仿底座 app/utils/security.py，但用 hobbybuddy 自己的 JWT_SECRET（独立密钥，不跨应用通用）。
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from hobby.config import settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: int, expires_hours: int | None = None) -> str:
    hours = expires_hours or settings.secrets.JWT_EXPIRE_HOURS
    payload = {
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
    }
    return jwt.encode(payload, settings.secrets.JWT_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.secrets.JWT_SECRET, algorithms=["HS256"])
