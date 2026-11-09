"""M1：草案会话归属与相关性测试（方案 2.3.1）。

覆盖：服务端注入真实 chat_session_id（模型伪造被覆盖）、tool 结果与 API 返回
归属/created_at/is_expired、跨学生隔离、legacy null、过期、当前 pending。
前端"四条件恢复"依赖这里的归属和过期判定，属于 M1 验收的后端半段。
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.core import ai_service
from app.models import StudyPlanDraft
from app.models.user import User
from app.features.chat import agent, sessions


def _chunk(content=None, tool_call=None, finish=None):
    delta = MagicMock()
    delta.content = content
    delta.reasoning_content = None
    delta.tool_calls = None
    if tool_call is not None:
        tc = MagicMock()
        tc.index = tool_call.get("index", 0)
        tc.id = tool_call.get("id")
        tc.function = MagicMock()
        tc.function.name = tool_call.get("name")
        tc.function.arguments = tool_call.get("arguments")
        delta.tool_calls = [tc]
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


async def _async_iter(items):
    for item in items:
        yield item


def _mock_tool_stream(tool_name, tool_input, text=""):
    args_str = json.dumps(tool_input, ensure_ascii=False)
    chunks = []
    if text:
        chunks.append(_chunk(content=text))
    chunks.append(_chunk(tool_call={"index": 0, "id": "call_1", "name": tool_name, "arguments": ""}))
    chunks.append(_chunk(tool_call={"index": 0, "id": None, "name": None, "arguments": args_str}))
    chunks.append(_chunk(finish="tool_calls"))
    return _async_iter(chunks)


def _mock_text_stream(text):
    return _async_iter([_chunk(content=text), _chunk(finish="stop")])


def _draft_args(**overrides):
    args = {
        "student_id": 2,
        "title": "语文阅读理解训练",
        "items": [{"title": "练一篇记叙文阅读", "minutes": 20}],
    }
    args.update(overrides)
    return args


def _make_draft(db, student_id=2, chat_session_id=None, status="pending", expires_at=None):
    d = StudyPlanDraft(
        student_id=student_id,
        chat_session_id=chat_session_id,
        draft_data={"title": "数学复习", "items": [{"title": "复习概念", "minutes": 20}]},
        revision=1,
        status=status,
        expires_at=expires_at,
    )
    db.add(d)
    db.flush()
    return d


def _auth_token(client):
    return client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]


class TestServerSideSessionInjection:
    """服务端注入真实 chat_session_id，模型伪造值被覆盖。"""

    def test_model_forged_chat_session_id_is_overridden_by_server(self, db):
        student = db.get(User, 2)
        session = sessions.create_session(db, student, student.id)
        streams = [
            _mock_tool_stream("draft_study_plan", _draft_args(chat_session_id=999)),  # 模型伪造
            _mock_text_stream("已生成语文草案卡，请确认。"),
        ]
        events: list[tuple[str, dict]] = []

        async def collect(evt_type, data):
            events.append((evt_type, data))

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
            asyncio.run(
                agent.run_agent_turn(
                    db, session, student, "今天学语文阅读理解，20分钟，练记叙文", emit=collect
                )
            )

        draft = (
            db.query(StudyPlanDraft)
            .filter(StudyPlanDraft.student_id == 2)
            .order_by(StudyPlanDraft.id.desc())
            .first()
        )
        assert draft is not None
        assert draft.chat_session_id == session.id  # 服务端注入真实会话
        assert draft.chat_session_id != 999  # 模型伪造值被覆盖
        # tool_result 输出返回真实归属和创建时间，前端据此建立当前卡
        result_events = [
            d for t, d in events if t == "tool_result" and d.get("name") == "draft_study_plan"
        ]
        assert result_events
        output = json.loads(result_events[-1]["output"])
        assert output["chat_session_id"] == session.id
        assert output["created_at"]

    def test_draft_tool_output_carries_ownership_fields(self, db):
        """handler 直接调用时，返回 chat_session_id/created_at 且落库一致。"""
        from app.features.agent.handlers.learning import _handle_draft_study_plan

        result = asyncio.run(_handle_draft_study_plan(_draft_args(chat_session_id=77), "student", db, 1))
        assert result.get("drafted") is True
        assert result.get("chat_session_id") == 77
        assert result.get("created_at")
        draft = db.get(StudyPlanDraft, result["draft_id"])
        assert draft.chat_session_id == 77


class TestPlanDraftRelevanceApi:
    """草案详情 API 的归属与过期语义。"""

    def test_api_returns_ownership_and_is_expired_for_current_pending(self, client, db):
        draft = _make_draft(db, chat_session_id=42)
        r = client.get(
            f"/api/study-plan-drafts/{draft.id}",
            headers={"Authorization": f"Bearer {_auth_token(client)}"},
        )
        assert r.status_code == 200
        body = r.json()
        # 当前 pending：归属明确 + 未过期 + 有创建时间，前端四条件可恢复当前卡
        assert body["status"] == "pending"
        assert body["chat_session_id"] == 42
        assert body["is_expired"] is False
        assert body["created_at"]

    def test_api_legacy_null_chat_session_id(self, client, db):
        """旧草案 chat_session_id=null：只能成为历史提示，不能恢复当前卡。"""
        draft = _make_draft(db, chat_session_id=None)
        r = client.get(
            f"/api/study-plan-drafts/{draft.id}",
            headers={"Authorization": f"Bearer {_auth_token(client)}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["chat_session_id"] is None
        assert body["is_expired"] is False
        assert body["created_at"]

    def test_api_expired_draft_is_expired_true(self, client, db):
        past = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(minutes=1)
        draft = _make_draft(db, chat_session_id=42, expires_at=past)
        r = client.get(
            f"/api/study-plan-drafts/{draft.id}",
            headers={"Authorization": f"Bearer {_auth_token(client)}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "pending"
        assert body["is_expired"] is True  # 服务端计算，前端不猜时区

    def test_api_future_expiry_not_expired(self, client, db):
        future = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) + timedelta(minutes=29)
        draft = _make_draft(db, chat_session_id=42, expires_at=future)
        r = client.get(
            f"/api/study-plan-drafts/{draft.id}",
            headers={"Authorization": f"Bearer {_auth_token(client)}"},
        )
        assert r.status_code == 200
        assert r.json()["is_expired"] is False

    def test_api_cross_student_draft_404(self, client, db):
        draft = _make_draft(db, student_id=999, chat_session_id=42)
        r = client.get(
            f"/api/study-plan-drafts/{draft.id}",
            headers={"Authorization": f"Bearer {_auth_token(client)}"},
        )
        assert r.status_code == 404  # 跨学生隔离：归属查不到

    def test_api_created_draft_not_recoverable(self, client, db):
        """已确认创建的草案：前端不得恢复当前卡，也不显示历史提示。"""
        draft = _make_draft(db, chat_session_id=42, status="created")
        r = client.get(
            f"/api/study-plan-drafts/{draft.id}",
            headers={"Authorization": f"Bearer {_auth_token(client)}"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "created"
