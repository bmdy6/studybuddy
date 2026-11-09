from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import reveal_secret, settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: int, role: str, expires_hours: int | None = None) -> str:
    hours = expires_hours or settings.JWT_EXPIRE_HOURS
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
    }
    return jwt.encode(payload, reveal_secret(settings.JWT_SECRET), algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, reveal_secret(settings.JWT_SECRET), algorithms=["HS256"])
