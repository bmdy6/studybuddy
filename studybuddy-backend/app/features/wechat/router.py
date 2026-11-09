from __future__ import annotations

import logging
from html import escape
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.config import reveal_secret, settings
from app.database import get_db
# 内部服务调用鉴权统一在 deps（家庭任务集成入口共用同一套 X-Internal-Token）
from app.deps import get_current_user, require_internal_token as _ensure_internal_token, require_wechat_enabled
from app.models.wechat import WECHAT_CHANNEL_ILINK_BOT, WECHAT_CHANNEL_OFFICIAL_ACCOUNT
from app.models.user import User
from app.features.wechat import accounts, guardian, inbound, messaging, report_progress as report_progress_service
from app.features.wechat.schemas import (
    WechatAccountResponse,
    WechatBindSessionResponse,
    WechatGuardianContextResponse,
    WechatGuardianSettingsResponse,
    WechatGuardianContextUpdate,
    WechatIlinkAccountItem,
    WechatIlinkAccountsResponse,
    WechatIlinkMessageRequest,
    WechatIlinkMessageResponse,
    WechatParentInvitationResponse,
)

router = APIRouter(prefix="/api/channels/wechat", tags=["wechat"], dependencies=[Depends(require_wechat_enabled)])
internal_router = APIRouter(prefix="/api/internal/channels/wechat/ilink", tags=["wechat-internal"], dependencies=[Depends(require_wechat_enabled)])
logger = logging.getLogger(__name__)


def _passive_text(to_user: str, from_user: str, content: str) -> Response:
    safe_content = escape(content)
    xml = (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        "<CreateTime>0</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{safe_content}]]></Content>"
        "</xml>"
    )
    return Response(content=xml, media_type="application/xml")


def _parse_message(raw: bytes) -> dict[str, str]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise HTTPException(status_code=400, detail="微信消息 XML 无效")
    result: dict[str, str] = {}
    for child in root:
        result[child.tag] = child.text or ""
    return result


def _ensure_signature(signature: str, timestamp: str, nonce: str) -> None:
    if not messaging.is_valid_signature(reveal_secret(settings.WECHAT_TOKEN), signature, timestamp, nonce):
        raise HTTPException(status_code=403, detail="微信签名校验失败")


@router.post("/bind-sessions", response_model=WechatBindSessionResponse)
def create_bind_session(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WechatBindSessionResponse:
    try:
        return accounts.create_bind_session(
            db, user, channel=WECHAT_CHANNEL_ILINK_BOT
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="微信连接服务暂不可用，请稍后再试",
        ) from exc


@router.post("/guardian-invitations", response_model=WechatBindSessionResponse)
def create_guardian_invitation(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WechatBindSessionResponse:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="只有学生可以邀请家长")
    try:
        return accounts.create_guardian_invitation(db, user)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="微信连接服务暂不可用，请稍后再试",
        ) from exc


@router.get("/bind-sessions/{session_id}", response_model=WechatBindSessionResponse)
def get_bind_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WechatBindSessionResponse:
    session = accounts.get_bind_session(db, session_id)
    belongs_to_user = session and (
        session.user_id == user.id or session.invited_by_user_id == user.id
    )
    if not belongs_to_user:
        raise HTTPException(status_code=404, detail="绑定会话不存在")
    try:
        session = accounts.get_bind_session(db, session_id, refresh_provider=True)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="微信连接服务暂不可用，请稍后再试",
        ) from exc
    if not session:
        raise HTTPException(status_code=404, detail="绑定会话不存在")
    return session


@router.get("/account", response_model=WechatAccountResponse)
def get_account(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WechatAccountResponse:
    account = accounts.get_active_account(db, user.id, channel=WECHAT_CHANNEL_ILINK_BOT)
    if not account:
        return WechatAccountResponse(bound=False)
    return WechatAccountResponse(
        bound=True,
        openid_masked=messaging.mask_openid(account.openid),
        bound_at=account.bound_at,
    )


@router.get("/guardian-contexts", response_model=list[WechatGuardianContextResponse])
def list_guardian_contexts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WechatGuardianContextResponse]:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="只有学生可以查看家庭陪伴")
    items = []
    # guardian_user 而非 guardian：避免覆盖上方导入的 guardian 子模块（约束同 p2 interests 重命名）
    for context, account, guardian_user in guardian.list_guardian_contexts_for_student(
        db, user
    ):
        summary = guardian.get_latest_guardian_growth_summary(
            db, guardian_user.id, user.id
        )
        items.append(
            WechatGuardianContextResponse(
                id=context.id,
                guardian_name=guardian_user.display_name or "微信家长",
                openid_masked=messaging.mask_openid(account.openid),
                push_time=context.push_time,
                paused=context.paused,
                status=context.status,
                latest_summary_title=summary.title if summary else None,
                latest_summary_content=summary.content if summary else None,
                latest_summary_created_at=summary.created_at if summary else None,
            )
        )
    return items


@router.post("/report-progress")
def report_progress(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """学生主动把当日学习摘要发给家长微信。"""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="只有学生可以向家长报进度")
    try:
        return report_progress_service.send_student_progress_to_guardians(db, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/guardian-settings", response_model=WechatGuardianSettingsResponse)
def get_guardian_settings(
    user: User = Depends(get_current_user),
) -> WechatGuardianSettingsResponse:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="只有学生可以查看家庭陪伴")
    options, default = guardian.get_guardian_push_time_config()
    return WechatGuardianSettingsResponse(
        push_time_options=options,
        default_push_time=default,
    )


@router.patch(
    "/guardian-contexts/{context_id}", response_model=WechatGuardianContextResponse
)
def update_guardian_context(
    context_id: int,
    payload: WechatGuardianContextUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WechatGuardianContextResponse:
    try:
        row = guardian.update_guardian_context(
            db,
            user,
            context_id,
            push_time=payload.push_time,
            paused=payload.paused,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="家庭陪伴关系不存在")
    context, account, guardian_user = row
    summary = guardian.get_latest_guardian_growth_summary(
        db, guardian_user.id, user.id
    )
    return WechatGuardianContextResponse(
        id=context.id,
        guardian_name=guardian_user.display_name or "微信家长",
        openid_masked=messaging.mask_openid(account.openid),
        push_time=context.push_time,
        paused=context.paused,
        status=context.status,
        latest_summary_title=summary.title if summary else None,
        latest_summary_content=summary.content if summary else None,
        latest_summary_created_at=summary.created_at if summary else None,
    )


@router.delete("/guardian-contexts/{context_id}", status_code=204, response_class=Response)
def unbind_guardian_context(
    context_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    if not guardian.unbind_guardian_context(db, user, context_id):
        raise HTTPException(status_code=404, detail="家庭陪伴关系不存在")
    return Response(status_code=204)


@router.get(
    "/parent-invitations/{scene}", response_model=WechatParentInvitationResponse
)
def get_parent_invitation(
    scene: str, db: Session = Depends(get_db)
) -> WechatParentInvitationResponse:
    invitation = accounts.get_parent_invitation(db, scene)
    if not invitation:
        raise HTTPException(status_code=404, detail="家长邀请不存在")
    session, parent, student = invitation
    return WechatParentInvitationResponse(
        parent_name=parent.display_name or parent.username,
        student_name=student.display_name or student.username,
        bind_code=session.bind_code,
        qr_value=session.qr_value,
        status=session.status,
        expires_at=session.expires_at,
    )


@router.delete("/account", status_code=204, response_class=Response)
def unbind_account(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    account = accounts.get_active_account(
        db, user.id, channel=WECHAT_CHANNEL_ILINK_BOT
    )
    accounts.unbind_account(db, user, channel=WECHAT_CHANNEL_ILINK_BOT)
    if account:
        try:
            accounts.revoke_ilink_user(
                account.provider_account_id or "", account.openid
            )
        except Exception:
            logger.warning("微信学习助手白名单撤销失败，将在下次入站消息自愈", exc_info=True)
        else:
            accounts.clear_ilink_revocation_pending(
                db, account.provider_account_id or "", account.openid
            )
    return Response(status_code=204)


@internal_router.post("/messages", response_model=WechatIlinkMessageResponse)
def receive_ilink_message(
    payload: WechatIlinkMessageRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> WechatIlinkMessageResponse:
    _ensure_internal_token(request)
    content = payload.content.strip()
    account = accounts.record_interaction(
        db,
        payload.ilink_user_id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id=payload.provider_account_id,
    )
    user = db.get(User, account.user_id) if account else None
    pending_bind = accounts.get_pending_bind_session_by_code(db, content)
    if pending_bind:
        try:
            accounts.complete_bind_by_code(
                db,
                content,
                payload.ilink_user_id,
                channel=WECHAT_CHANNEL_ILINK_BOT,
                provider_account_id=payload.provider_account_id,
            )
        except ValueError as exc:
            return WechatIlinkMessageResponse(reply=f"绑定失败：{exc}")
        bound_account = accounts.get_active_account_by_openid(
            db,
            payload.ilink_user_id,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id=payload.provider_account_id,
        )
        reply = (
            guardian.build_guardian_onboarding_prompt()
            if pending_bind.purpose == "guardian_invite"
            and bound_account
            and bound_account.guardian_onboarding_status == "awaiting_push_time"
            else "绑定成功"
        )
        return WechatIlinkMessageResponse(
            reply=reply, persist_credentials=True, activate_user=True
        )
    if not account and accounts.has_pending_ilink_revocation(
        db, payload.provider_account_id, payload.ilink_user_id
    ):
        return WechatIlinkMessageResponse(reply="绑定已解除", deactivate_user=True)
    onboarding_reply = guardian.handle_guardian_onboarding_choice(db, account, content)
    if onboarding_reply is not None:
        return WechatIlinkMessageResponse(reply=onboarding_reply)
    if account:
        if content == "邀请家长" and user and user.role == "student":
            return WechatIlinkMessageResponse(
                reply=accounts.create_parent_invitation_reply(db, user)
            )
    parent_reply = guardian.handle_parent_command(db, account, content)
    if parent_reply is not None:
        return WechatIlinkMessageResponse(reply=parent_reply)
    if account and user and user.role == "student":
        background_tasks.add_task(
            inbound.process_student_agent_message,
            account.id,
            content,
        )
        return WechatIlinkMessageResponse(reply="")
    if account and user and user.role == "teacher":
        context, guardian_reply = guardian.resolve_guardian_message_target(
            db, account, content
        )
        if guardian_reply is not None:
            return WechatIlinkMessageResponse(reply=guardian_reply)
        background_tasks.add_task(
            inbound.process_guardian_agent_message,
            account.id,
            context.student_id,
            content,
        )
        return WechatIlinkMessageResponse(reply="")
    try:
        accounts.complete_bind_by_code(
            db,
            content,
            payload.ilink_user_id,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id=payload.provider_account_id,
        )
    except ValueError as exc:
        return WechatIlinkMessageResponse(reply=f"绑定失败：{exc}")
    return WechatIlinkMessageResponse(
        reply="绑定成功", persist_credentials=True, activate_user=True
    )


@internal_router.get("/accounts", response_model=WechatIlinkAccountsResponse)
def list_ilink_accounts(
    request: Request, db: Session = Depends(get_db)
) -> WechatIlinkAccountsResponse:
    _ensure_internal_token(request)
    accounts_list = accounts.list_active_ilink_accounts(db)
    return WechatIlinkAccountsResponse(
        accounts=[
            WechatIlinkAccountItem(
                provider_account_id=provider_account_id,
                ilink_user_ids=sorted(
                    account.openid
                    for account in accounts_list
                    if account.provider_account_id == provider_account_id
                ),
            )
            for provider_account_id in sorted(
                accounts.list_known_ilink_provider_account_ids(db)
            )
        ]
    )


@router.get("/callback")
def verify_callback(
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
) -> Response:
    _ensure_signature(signature, timestamp, nonce)
    return Response(content=echostr, media_type="text/plain")


@router.post("/callback")
async def receive_callback(
    request: Request,
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    db: Session = Depends(get_db),
) -> Response:
    _ensure_signature(signature, timestamp, nonce)
    msg = _parse_message(await request.body())
    to_user = msg.get("FromUserName", "")
    from_user = msg.get("ToUserName", "")
    account = accounts.record_interaction(db, to_user, channel=WECHAT_CHANNEL_OFFICIAL_ACCOUNT)
    if msg.get("MsgType") != "text":
        return _passive_text(to_user, from_user, "已收到。当前微信公众号先支持发送绑定码完成账号绑定。")

    content = msg.get("Content", "").strip()
    parent_reply = guardian.handle_parent_command(db, account, content)
    if parent_reply is not None:
        return _passive_text(to_user, from_user, parent_reply)
    user = db.get(User, account.user_id) if account else None
    if account and user and user.role == "student":
        return _passive_text(to_user, from_user, "已绑定。学习问题请发送给微信学习助手。")
    try:
        accounts.complete_bind_by_code(
            db, content, to_user, channel=WECHAT_CHANNEL_OFFICIAL_ACCOUNT
        )
    except ValueError as exc:
        return _passive_text(to_user, from_user, f"绑定失败：{exc}")
    return _passive_text(to_user, from_user, "绑定成功。以后可以在微信里接收学习提醒，复杂操作仍回到网页完成。")
