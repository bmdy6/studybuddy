from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from .schemas import ChangePasswordRequest, LoginRequest, LoginResponse, RegisterRequest, UpdateProfileRequest, UserProfile
from .auth_service import UsernameAlreadyExistsError, change_password, get_profile, login, register, update_profile

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def api_login(req: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    try:
        return login(db, req.username, req.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/register", response_model=LoginResponse, status_code=201)
def api_register(req: RegisterRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """创建学生账号并直接返回登录态。"""
    try:
        return register(db, req.username, req.password)
    except UsernameAlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me", response_model=UserProfile)
def api_get_profile(user: User = Depends(get_current_user)) -> UserProfile:
    """当前用户信息（个人中心用）。"""
    return get_profile(user)


@router.patch("/me", response_model=UserProfile)
def api_update_profile(
    req: UpdateProfileRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserProfile:
    """改个人资料（显示名/头像）。"""
    return update_profile(db, user, req.display_name, req.avatar, mode=req.mode)


@router.put("/me/password", status_code=204)
def api_change_password(
    req: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """改密码。"""
    try:
        change_password(db, user, req.old_password, req.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
