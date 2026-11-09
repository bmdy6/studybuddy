from datetime import datetime

from pydantic import BaseModel, Field


class WechatBindSessionResponse(BaseModel):
    id: int
    bind_code: str
    qr_value: str
    status: str
    expires_at: datetime
    bound_at: datetime | None = None

    model_config = {"from_attributes": True}


class WechatAccountResponse(BaseModel):
    bound: bool
    openid_masked: str | None = None
    bound_at: datetime | None = None


class WechatGuardianContextResponse(BaseModel):
    id: int
    guardian_name: str
    openid_masked: str
    push_time: str
    paused: bool
    status: str
    latest_summary_title: str | None = None
    latest_summary_content: str | None = None
    latest_summary_created_at: datetime | None = None


class WechatGuardianContextUpdate(BaseModel):
    push_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    paused: bool | None = None


class WechatGuardianSettingsResponse(BaseModel):
    push_time_options: list[str]
    default_push_time: str


class WechatParentInvitationResponse(BaseModel):
    parent_name: str
    student_name: str
    bind_code: str
    qr_value: str
    status: str
    expires_at: datetime


class WechatIlinkMessageRequest(BaseModel):
    provider_account_id: str = Field(min_length=1)
    ilink_user_id: str = Field(min_length=1)
    content: str = Field(min_length=1)


class WechatIlinkMessageResponse(BaseModel):
    reply: str
    persist_credentials: bool = False
    activate_user: bool = False
    deactivate_user: bool = False


class WechatIlinkAccountItem(BaseModel):
    provider_account_id: str
    ilink_user_ids: list[str]


class WechatIlinkAccountsResponse(BaseModel):
    accounts: list[WechatIlinkAccountItem]
