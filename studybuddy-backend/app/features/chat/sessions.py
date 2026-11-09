"""对话会话 CRUD + 标题。

会话生命周期: 学生长期主会话 (唯一, primary_student_id 唯一约束 + IntegrityError
并发保护) / 教师-学生会话 / 标题自动命名。消息读取视图 get_messages 归此 (会话数据
访问同簇); 消息写入 (persist_message) 归 agent (编排)。

拆自 app/services/chat_service.py。DAG: sessions <- agent (run_agent_turn 调 maybe_auto_title)。
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.chat.legacy_markdown_repair import repair_legacy_markdown
from app.features.chat.schemas import MessageItem, SessionItem
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.core.auth import access_service


STUDENT_PRIMARY_SESSION_TITLE = "学习对话"


def get_or_create_student_primary_session(db: Session, user: User, mode: str = "study") -> ChatSession:
    """获取或创建学生的长期主会话（按模式隔离：study/hobby 各自主会话）。

    - 学生身份专用：辅导者不应调用此入口（路由层拒绝）。
    - 新学生第一次进入：创建主会话，primary_student_id = 学生 id。
    - 老学生已有多个会话：按 updated_at desc, id desc 认领最新一条作为主会话。
    - 重复请求：返回同一个主会话，不产生多个。
    - 并发保护：依赖 chat_sessions.primary_student_id 的唯一约束（MySQL 5.7 UNIQUE
      索引允许多个 NULL，但保证一名学生最多一个主会话）。冲突方回滚本次事务后重新读取
      已存在主会话；不使用 SELECT FOR UPDATE 锁不存在的会话行，也不只靠 service 先查后写。

    不合并消息、不删除旧会话、不迁移正式聊天内容。
    """
    if user.role != "student":
        raise PermissionError("仅学生可使用长期主会话")

    student_id = user.id

    # 1. 已有主会话直接返回（命中已存在 primary_student_id）。
    existing = (
        db.query(ChatSession)
        .filter(
            ChatSession.primary_student_id == student_id,
            ChatSession.student_id == student_id,
            ChatSession.mode == mode,
        )
        .first()
    )
    if existing:
        return existing

    # 2. 老学生多会话：按 updated_at desc, id desc 认领最新一条学生自己的会话。
    candidate = _select_primary_candidate(db, student_id, mode)

    try:
        if candidate is not None:
            candidate.primary_student_id = student_id
            db.commit()
            db.refresh(candidate)
            return candidate

        # 3. 新学生：创建主会话并写入 primary_student_id。
        session = ChatSession(
            user_id=student_id,
            student_id=student_id,
            role_at_create="student",
            title=STUDENT_PRIMARY_SESSION_TITLE,
            primary_student_id=student_id,
            mode=mode,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session
    except IntegrityError:
        # 并发冲突：另一请求已为该学生写入 primary_student_id。
        # 回滚本次事务，重新读取已存在主会话。
        db.rollback()
        existing = (
            db.query(ChatSession)
            .filter(
                ChatSession.primary_student_id == student_id,
                ChatSession.mode == mode,
            )
            .first()
        )
        if existing:
            return existing
        # 理论上唯一约束冲突后必然存在主会话；若极端情况查不到则重新抛出，避免静默。
        raise


def _select_primary_candidate(db: Session, student_id: int, mode: str = "study") -> ChatSession | None:
    """从学生已有的学生角色会话中选最新一条作为主会话候选。

    规则：updated_at desc, id desc（确定性，不依赖时间戳精度）。
    只在学生自己发起的会话（user_id == student_id 且 role_at_create='student'）中选。
    """
    return (
        db.query(ChatSession)
        .filter(
            ChatSession.student_id == student_id,
            ChatSession.user_id == student_id,
            ChatSession.role_at_create == "student",
            ChatSession.primary_student_id.is_(None),
            ChatSession.mode == mode,
        )
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .first()
    )


def create_session(db: Session, user: User, student_id: int) -> ChatSession:
    """创建对话会话。student 发起时 student_id 必须是自己。"""
    if user.role == "student":
        return get_or_create_student_primary_session(db, user, mode=user.mode)

    actual_student_id = student_id if user.role == "teacher" else user.id
    if user.role == "teacher" and not access_service.teacher_can_access_student(db, user.id, student_id):
        raise PermissionError("无权为该学生创建会话")
    if user.role == "student" and student_id != user.id:
        # student 不能指定别人
        actual_student_id = user.id

    title = "新对话"
    session = ChatSession(
        user_id=user.id,
        student_id=actual_student_id,
        role_at_create=user.role,
        title=title,
        mode=user.mode,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_or_create_task_session(
    db: Session, user: User, student_id: int, plan_id: int, plan_item_id: int
) -> ChatSession:
    """获取或创建某个计划项的 task session（U-042）。

    - 每个 plan_item_id 最多一个 task session（唯一索引保证，重开复用）。
    - task session 不设 primary_student_id（不属于主会话）。
    - 辅导者创建时 student_id 用传入值，学生用自己的 id。
    """
    existing = (
        db.query(ChatSession)
        .filter(
            ChatSession.plan_item_id == plan_item_id,
            ChatSession.session_type == "task",
        )
        .first()
    )
    if existing:
        return existing
    actual_student_id = student_id if user.role == "teacher" else user.id
    session = ChatSession(
        user_id=user.id,
        student_id=actual_student_id,
        role_at_create=user.role,
        title="学习任务",
        session_type="task",
        mode="study",  # task 会话跟计划项走（计划项属学习模式），不随用户当前模式切换
        plan_id=plan_id,
        plan_item_id=plan_item_id,
        status="active",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_sessions(db: Session, user: User) -> list[SessionItem]:
    """列出当前用户的会话（按模式隔离：只列 user.mode 对应模式的会话）。"""
    q = db.query(ChatSession).filter(
        ChatSession.user_id == user.id,
        ChatSession.mode == user.mode,
    )
    sessions = q.order_by(ChatSession.updated_at.desc()).all()
    return [
        SessionItem(
            id=s.id,
            user_id=s.user_id,
            student_id=s.student_id,
            title=s.title,
            created_at=s.created_at.strftime("%Y-%m-%d %H:%M:%S") if s.created_at else "",
            session_type=s.session_type,
            mode=s.mode,
            plan_id=s.plan_id,
            plan_item_id=s.plan_item_id,
            status=s.status,
        )
        for s in sessions
    ]


def get_messages(db: Session, session_id: int) -> list[MessageItem]:
    """加载会话历史消息（转成 LLM 上下文格式由 router 处理）。

    展示层对旧 assistant 文本应用保守历史适配器（批次 2）：
    MiMo 偶发丢换行的历史消息（如 --- ### 标题挤一行）修复为规范 markdown。
    新消息已是渲染后规范文本，适配器幂等不破坏。
    """
    msgs = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.id).all()
    return [
        MessageItem(
            id=m.id,
            role=m.role,
            content=_repair_content_for_display(m),
            tool_calls=m.tool_calls,
            tool_result=m.tool_result,
            created_at=m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else "",
        )
        for m in msgs
    ]


def _repair_content_for_display(message: ChatMessage) -> str | None:
    """展示层历史适配：仅对 assistant 自由正文（无 tool_calls 的内容）应用修复。

    - assistant 且无 tool_calls：content 是正文，应用保守修复（幂等）。
    - 其余角色（user/tool）或带 tool_calls 的 assistant：原样返回。
    """
    if message.role == "assistant" and not message.tool_calls:
        return repair_legacy_markdown(message.content)
    return message.content


def get_session(db: Session, session_id: int) -> ChatSession | None:
    return db.get(ChatSession, session_id)


# 会话标题自动命名的截断长度（首条用户消息前若干字）
TITLE_MAX_LEN = 20


def auto_title(content: str) -> str:
    """根据首条用户消息生成会话标题：去空白截断，超长加省略号。

    不调 LLM，零额外成本/延迟（省 token 原则）。纯文本如「出5道英语定语从句」
    →「出5道英语定语从句」；长句 → 截断 + …。
    """
    text = (content or "").strip().replace("\n", " ")
    if not text:
        return "新对话"
    return text[:TITLE_MAX_LEN] + ("…" if len(text) > TITLE_MAX_LEN else "")


def maybe_auto_title(db: Session, session: ChatSession, user_content: str) -> bool:
    """若会话标题仍是默认「新对话」，用首条用户消息自动命名。返回是否更新。"""
    if session.title != "新对话":
        return False
    session.title = auto_title(user_content)
    db.commit()
    return True


def reset_main_context(db: Session, session: ChatSession) -> None:
    """清空当前会话的所有消息，开始全新对话（会话记录本身保留）。"""
    db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete(
        synchronize_session=False
    )
    session.context_summary = None
    session.context_summary_message_id = None
    db.commit()


def rename_session(db: Session, session: ChatSession, title: str) -> ChatSession:
    """重命名会话标题（前端用户手动改名用）。"""
    session.title = (title or "").strip()[:128] or "未命名会话"
    db.commit()
    db.refresh(session)
    return session


def delete_session(db: Session, session: ChatSession) -> None:
    """删除会话（连带删除其下消息，ChatMessage.session_id ondelete=CASCADE）。"""
    db.delete(session)
    db.commit()
