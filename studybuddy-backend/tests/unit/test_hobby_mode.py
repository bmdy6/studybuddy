"""兴趣模式（hobby）单元测试：工具集 + 提示词 + 模式切换驱动。"""

import pytest

from app.features.agent.tools import HOBBY_TOOLS, STUDENT_TOOLS, tools_for_actor
from app.prompts.agent import system_prompt


def test_hobby_tools_includes_search_and_keeps_study_tools():
    """兴趣模式工具集 = 学习工具全保留 + search_hobby_resource。"""
    names = {t["name"] for t in HOBBY_TOOLS}
    assert "search_hobby_resource" in names
    # 用户要求：目前学科工具都保留（笔记/计划/素材/记录等可复用）
    study_names = {t["name"] for t in STUDENT_TOOLS}
    assert study_names.issubset(names)


def test_tools_for_actor_hobby_mode():
    tools = tools_for_actor("student", "hobby")
    names = {t["name"] for t in tools}
    assert "search_hobby_resource" in names
    assert "save_note" in names  # 学习工具仍在


def test_tools_for_actor_study_mode_unaffected():
    tools = tools_for_actor("student")
    names = {t["name"] for t in tools}
    assert "search_hobby_resource" not in names


def test_system_prompt_hobby_mode():
    prompt = system_prompt("student", "hobby")
    assert "兴趣陪伴" in prompt
    assert "不判分" in prompt or "不判分、不打分" in prompt


def test_system_prompt_study_mode_unaffected():
    prompt = system_prompt("student")
    assert "兴趣陪伴" not in prompt


def test_primary_session_isolated_by_mode(db, client):
    """同学生 study/hobby 各有一个主会话，互不串上下文。"""
    from app.features.chat.sessions import get_or_create_student_primary_session
    from app.models.user import User

    student = db.query(User).filter(User.role == "student").first()
    assert student is not None

    s_study = get_or_create_student_primary_session(db, student, mode="study")
    s_hobby = get_or_create_student_primary_session(db, student, mode="hobby")
    assert s_study.id != s_hobby.id
    assert s_study.mode == "study"
    assert s_hobby.mode == "hobby"

    # 再次获取返回同一会话（不重复创建）
    s_study2 = get_or_create_student_primary_session(db, student, mode="study")
    s_hobby2 = get_or_create_student_primary_session(db, student, mode="hobby")
    assert s_study2.id == s_study.id
    assert s_hobby2.id == s_hobby.id


def _student_token(client):
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_primary_session_router_respects_user_mode(db, client):
    """路由层：GET /sessions/primary 按 user.mode 返回对应模式主会话（hobby 用户拿 hobby 会话）。"""
    from app.models.user import User

    student = db.query(User).filter(User.role == "student").first()
    student.mode = "hobby"
    db.commit()

    token = _student_token(client)
    r = client.get("/api/chat/sessions/primary", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "hobby"


def test_send_message_rejects_mode_mismatch(real_client):
    """fail-closed：向其他模式的会话发消息被拒（409），防跨模式串上下文。"""
    import uuid

    from app.database import SessionLocal
    from app.models.chat import ChatMessage, ChatSession
    from app.models.user import User

    username = f"isolate_{uuid.uuid4().hex[:8]}"
    r = real_client.post("/auth/register", json={"username": username, "password": "test123456"})
    assert r.status_code == 201, r.text
    user_id = r.json()["user_id"]
    token = r.json()["access_token"]
    try:
        sid = real_client.get("/api/chat/sessions/primary", headers={"Authorization": f"Bearer {token}"}).json()["id"]
        real_client.patch("/auth/me", json={"mode": "hobby"}, headers={"Authorization": f"Bearer {token}"})
        r2 = real_client.post(
            f"/api/chat/sessions/{sid}/messages",
            json={"content": "hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 409, r2.text
    finally:
        with SessionLocal() as db:
            db.query(ChatMessage).filter(ChatMessage.session_id == sid).delete()
            db.query(ChatSession).filter(ChatSession.user_id == user_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.commit()


# ---------- 数据隔离（计划/笔记按模式）----------

def test_study_plan_isolation_by_mode(db):
    """同学生 study/hobby 计划互不可见：列表按 mode 过滤。"""
    from app.features.p2 import study_plan
    from app.models.user import User

    student = db.query(User).filter(User.role == "student").first()
    assert student is not None

    # 创建 study + hobby 各一个计划
    study_plan.create_study_plan(
        db, student.id, "数学复习", [study_plan.StudyPlanItemInput(title="做练习", minutes=15)],
        mode="study",
    )
    db.commit()
    study_plan.create_study_plan(
        db, student.id, "唱歌练习", [study_plan.StudyPlanItemInput(title="练气息", minutes=15)],
        mode="hobby",
    )
    db.commit()

    study_plans = study_plan.list_study_plans(db, student.id, status=None, mode="study")
    hobby_plans = study_plan.list_study_plans(db, student.id, status=None, mode="hobby")
    assert all(p.mode == "study" for p in study_plans)
    assert all(p.mode == "hobby" for p in hobby_plans)
    # 互不包含
    assert not any("唱歌" in p.title for p in study_plans)
    assert not any("数学" in p.title for p in hobby_plans)


def test_note_isolation_by_mode(db):
    """同学生 study/hobby 笔记互不可见。"""
    from app.features.note import service as note_service
    from app.models.user import User

    student = db.query(User).filter(User.role == "student").first()
    note_service.create_note(
        db, {"student_id": student.id, "title": "数学错题", "content": "x", "status": "confirmed"}, mode="study"
    )
    db.commit()
    note_service.create_note(
        db, {"student_id": student.id, "title": "唱歌心得", "content": "y", "status": "confirmed"}, mode="hobby"
    )
    db.commit()

    study_notes = note_service.list_notes(db, student.id, status="confirmed", mode="study")
    hobby_notes = note_service.list_notes(db, student.id, status="confirmed", mode="hobby")
    assert not any("唱歌" in n.title for n in study_notes)
    assert not any("数学" in n.title for n in hobby_notes)


def test_hobby_context_skips_learning_memory(monkeypatch, db):
    """hobby 模式主会话不注入学习记忆/每日记录/错题上下文（防学科记忆污染兴趣对话）。"""
    import asyncio

    from unittest.mock import AsyncMock, patch

    from app.core import ai_service
    from app.features.agent import agent_loop
    from app.models.user import User

    student = db.query(User).filter(User.role == "student").first()
    student.mode = "hobby"
    db.commit()

    captured_systems: list[str] = []
    turn_results: list[str] = []

    def fake_profile(db, sid, text, mode="study"):
        return "\n[画像] 八年级学生，兴趣：唱歌"

    def fake_daily(db, sid):
        return "\n[每日记录] 今天做了数学练习"

    def fake_memory(db, sid, text):
        return "\n[学习记忆] 错题：一元二次方程"

    def fake_error_import(messages):
        return "\n[错题导入] 上传了数学错题"

    monkeypatch.setattr(agent_loop, "_build_profile_context", fake_profile)
    monkeypatch.setattr(agent_loop, "_build_daily_learning_record_context", fake_daily)
    monkeypatch.setattr(agent_loop, "_build_learning_memory_context", fake_memory)
    monkeypatch.setattr(agent_loop, "_build_error_import_context", fake_error_import)

    async def fake_stream(**kwargs):
        # 捕获 system 内容（agent_loop 单独传 system 参数）
        if kwargs.get("system"):
            captured_systems.append(kwargs["system"])
        # 返回纯文本流：content + finish，结束循环
        turn_results.append("好的，你想学什么？")
        class _Delta:
            content = "好的，你想学什么？"
            tool_calls = None  # 纯文本回复，无工具调用
        class _Choice:
            delta = _Delta()
            finish_reason = "stop"
        class _Chunk:
            choices = [_Choice()]
            usage = None
        yield _Chunk()

    with patch.object(ai_service, "call_llm_stream", side_effect=fake_stream):
        from app.features.chat import agent as chat_agent
        from app.features.chat.sessions import get_or_create_student_primary_session

        session = get_or_create_student_primary_session(db, student, mode="hobby")
        result = asyncio.run(
            chat_agent.run_agent_turn(
                db, session, student, "我想学唱歌",
            )
        )

    assert captured_systems, "应捕获到 system"
    hobby_system = captured_systems[0]
    assert "[画像]" in hobby_system
    assert "[学习记忆]" not in hobby_system
    assert "[每日记录]" not in hobby_system
    assert "[错题导入]" not in hobby_system
    # 回合真正成功：LLM 被调用且正文非空（mock 未触发重试/降级）
    assert turn_results


def test_profile_context_split_by_mode(monkeypatch, db):
    """hobby 画像只注入基础身份（年级/学校/兴趣），跳过学科档案/薄弱科目/教材版本。"""
    from app.features.agent import context

    class _Snapshot(dict):
        pass

    class _Attr:
        snapshot = {
            "grade": "八年级",
            "school": "某中学",
            "weak_subjects": ["数学"],
            "textbook_versions": {"数学": "人教版"},
            "engagement": "高",
            "mastered_count": 5,
        }

    class _AttrService:
        @staticmethod
        def get_latest_attributes(db, sid):
            return _Attr()

    def fake_summary(db, sid):
        class _S:
            needs_onboarding = False
        return _S()

    def fake_interests(db, sid):
        class _I:
            tag = "唱歌"
            approved = True
        return [_I()]

    monkeypatch.setattr(context.profile, "get_profile_summary", fake_summary)
    monkeypatch.setattr(context.attribute, "get_latest_attributes", _AttrService.get_latest_attributes)
    monkeypatch.setattr(context.interests, "list_interests", fake_interests)

    study_ctx = context._build_profile_context(db, 1, mode="study")
    hobby_ctx = context._build_profile_context(db, 1, mode="hobby")

    # 公共基础身份都在
    assert "八年级" in study_ctx and "八年级" in hobby_ctx
    assert "唱歌" in study_ctx and "唱歌" in hobby_ctx
    # 学科档案/薄弱科目/教材版本：study 有，hobby 无
    assert "薄弱科目" in study_ctx
    assert "薄弱科目" not in hobby_ctx
    assert "教材版本" in study_ctx
    assert "教材版本" not in hobby_ctx
    assert "学习档案" in study_ctx
    assert "学习档案" not in hobby_ctx
