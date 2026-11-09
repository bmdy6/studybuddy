"""对话路由（P2 agent 化）。

提供会话管理 + SSE 流式对话端点。
工具调用过程通过 SSE 事件实时推给前端（learn-claude-code s02 的 print 可见性的 Web 等价物）。
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.models.chat import ChatSession
from app.models.user import User
from app.features.chat.schemas import CreateSessionRequest, MessageItem, RenameSessionRequest, SendMessageRequest, SessionItem
from app.features.chat.agent import run_agent_turn
from app.features.chat.sessions import (
    create_session,
    delete_session,
    get_messages,
    get_or_create_student_primary_session,
    get_or_create_task_session,
    get_session,
    list_sessions,
    rename_session,
    reset_main_context,
)
from app.core.auth import access_service
from app.models.p2 import StudyPlan, StudyPlanItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _to_session_item(session: ChatSession) -> SessionItem:
    return SessionItem(
        id=session.id,
        user_id=session.user_id,
        student_id=session.student_id,
        title=session.title,
        created_at=session.created_at.strftime("%Y-%m-%d %H:%M:%S") if session.created_at else "",
        session_type=session.session_type,
        mode=session.mode,
        plan_id=session.plan_id,
        plan_item_id=session.plan_item_id,
        status=session.status,
    )


@router.get("/sessions/primary", response_model=SessionItem)
def api_get_student_primary_session(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SessionItem:
    """获取或创建学生的长期主会话（学生身份专用）。

    辅导者调用返回 403，保留辅导者原有多会话能力。
    新学生第一次进入创建主会话；以后始终恢复同一个会话。
    """
    if user.role != "student":
        raise HTTPException(status_code=403, detail="仅学生可使用长期主会话")
    session = get_or_create_student_primary_session(db, user, mode=user.mode)
    return _to_session_item(session)


@router.post("/sessions", response_model=SessionItem, status_code=201)
def api_create_session(
    req: CreateSessionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SessionItem:
    try:
        session = create_session(db, user, req.student_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return _to_session_item(session)


@router.get("/sessions", response_model=list[SessionItem])
def api_list_sessions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SessionItem]:
    return list_sessions(db, user)


def _get_owned_session(db: Session, session_id: int, user: User) -> ChatSession:
    """会话归属 + 模式一致性校验（模式隔离 fail-closed，统一所有会话操作入口）。"""
    session = get_session(db, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    # task 会话跟计划项走（计划项属学习模式），不受用户当前模式切换影响
    if session.session_type != "task" and getattr(session, "mode", "study") != user.mode:
        raise HTTPException(status_code=409, detail="会话模式与当前模式不一致，请切换模式后重试")
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[MessageItem])
def api_get_messages(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MessageItem]:
    _get_owned_session(db, session_id, user)
    return get_messages(db, session_id)


def _sse_event(data: dict) -> str:
    """格式化一条 SSE 事件。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/sessions/{session_id}/messages")
async def api_send_message(
    session_id: int,
    req: SendMessageRequest | None = Body(default=None),
    content_query: str | None = Query(default=None, alias="content"),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """发消息并流式返回 agent 响应（SSE）。

    前端用 fetch + ReadableStream 读取 text/event-stream，因此消息正文走 JSON body，避免出现在 URL/query 日志里。
    """
    # 用独立 db session（async generator 生命周期需要）
    db = SessionLocal()

    try:
        session = _get_owned_session(db, session_id, user)
    except HTTPException:
        db.close()
        raise

    content = req.content if req else content_query
    # 冷启动自动触发会发空 content（前端 skipUserMessage）：允许空，agent 按注入的冷启动指令回话
    content = content or ""

    # 流期请求依赖 db 已 teardown，从独立 db 重取稳定 user 实例，避免 detached
    stream_user = db.get(User, user.id)

    async def event_stream() -> AsyncGenerator[str, None]:
        # agent_loop 的 emit 回调把事件写入队列，这里消费
        queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

        async def emit_to_queue(evt_type: str, data: dict[str, Any]) -> None:
            await queue.put((evt_type, data))

        # 跑 agent_loop（独立 task，避免 generator 阻塞）
        async def run_loop() -> None:
            try:
                final_assistant_content = await run_agent_turn(
                    db,
                    session,
                    stream_user,
                    content,
                    emit=emit_to_queue,
                    display_content=req.display_content if req else None,
                )
                await queue.put(("done", {"content": final_assistant_content}))
            except Exception as e:  # noqa: BLE001
                logger.exception("send_message SSE 流内异常 session=%s", session_id)
                await queue.put(("error", {"message": str(e)}))

        task = asyncio.create_task(run_loop())

        try:
            while True:
                evt_type, data = await queue.get()
                if evt_type == "done":
                    yield _sse_event({"type": "done", **data})
                    break
                elif evt_type == "error":
                    yield _sse_event({"type": "error", **data})
                    break
                else:
                    yield _sse_event({"type": evt_type, **data})
        finally:
            if not task.done():
                task.cancel()
            db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/context/reset", status_code=204)
def api_reset_main_context(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """清空当前会话的所有消息，开始全新对话（会话记录本身保留）。

    主会话与计划 task session 都可重置。
    """
    session = _get_owned_session(db, session_id, user)
    if user.role != "student":
        raise HTTPException(status_code=403, detail="仅学生可重置会话上下文")
    reset_main_context(db, session)


@router.patch("/sessions/{session_id}", response_model=SessionItem)
def api_rename_session(
    session_id: int,
    req: RenameSessionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SessionItem:
    """重命名会话标题（用户手动改名）。"""
    session = _get_owned_session(db, session_id, user)
    session = rename_session(db, session, req.title)
    return _to_session_item(session)


@router.delete("/sessions/{session_id}", status_code=204)
def api_delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除会话（连带删除其下消息，ChatMessage.session_id ondelete=CASCADE）。"""
    session = _get_owned_session(db, session_id, user)
    delete_session(db, session)


@router.post("/students/{student_id}/plan-items/{item_id}/continue")
async def api_continue_plan_item(
    student_id: int,
    item_id: int,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """继续某个计划项的学习：创建/恢复 task session 并触发 agent（U-042）。

    - 每个 plan_item_id 最多一个 task session（重开复用）。
    - 不要求学生再发消息，后端直接起一轮 agent 用任务启动提示开口。
    - 流式返回：先推 session 事件（task session 信息），再推 agent 事件，最后 done。

    用独立 db session 贯穿整个 SSE 流（与 send_message 一致）：请求依赖的 db/user 在
    StreamingResponse 返回后会被 teardown，若把请求期 ORM 对象捕获进闭包，
    get_or_create_task_session 的 commit（expire_on_commit）会使 user 过期，
    随后 agent 访问 user.role 即抛 DetachedInstanceError。
    """
    db = SessionLocal()
    try:
        # 权限校验（user.id/role 在请求期读取标量，安全）
        if user.role == "teacher":
            if not access_service.teacher_can_access_student(db, user.id, student_id):
                raise HTTPException(status_code=403, detail="无权为该学生继续任务")
        elif user.role == "student":
            if student_id != user.id:
                raise HTTPException(status_code=403, detail="不能为他人继续任务")

        item = db.get(StudyPlanItem, item_id)
        if not item or item.plan_id is None:
            raise HTTPException(status_code=404, detail="计划项不存在")
        plan = db.get(StudyPlan, item.plan_id)
        if not plan or plan.student_id != student_id:
            # 防越权：学生用自己的 student_id（过身份校验）+ 枚举别人 item_id 时，
            # 必须校验计划归属，否则会把他人计划标题/任务目标注入自己 task session。
            raise HTTPException(status_code=404, detail="计划项不存在")
        plan_title = plan.title
        # 流期请求依赖 db 已 teardown，从独立 db 重取稳定 user 实例，避免 detached
        stream_user = db.get(User, user.id)
        # 建/恢复 task session
        session = get_or_create_task_session(db, stream_user, student_id, item.plan_id, item_id)
        # 任务启动提示（作为本轮 agent 输入）
        content = f"继续学习「{plan_title}」里的「{item.title}」。请直接带我开始这个任务。"
    except HTTPException:
        db.close()
        raise
    except Exception:
        db.close()
        raise

    async def event_stream() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

        async def emit_to_queue(evt_type: str, data: dict[str, Any]) -> None:
            await queue.put((evt_type, data))

        async def run_loop() -> None:
            try:
                # 先推 task session 信息，前端据此切到 task 会话
                await queue.put(("session", {"session": _to_session_item(session).model_dump()}))
                final_assistant_content = await run_agent_turn(
                    db, session, stream_user, content, emit=emit_to_queue,
                )
                await queue.put(("done", {"content": final_assistant_content}))
            except Exception as e:  # noqa: BLE001
                logger.exception("continue SSE 流内异常 student=%s item=%s", student_id, item_id)
                await queue.put(("error", {"message": str(e)}))

        task = asyncio.create_task(run_loop())
        try:
            while True:
                evt_type, data = await queue.get()
                if evt_type == "done":
                    yield _sse_event({"type": "done", **data})
                    break
                elif evt_type == "error":
                    yield _sse_event({"type": "error", **data})
                    break
                else:
                    yield _sse_event({"type": evt_type, **data})
        finally:
            if not task.done():
                task.cancel()
            db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
