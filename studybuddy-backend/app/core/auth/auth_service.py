from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from .schemas import ChildInfo, LoginResponse, UserProfile
from . import access_service
from app.utils.security import create_access_token, hash_password, verify_password


class UsernameAlreadyExistsError(ValueError):
    """注册用户名与现有账号冲突。"""


def login(db: Session, username: str, password: str) -> LoginResponse:
    """校验账号密码并返回登录态。"""
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.web_login_enabled or not verify_password(password, user.password_hash):
        raise ValueError("用户名或密码错误")
    return create_login_response(db, user)


def register(db: Session, username: str, password: str) -> LoginResponse:
    """创建学生账号并直接签发现有登录态。"""
    normalized_username = username.strip()
    if not normalized_username:
        raise ValueError("用户名不能为空")
    if db.query(User).filter(User.username == normalized_username).first():
        raise UsernameAlreadyExistsError("用户名已被使用")

    user = User(
        username=normalized_username,
        password_hash=hash_password(password),
        role="student",
        display_name=normalized_username,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise UsernameAlreadyExistsError("用户名已被使用") from exc
    db.refresh(user)
    return create_login_response(db, user)


def create_login_response(db: Session, user: User) -> LoginResponse:
    """为已完成身份校验的用户签发登录态。"""
    token = create_access_token(user.id, user.role, expires_hours=settings.JWT_REMEMBER_LOGIN_HOURS)
    children = _list_children(db, user.id) if user.role == "teacher" else []
    return LoginResponse(
        access_token=token,
        expires_in=settings.JWT_REMEMBER_LOGIN_HOURS * 3600,
        user_id=user.id,
        role=user.role,
        display_name=user.display_name or user.username,
        avatar=user.avatar,
        mode=user.mode,
        children=children,
    )


def _list_children(db: Session, teacher_id: int) -> list[ChildInfo]:
    """列出家长端可管理的学生。"""
    students = access_service.list_accessible_students(db, teacher_id)
    return [ChildInfo(id=s.id, display_name=s.display_name or s.username, mode=s.mode) for s in students]


def get_profile(user: User) -> UserProfile:
    """当前用户信息。display_name 回退到 username，避免前端显示空。"""
    return UserProfile(
        user_id=user.id,
        username=user.username,
        role=user.role,
        display_name=user.display_name or user.username,
        avatar=user.avatar,
        mode=user.mode,
    )


def update_profile(db: Session, user: User, display_name: str | None, avatar: str | None, mode: str | None = None) -> UserProfile:
    """改个人资料。仅更新传入的字段。"""
    if display_name is not None:
        name = display_name.strip()
        user.display_name = name if name else None
    if avatar is not None:
        user.avatar = avatar.strip() or None
    if mode is not None:
        user.mode = mode
    db.commit()
    return get_profile(user)


def change_password(db: Session, user: User, old_password: str, new_password: str) -> None:
    """改密码。校验旧密码，新密码 hash 后覆盖。"""
    if not verify_password(old_password, user.password_hash):
        raise ValueError("旧密码错误")
    user.password_hash = hash_password(new_password)
    db.commit()
