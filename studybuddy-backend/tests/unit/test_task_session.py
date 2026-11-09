"""task session 单测（U-042）：计划项独立学习会话。

覆盖：
- get_or_create_task_session 首次创建 + 重复调用复用同一会话。
- 不同计划项得到不同 task session，互不串线。
- task session 字段正确（session_type/plan_id/plan_item_id，无 primary_student_id）。
"""

import pytest

from app.models.chat import ChatSession
from app.models.p2 import StudyPlan, StudyPlanItem
from app.models.user import User
from app.features.chat import sessions
from app.utils.security import hash_password


def _make_student(db, username="task-student") -> User:
    student = User(
        username=username,
        password_hash=hash_password("x"),
        role="student",
        display_name=username,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _make_plan_item(db, student_id):
    plan = StudyPlan(student_id=student_id, title="英语时态", focus="一般过去时")
    db.add(plan)
    db.commit()
    db.refresh(plan)
    item = StudyPlanItem(plan_id=plan.id, title="复盘错题", target="说出2个错因", minutes=15)
    db.add(item)
    db.commit()
    db.refresh(item)
    return plan, item


class TestTaskSession:
    def test_get_or_create_task_session_creates_and_reuses(self, db):
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        s1 = sessions.get_or_create_task_session(db, student, student.id, item.plan_id, item.id)
        assert s1.session_type == "task"
        assert s1.plan_id == item.plan_id
        assert s1.plan_item_id == item.id
        assert s1.primary_student_id is None  # task session 不属于主会话
        # 重复调用复用同一会话
        s2 = sessions.get_or_create_task_session(db, student, student.id, item.plan_id, item.id)
        assert s2.id == s1.id

    def test_different_items_get_different_sessions(self, db):
        student = _make_student(db)
        plan, item1 = _make_plan_item(db, student.id)
        item2 = StudyPlanItem(plan_id=plan.id, title="做5道题", target="全对", minutes=20)
        db.add(item2)
        db.commit()
        db.refresh(item2)
        s1 = sessions.get_or_create_task_session(db, student, student.id, plan.id, item1.id)
        s2 = sessions.get_or_create_task_session(db, student, student.id, plan.id, item2.id)
        assert s1.id != s2.id
        assert s1.plan_item_id == item1.id
        assert s2.plan_item_id == item2.id

    def test_task_session_does_not_touch_primary_session(self, db):
        """建 task session 不影响学生主会话。"""
        student = _make_student(db)
        primary = sessions.get_or_create_student_primary_session(db, student)
        _, item = _make_plan_item(db, student.id)
        task = sessions.get_or_create_task_session(db, student, student.id, item.plan_id, item.id)
        assert task.id != primary.id
        assert task.session_type == "task"
        assert primary.session_type == "main"

    def test_build_task_context_injects_plan_and_item(self, db):
        """_build_task_context 注入计划说明 + 任务目标 + 相关知识点。"""
        from app.features.agent.context import _build_task_context

        student = _make_student(db)
        plan, item = _make_plan_item(db, student.id)

        class _FakeSession:
            student_id = student.id
            plan_id = plan.id
            plan_item_id = item.id

        ctx = _build_task_context(db, _FakeSession())
        assert "英语时态" in ctx
        assert "复盘错题" in ctx
        assert "说出2个错因" in ctx

    def test_run_agent_turn_uses_current_user_role(self, db):
        """P1-4：task session 角色取当前 user.role，不取 session.role_at_create。

        teacher 先建的 task session，学生继续时 agent 应以 student 角色跑，
        不能拿到 teacher 工具集（如 search_paper_sources）。
        """
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app.features.chat.agent import run_agent_turn
        from app.features.chat import sessions as chat_sessions

        teacher = db.get(User, 1)  # seeded teacher
        student = db.get(User, 2)  # seeded student（与 _make_student 不同，保证是测试基线账号）
        assert teacher is not None and student is not None
        plan, item = _make_plan_item(db, student.id)
        # teacher 先建 task session（role_at_create=teacher）
        task_session = chat_sessions.get_or_create_task_session(
            db, teacher, student.id, item.plan_id, item.id
        )
        assert task_session.role_at_create == "teacher"

        captured = {}

        async def fake_loop(**kwargs):
            captured["role"] = kwargs.get("role")
            captured["teacher_id"] = kwargs.get("teacher_id")
            return []  # 不追加新消息

        with patch("app.features.agent.agent_loop.agent_loop", new=AsyncMock(side_effect=fake_loop)):
            asyncio.run(run_agent_turn(db, task_session, student, "开始"))

        # 当前操作者是 student，角色应取 user.role=student，而非 session.role_at_create=teacher
        assert captured["role"] == "student"
        assert captured["teacher_id"] == student.id
