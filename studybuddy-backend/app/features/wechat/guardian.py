from __future__ import annotations

import logging
import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.models.chat import ChatSession
from app.models.notification import Notification
from app.models.teacher_student import TeacherStudent
from app.models.user import User
from app.models.wechat import (
    WECHAT_CHANNEL_ILINK_BOT,
    WECHAT_CHANNEL_OFFICIAL_ACCOUNT,
    WechatAccount,
    WechatGuardianStudentContext,
)
from app.core.auth import access_service
from app.features.growth import supervision_service, guardian_today
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.features.chat import sessions
from app.features.wechat.messaging import send_ilink_text

logger = logging.getLogger(__name__)


def get_guardian_push_time_config() -> tuple[list[str], str]:
    options = [value.strip() for value in settings.WECHAT_GUARDIAN_PUSH_TIME_OPTIONS.split(",") if value.strip()]
    default = settings.WECHAT_GUARDIAN_DEFAULT_PUSH_TIME.strip()
    if len(options) != 2 or len(set(options)) != 2 or default in options:
        raise RuntimeError("家长推送时间配置无效")
    try:
        for value in [*options, default]:
            datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise RuntimeError("家长推送时间配置无效") from exc
    return options, default


def build_guardian_onboarding_prompt(student_name: str | None = None) -> str:
    options, default = get_guardian_push_time_config()
    lines = []
    if student_name:
        lines.append(f"正在修改{student_name}的成长摘要时间。")
    lines.append("你希望什么时候收到孩子的成长摘要？请选择下面一项，回复对应编号或时间。")
    lines.extend(f"{index}. 晚上 {value}" for index, value in enumerate(options, 1))
    lines.append(f"{len(options) + 1}. 保持默认（{default}）")
    return "\n".join(lines)


def get_or_create_guardian_chat_session(db: Session, context: WechatGuardianStudentContext, guardian: User) -> ChatSession:
    session = db.get(ChatSession, context.chat_session_id) if context.chat_session_id else None
    if session and session.user_id == guardian.id and session.student_id == context.student_id:
        return session
    session = sessions.create_session(db, guardian, context.student_id)
    session.title = "微信家庭陪伴"
    context.chat_session_id = session.id
    db.commit()
    db.refresh(session)
    return session


def _active_guardian_contexts(db: Session, account: WechatAccount) -> list[tuple[WechatGuardianStudentContext, User]]:
    rows = (
        db.query(WechatGuardianStudentContext, User)
        .join(User, User.id == WechatGuardianStudentContext.student_id)
        .filter(
            WechatGuardianStudentContext.account_id == account.id,
            WechatGuardianStudentContext.status == "active",
            User.role == "student",
        )
        .order_by(WechatGuardianStudentContext.id.asc())
        .all()
    )
    return [row for row in rows if access_service.teacher_can_access_student(db, account.user_id, row[0].student_id)]


def resolve_guardian_message_target(db: Session, account: WechatAccount, content: str) -> tuple[WechatGuardianStudentContext | None, str | None]:
    rows = _active_guardian_contexts(db, account)
    if not rows:
        account.selected_student_id = None
        db.commit()
        return None, "当前没有已绑定学生"

    names = [student.display_name or student.username for _, student in rows]
    normalized = content.strip()
    selected_index: int | None = None
    if normalized.isdigit() and 1 <= int(normalized) <= len(rows):
        selected_index = int(normalized) - 1
    else:
        exact_matches = [index for index, name in enumerate(names) if normalized == name]
        if len(exact_matches) == 1:
            selected_index = exact_matches[0]

    if selected_index is not None:
        context, student = rows[selected_index]
        account.selected_student_id = context.student_id
        db.commit()
        return (
            None,
            f"已切换到{student.display_name or student.username}，可以继续问我孩子最近的学习情况。",
        )

    selected = next(
        (context for context, _ in rows if context.student_id == account.selected_student_id),
        None,
    )
    if selected:
        return selected, None
    if len(rows) == 1:
        account.selected_student_id = rows[0][0].student_id
        db.commit()
        return rows[0][0], None

    account.selected_student_id = None
    db.commit()
    menu = "\n".join(["你想查看哪个孩子？", *(f"{index}. {name}" for index, name in enumerate(names, 1))])
    return None, menu


def _is_guardian_today_learning_query(content: str) -> bool:
    normalized = re.sub(r"\s+", "", content)
    if not normalized:
        return False
    if any(period in normalized for period in ("昨天", "本周", "这周", "最近")) and not any(
        period in normalized for period in ("今天", "今日")
    ):
        return False
    has_today = any(period in normalized for period in ("今天", "今日"))
    # 时长类（多久/多长时间/学习时长）必须配合"今天/今日"才命中，
    # 否则"明天要学多久""考试要准备多久"会被误答成今天学习时长。
    if has_today and any(keyword in normalized for keyword in ("多久", "多长时间", "学习时长")):
        return True
    return has_today and any(
        keyword in normalized
        for keyword in ("学了什么", "学习了什么", "学习内容", "学习的内容", "做了什么", "学什么", "学得怎么样")
    )


def build_parent_daily_summary(db: Session, teacher_id: int) -> str:
    """基于现有督促数据生成家长可读的确定性今日摘要。"""
    students = access_service.list_accessible_students(db, teacher_id)
    if not students:
        return "当前没有已绑定学生"
    sections: list[str] = []
    for student in students:
        summary = supervision_service.build_supervision_summary(db, student.id)
        todo_count = sum(item.todo_count for item in summary.reminders)
        todo_minutes = sum(item.todo_minutes for item in summary.reminders)
        lines = [f"{summary.student_name or student.username}今日学情"]
        today_text = guardian_today.build_guardian_today_learning_summary(db, student.id)
        lines.append(today_text.replace("今天学习 ", "自报学习时长：", 1))
        lines.append(f"待完成任务：{todo_count} 项，预计 {todo_minutes} 分钟" if todo_count else "待完成任务：暂无")
        lines.append("薄弱点：" + "、".join(item.tag for item in summary.weak_points[:2]) if summary.weak_points else "薄弱点：暂无新增记录")
        lines.append(f"每日回顾：{summary.support_items[0].content}" if summary.support_items else "每日回顾：暂无记录")
        latest_exam = (
            db.query(ExamRecord, Exam)
            .join(Exam, Exam.id == ExamRecord.exam_id)
            .filter(ExamRecord.student_id == student.id, ExamRecord.status.in_(["submitted", "graded"]))
            .order_by(ExamRecord.submitted_at.desc(), ExamRecord.id.desc())
            .first()
        )
        if latest_exam:
            record, exam = latest_exam
            score = f"{record.total_score.normalize():f} 分" if record.status == "graded" and record.total_score is not None else "待批改"
            lines.append(f"最近试卷：{exam.title}（{score}）")
        elif summary.recent_assignments:
            assignment = summary.recent_assignments[0]
            lines.append(f"最近试卷：{assignment.exam_title}（{assignment.status}）")
        else:
            lines.append("最近试卷：暂无记录")
        # Suggestions are sentences upstream; this line owns separators and the final stop.
        suggestions = [
            item.tag + "：" + item.next_action.rstrip("。；;.!！?？ \t\r\n")
            for item in summary.weak_points[:2]
        ]
        lines.append("明天建议：" + "；".join(suggestions) + "。" if suggestions else "明天建议：先回看今天的记录，再确定下一项任务。")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def handle_parent_command(db: Session, account: WechatAccount | None, content: str) -> str | None:
    """处理家长查询与提醒配置指令，非家长指令返回 None。"""
    if content != "今日学情" and content != "关闭提醒" and not content.startswith("提醒"):
        return None
    user = db.get(User, account.user_id) if account else None
    if not account or not user or user.role != "teacher":
        return "请先发送家长绑定码完成绑定"
    if not access_service.list_accessible_students(db, user.id):
        return "家长账号尚未绑定学生"
    if account.channel == WECHAT_CHANNEL_ILINK_BOT and content == "今日学情":
        return None
    if content == "今日学情":
        return build_parent_daily_summary(db, user.id)
    if account.channel == WECHAT_CHANNEL_ILINK_BOT:
        return "推送设置请由学生在 Web 的家庭陪伴中修改。"
    if content == "关闭提醒":
        account.reminder_times = None
        db.commit()
        return "学习提醒已关闭"

    values = content.split()[1:]
    if not values:
        return "提醒格式：提醒 09:00 20:30"
    try:
        reminder_times = sorted({datetime.strptime(value, "%H:%M").strftime("%H:%M") for value in values})
    except ValueError:
        return "提醒格式：提醒 09:00 20:30"
    account.reminder_times = reminder_times
    db.commit()
    return "提醒时间已设置：" + "、".join(reminder_times)


def handle_guardian_onboarding_choice(db: Session, account: WechatAccount | None, content: str) -> str | None:
    if not account:
        return None
    user = db.get(User, account.user_id)
    if not user or user.role != "teacher":
        return None
    selected_context = (
        db.query(WechatGuardianStudentContext)
        .filter(
            WechatGuardianStudentContext.account_id == account.id,
            WechatGuardianStudentContext.student_id == account.selected_student_id,
            WechatGuardianStudentContext.status == "active",
        )
        .first()
    )
    if account.guardian_onboarding_status == "completed":
        if content.strip() not in {"修改推送时间", "修改时间"}:
            return None
        if not selected_context:
            rows = _active_guardian_contexts(db, account)
            if len(rows) > 1:
                account.guardian_onboarding_status = "awaiting_push_time"
                account.selected_student_id = None
                db.commit()
                names = [student.display_name or student.username for _, student in rows]
                return "\n".join(
                    [
                        "你想修改哪个孩子的成长摘要时间？",
                        *(f"{index}. {name}" for index, name in enumerate(names, 1)),
                    ]
                )
            selected_context = rows[0][0] if rows else None
        if not selected_context:
            return "当前没有已绑定学生"
        account.selected_student_id = selected_context.student_id
        account.guardian_onboarding_status = "awaiting_push_time"
        db.commit()
        student = db.get(User, selected_context.student_id)
        return build_guardian_onboarding_prompt(student.display_name or student.username if student else None)
    if not selected_context:
        rows = _active_guardian_contexts(db, account)
        if not rows:
            account.guardian_onboarding_status = "completed"
            db.commit()
            return "当前没有已绑定学生"
        names = [student.display_name or student.username for _, student in rows]
        normalized = content.strip()
        selected_index: int | None = None
        if normalized.isdigit() and 1 <= int(normalized) <= len(rows):
            selected_index = int(normalized) - 1
        else:
            exact_matches = [index for index, name in enumerate(names) if normalized == name]
            if len(exact_matches) == 1:
                selected_index = exact_matches[0]
        if selected_index is None:
            return "\n".join(
                [
                    "你想修改哪个孩子的成长摘要时间？",
                    *(f"{index}. {name}" for index, name in enumerate(names, 1)),
                ]
            )
        selected_context, student = rows[selected_index]
        account.selected_student_id = selected_context.student_id
        db.commit()
        return build_guardian_onboarding_prompt(student.display_name or student.username)
    student = db.get(User, selected_context.student_id)
    student_name = student.display_name or student.username if student else "该学生"
    options, default = get_guardian_push_time_config()
    choices = {str(index): value for index, value in enumerate(options, 1)}
    choices[str(len(options) + 1)] = default
    normalized = content.strip()
    push_time = choices.get(normalized)
    # 提示文案承诺"回复对应编号或时间"：直接回复精确 HH:MM（命中选项/默认值集合）也接受
    if not push_time and normalized in {*options, default}:
        push_time = normalized
    if not push_time:
        return build_guardian_onboarding_prompt(student_name)
    account.guardian_default_push_time = push_time
    account.guardian_onboarding_status = "completed"
    selected_context.push_time = push_time
    db.commit()
    return f"已将{student_name}的成长摘要设置为每天 {push_time} 推送。"


def list_guardian_contexts_for_student(db: Session, student: User) -> list[tuple[WechatGuardianStudentContext, WechatAccount, User]]:
    if student.role != "student":
        return []
    rows = (
        db.query(WechatGuardianStudentContext, WechatAccount, User)
        .join(WechatAccount, WechatAccount.id == WechatGuardianStudentContext.account_id)
        .join(User, User.id == WechatAccount.user_id)
        .filter(
            WechatGuardianStudentContext.student_id == student.id,
            WechatGuardianStudentContext.status == "active",
            WechatAccount.status == "active",
            User.role == "teacher",
        )
        .order_by(WechatGuardianStudentContext.id.asc())
        .all()
    )
    return [row for row in rows if access_service.teacher_can_access_student(db, row[2].id, student.id)]


def get_guardian_context_for_student(db: Session, student: User, context_id: int) -> tuple[WechatGuardianStudentContext, WechatAccount, User] | None:
    row = (
        db.query(WechatGuardianStudentContext, WechatAccount, User)
        .join(WechatAccount, WechatAccount.id == WechatGuardianStudentContext.account_id)
        .join(User, User.id == WechatAccount.user_id)
        .filter(
            WechatGuardianStudentContext.id == context_id,
            WechatGuardianStudentContext.student_id == student.id,
            WechatGuardianStudentContext.status == "active",
            WechatAccount.status == "active",
            User.role == "teacher",
        )
        .first()
    )
    if not row or not access_service.teacher_can_access_student(db, row[2].id, student.id):
        return None
    return row


def get_latest_guardian_growth_summary(db: Session, guardian_id: int, student_id: int) -> Notification | None:
    return (
        db.query(Notification)
        .filter(
            Notification.recipient_id == guardian_id,
            Notification.student_id == student_id,
            Notification.source_type == "growth_summary",
        )
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .first()
    )


def update_guardian_context(
    db: Session,
    student: User,
    context_id: int,
    *,
    push_time: str | None,
    paused: bool | None,
) -> tuple[WechatGuardianStudentContext, WechatAccount, User] | None:
    row = get_guardian_context_for_student(db, student, context_id)
    if not row:
        return None
    if push_time is None and paused is None:
        raise ValueError("没有需要修改的设置")
    context, account, guardian = row
    if push_time is not None:
        options, default = get_guardian_push_time_config()
        if push_time not in {*options, default}:
            raise ValueError("不支持该推送时间")
        context.push_time = push_time
    if paused is not None:
        context.paused = paused
    db.commit()
    student_name = student.display_name or student.username
    message = f"{student_name}的成长摘要推送已暂停。" if context.paused else f"{student_name}的成长摘要将在每天 {context.push_time} 推送。"
    if account.provider_account_id:
        try:
            send_ilink_text(account.provider_account_id, account.openid, message)
        except Exception:
            logger.warning("家长设置变更通知发送失败", exc_info=True)
    return context, account, guardian


def unbind_guardian_context(db: Session, student: User, context_id: int) -> bool:
    row = get_guardian_context_for_student(db, student, context_id)
    if not row:
        return False
    context, account, guardian = row
    context.status = "unbound"
    context.paused = True
    if account.selected_student_id == student.id:
        account.selected_student_id = None
    db.commit()
    remaining = (
        db.query(WechatGuardianStudentContext.id)
        .join(WechatAccount, WechatAccount.id == WechatGuardianStudentContext.account_id)
        .filter(
            WechatAccount.user_id == guardian.id,
            WechatGuardianStudentContext.student_id == student.id,
            WechatGuardianStudentContext.status == "active",
        )
        .first()
    )
    if not remaining:
        db.query(TeacherStudent).filter(
            TeacherStudent.teacher_id == guardian.id,
            TeacherStudent.student_id == student.id,
        ).delete(synchronize_session=False)
        db.commit()
    if account.provider_account_id:
        try:
            send_ilink_text(
                account.provider_account_id,
                account.openid,
                f"已解除与{student.display_name or student.username}的家庭陪伴绑定。",
            )
        except Exception:
            logger.warning("家长解绑通知发送失败", exc_info=True)
    return True
