from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(min_length=6, max_length=64)


class ChildInfo(BaseModel):
    """家长端绑定的学生信息。"""

    id: int
    display_name: str
    mode: str = "study"


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: int
    role: str
    display_name: str
    avatar: str | None = None
    mode: str = "study"
    children: list[ChildInfo] = []


class UserProfile(BaseModel):
    """当前用户信息（GET /auth/me 返回）。"""

    user_id: int
    username: str
    role: str
    display_name: str
    avatar: str | None = None
    mode: str = "study"


class UpdateProfileRequest(BaseModel):
    """改个人资料（PATCH /auth/me）。"""

    display_name: str | None = Field(default=None, max_length=64)
    avatar: str | None = Field(default=None, max_length=512)
    mode: str | None = Field(default=None, pattern="^(study|hobby)$")


class ChangePasswordRequest(BaseModel):
    """改密码（PUT /auth/me/password）。"""

    old_password: str
    new_password: str = Field(min_length=6, max_length=64)
