"""访问关系服务：维护内部身份与学生访问边界。"""

from typing import Literal

from sqlalchemy.orm import Session

from app.models.teacher_student import TeacherStudent
from app.models.user import User
from app.models.wechat import WECHAT_CHANNEL_ILINK_BOT, WechatAccount

BusinessActor = Literal["student", "channel_guardian", "coach"]


def resolve_business_actor(
    user: User, account: WechatAccount | None = None
) -> BusinessActor:
    """把内部角色解析成产品权限身份。"""
    if user.role == "student":
        return "student"
    if account and account.channel == WECHAT_CHANNEL_ILINK_BOT:
        return "channel_guardian"
    return "coach"


def bind_teacher_student(db: Session, teacher_id: int, student_id: int) -> TeacherStudent:
    """绑定一个家长和一个学生，已存在时直接返回原关系。"""
    existing = db.query(TeacherStudent).filter(TeacherStudent.teacher_id == teacher_id, TeacherStudent.student_id == student_id).first()
    if existing:
        return existing
    relation = TeacherStudent(teacher_id=teacher_id, student_id=student_id)
    db.add(relation)
    db.commit()
    db.refresh(relation)
    return relation


def teacher_can_access_student(db: Session, teacher_id: int, student_id: int) -> bool:
    """判断家长是否绑定并可管理指定学生。"""
    return db.query(TeacherStudent).filter(TeacherStudent.teacher_id == teacher_id, TeacherStudent.student_id == student_id).first() is not None


def list_accessible_students(db: Session, teacher_id: int) -> list[User]:
    """列出家长已绑定的学生账号。"""
    return (
        db.query(User)
        .join(TeacherStudent, TeacherStudent.student_id == User.id)
        .filter(TeacherStudent.teacher_id == teacher_id, User.role == "student")
        .order_by(User.id.asc())
        .all()
    )


def list_bound_teachers(db: Session, student_id: int) -> list[User]:
    """列出绑定某学生的家长账号，用于站内提醒同步给督促者。"""
    return (
        db.query(User)
        .join(TeacherStudent, TeacherStudent.teacher_id == User.id)
        .filter(TeacherStudent.student_id == student_id, User.role == "teacher")
        .order_by(User.id.asc())
        .all()
    )
