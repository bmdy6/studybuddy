"""兴趣空间鉴权：注册 + 登录 + 当前用户。

模仿底座 auth，但无 teacher/student 角色（兴趣空间单一学习者角色）。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hobby.config import settings
from hobby.database import get_db
from hobby.models import User
from hobby.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    expires_in: int
    user_id: int
    display_name: str


def _login_response(db: Session, user: User) -> LoginResponse:
    hours = settings.secrets.JWT_REMEMBER_LOGIN_HOURS
    return LoginResponse(
        access_token=create_access_token(user.id, expires_hours=hours),
        expires_in=hours * 3600,
        user_id=user.id,
        display_name=user.display_name or user.username,
    )


@router.post("/register", response_model=LoginResponse, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)) -> LoginResponse:
    username = req.username.strip()
    if not username or len(req.password) < 6:
        raise HTTPException(status_code=400, detail="用户名不能为空，密码至少 6 位")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="用户名已被使用")
    user = User(
        username=username,
        password_hash=hash_password(req.password),
        display_name=username,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已被使用") from None
    db.refresh(user)
    return _login_response(db, user)


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.username == req.username.strip()).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _login_response(db, user)
