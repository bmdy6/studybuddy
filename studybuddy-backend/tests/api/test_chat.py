"""Chat router 集成测试（mock LLM，测 SSE 端点端到端）。

覆盖：
- 创建会话 → 201 + session_id
- 会话列表 → 200
- 未登录 → 401
- student 指定别的 student_id → 用自己 id
- SSE 发消息 → mock LLM 返回 text 事件（不依赖真实 LLM 配额）
- SSE 发消息 → mock LLM 返回 tool_call + tool_result + text 完整事件流
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core import ai_service
from app.main import app


async def _async_iter(items):
    """把普通 list 包成 async-iterable，供 `async for chunk in stream` 消费。

    call_llm_stream 改 async 后返回 AsyncStream，mock 需返回 async-iterable。
    """
    for item in items:
        yield item


def _teacher_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert r.status_code == 200
    return r.json()["access_token"]


def _teacher_token_and_child_id(client: TestClient) -> tuple[str, int]:
    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert r.status_code == 200
    data = r.json()
    assert data["children"], "teacher 测试账号必须至少绑定一个学生"
    return data["access_token"], data["children"][0]["id"]


def _student_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})
    assert r.status_code == 200
    return r.json()["access_token"]


def _mock_text_only(text: str = "你好"):
    """mock LLM 返回纯文本（OpenAI ChatCompletion 格式）。"""
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _chunk(content=None, reasoning=None, tool_call=None, finish=None):
    """构造流式 chunk（delta 含 content/reasoning_content/tool_calls）。"""
    delta = MagicMock()
    delta.content = content
    delta.reasoning_content = reasoning
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


def _mock_text_stream(text="测试回复"):
    """mock 流式纯文本（包成 async-iterable）：一个 content chunk + stop。"""
    return _async_iter([_chunk(content=text), _chunk(finish="stop")])


def _mock_present_response_stream(blocks):
    """mock 一次 present_response 工具调用流（结构化终态协议）。"""
    return _mock_tool_stream("present_response", {"blocks": blocks})


def _mock_tool_stream(name, args, text=""):
    """mock 流式工具调用（包成 async-iterable）：可选正文 + tool_call + finish。"""
    args_str = json.dumps(args, ensure_ascii=False)
    chunks = []
    if text:
        chunks.append(_chunk(content=text))
    chunks.append(_chunk(tool_call={"index": 0, "id": "c1", "name": name, "arguments": ""}))
    chunks.append(_chunk(tool_call={"index": 0, "id": None, "name": None, "arguments": args_str}))
    chunks.append(_chunk(finish="tool_calls"))
    return _async_iter(chunks)


class TestSessionManagement:
    """会话管理端到端。"""

    def test_create_session_teacher(self, client):
        token = _teacher_token(client)
        r = client.post("/api/chat/sessions", json={"student_id": 2}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201
        assert "id" in r.json()

    def test_create_session_student_uses_own_id(self, client):
        """student 指定 student_id 时实际用自己的 id。"""
        token = _student_token(client)
        r = client.post("/api/chat/sessions", json={"student_id": 999}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201

    def test_list_sessions(self, client):
        token = _teacher_token(client)
        client.post("/api/chat/sessions", json={"student_id": 2}, headers={"Authorization": f"Bearer {token}"})
        r = client.get("/api/chat/sessions", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_unauthenticated_rejected(self, client):
        r = client.post("/api/chat/sessions", json={"student_id": 2})
        assert r.status_code in (401, 403)  # 未认证拒绝

    def test_get_messages_empty_session(self, client):
        token = _teacher_token(client)
        create = client.post("/api/chat/sessions", json={"student_id": 2}, headers={"Authorization": f"Bearer {token}"})
        sid = create.json()["id"]
        r = client.get(f"/api/chat/sessions/{sid}/messages", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestSSEMessage:
    """SSE 发消息（mock LLM）。用 real_client：SSE 的 agent_loop 在异步 task 里
    用独立连接，看不到事务隔离里未提交的会话，需真实提交。"""

    def test_sse_returns_text_event(self, real_client):
        """mock LLM 返回纯文本 → SSE 推 text 事件。"""
        token, child_id = _teacher_token_and_child_id(real_client)
        sid = real_client.post("/api/chat/sessions", json={"student_id": child_id}, headers={"Authorization": f"Bearer {token}"}).json()["id"]

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, return_value=_mock_text_stream("测试回复")):
            r = real_client.post(
                f"/api/chat/sessions/{sid}/messages",
                json={"content": "hi"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        # SSE 响应含 text 事件
        assert "text" in r.text
        assert "测试回复" in r.text

    def test_sse_does_not_expose_reasoning_event(self, real_client):
        """mock LLM 返回 reasoning_content → SSE 不暴露 reasoning，只推结构化渲染正文并持久化。"""
        token, child_id = _teacher_token_and_child_id(real_client)
        sid = real_client.post("/api/chat/sessions", json={"student_id": child_id}, headers={"Authorization": f"Bearer {token}"}).json()["id"]
        stream = _async_iter([_chunk(reasoning="先分析"), _chunk(content="测试回复"), _chunk(finish="stop")])
        # 第一轮 reasoning+content（content 作自由正文会被协议拦截），第二轮 forced present_response
        present_stream = _mock_present_response_stream([{"type": "paragraph", "text": "测试回复"}])

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[stream, present_stream]):
            r = real_client.post(
                f"/api/chat/sessions/{sid}/messages",
                json={"content": "hi"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        assert '"type": "reasoning"' not in r.text
        assert "先分析" not in r.text
        assert "测试回复" in r.text

        messages = real_client.get(f"/api/chat/sessions/{sid}/messages", headers={"Authorization": f"Bearer {token}"}).json()
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["content"] == "测试回复\n"

    def test_sse_returns_tool_call_events(self, real_client):
        """mock LLM 返回 tool_use → SSE 推事件，并持久化工具调用历史。"""
        token, child_id = _teacher_token_and_child_id(real_client)
        sid = real_client.post("/api/chat/sessions", json={"student_id": child_id}, headers={"Authorization": f"Bearer {token}"}).json()["id"]

        # 第一轮返回 query_diagnosis tool_calls，第二轮返回结构化终态
        tool_stream = _mock_tool_stream("query_diagnosis", {"student_id": child_id, "top_n": 5})
        text_stream = _mock_present_response_stream([{"type": "paragraph", "text": "弟弟暂无错题"}])

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]):
            r = real_client.post(
                f"/api/chat/sessions/{sid}/messages",
                json={"content": "查诊断"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        assert "tool_call" in r.text
        assert "tool_result" in r.text
        assert "done" in r.text

        messages = real_client.get(f"/api/chat/sessions/{sid}/messages", headers={"Authorization": f"Bearer {token}"}).json()
        assert [m["role"] for m in messages[-4:]] == ["user", "assistant", "tool", "assistant"]

        tool_call_message = messages[-3]
        assert tool_call_message["tool_calls"][0]["id"] == "c1"
        assert tool_call_message["tool_calls"][0]["function"]["name"] == "query_diagnosis"

        tool_result_message = messages[-2]
        assert tool_result_message["tool_result"]["tool_call_id"] == "c1"
        assert tool_result_message["tool_result"]["name"] == "query_diagnosis"
        assert tool_result_message["content"]

        assert messages[-1]["content"] == "弟弟暂无错题\n"

    def test_sse_accepts_query_content_for_legacy_clients(self, real_client):
        """兼容旧客户端：query content 仍可发送，避免前后端短暂错版时聊天不可用。"""
        token, child_id = _teacher_token_and_child_id(real_client)
        sid = real_client.post("/api/chat/sessions", json={"student_id": child_id}, headers={"Authorization": f"Bearer {token}"}).json()["id"]

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, return_value=_mock_text_stream("兼容回复")):
            r = real_client.post(
                f"/api/chat/sessions/{sid}/messages?content=hi",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        assert "兼容回复" in r.text


class TestTaskSessionAuthz:
    """task session 越权防护（U-042 P1-1）。"""

    def test_continue_rejects_other_student_plan_item(self, client, db):
        """学生用自己的 student_id + 枚举别人 item_id 继续任务，应 404，不能读到他人计划内容。"""
        from app.models.p2 import StudyPlan, StudyPlanItem
        from app.models.user import User
        from app.utils.security import hash_password

        # 受害学生（非测试 student=2）
        victim = User(
            username="victim-student",
            password_hash=hash_password("x"),
            role="student",
            display_name="victim",
        )
        db.add(victim)
        db.commit()
        db.refresh(victim)
        plan = StudyPlan(student_id=victim.id, title="victim的英语", focus="定语从句")
        db.add(plan)
        db.commit()
        db.refresh(plan)
        item = StudyPlanItem(plan_id=plan.id, title="victim的复盘", target="错因", minutes=10)
        db.add(item)
        db.commit()
        db.refresh(item)

        # 攻击者：测试 student（id=2），用自己的 student_id 过身份校验，但传受害者的 item_id
        token = _student_token(client)
        r = client.post(
            f"/api/chat/students/2/plan-items/{item.id}/continue",
            headers={"Authorization": f"Bearer {token}"},
        )
        # 计划归属校验拦截，不泄漏 victim 计划标题/任务目标，返回 404
        assert r.status_code == 404


class TestContinuePlanItemSSE:
    """continue 端点 SSE 回归（bug1：独立 db + 流内重取 user，不应 DetachedInstanceError）。

    real_client 用真实库（非事务隔离），plan+item 必须用真实库建才能被读到；
    测试后精确清理 plan/item/task session，不污染开发库。
    """

    @staticmethod
    def _make_plan_item(student_id: int) -> tuple[int, int]:
        """用真实库建 plan+item，返回 (item_id, plan_id)。"""
        from app.database import SessionLocal
        from app.models.p2 import StudyPlan, StudyPlanItem

        db = SessionLocal()
        try:
            plan = StudyPlan(student_id=student_id, title="英语时态", focus="现在完成时")
            db.add(plan)
            db.commit()
            db.refresh(plan)
            item = StudyPlanItem(plan_id=plan.id, title="阅读理解", target="理解现在完成时", minutes=15)
            db.add(item)
            db.commit()
            db.refresh(item)
            return item.id, plan.id
        finally:
            db.close()

    @staticmethod
    def _cleanup(plan_id: int, item_id: int) -> None:
        from app.database import SessionLocal
        from app.models.chat import ChatSession
        from app.models.p2 import StudyPlan, StudyPlanItem

        db = SessionLocal()
        try:
            db.query(ChatSession).filter(ChatSession.plan_item_id == item_id).delete(synchronize_session=False)
            db.query(StudyPlanItem).filter(StudyPlanItem.id == item_id).delete(synchronize_session=False)
            db.query(StudyPlan).filter(StudyPlan.id == plan_id).delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def test_continue_first_time_builds_task_session_and_streams(self, real_client):
        """首次 continue 某 plan item：建 task session + SSE 推 session/text/done，无 DetachedInstanceError。"""
        token, child_id = _teacher_token_and_child_id(real_client)
        item_id, plan_id = self._make_plan_item(child_id)
        try:
            url = f"/api/chat/students/{child_id}/plan-items/{item_id}/continue"
            with patch.object(
                ai_service, "call_llm_stream", new_callable=AsyncMock,
                side_effect=lambda *a, **k: _mock_text_stream("我们开始学时态吧"),
            ):
                r = real_client.post(url, headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200, r.text
            body = r.text
            assert '"type": "session"' in body
            assert '"session_type": "task"' in body
            assert "我们开始学时态吧" in body
            assert '"type": "done"' in body
            # bug1 回归：不应出现 detached / DetachedInstanceError
            assert "DetachedInstanceError" not in body
            assert "not bound to a Session" not in body
        finally:
            self._cleanup(plan_id, item_id)

    def test_continue_reuse_existing_task_session(self, real_client):
        """同一 plan item 第二次 continue：复用 task session，仍正常流式。"""
        token, child_id = _teacher_token_and_child_id(real_client)
        item_id, plan_id = self._make_plan_item(child_id)
        try:
            url = f"/api/chat/students/{child_id}/plan-items/{item_id}/continue"
            with patch.object(
                ai_service, "call_llm_stream", new_callable=AsyncMock,
                side_effect=lambda *a, **k: _mock_text_stream("继续画图"),
            ):
                r1 = real_client.post(url, headers={"Authorization": f"Bearer {token}"})
                r2 = real_client.post(url, headers={"Authorization": f"Bearer {token}"})
            assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
            assert '"type": "done"' in r1.text
            assert '"type": "done"' in r2.text
            assert "DetachedInstanceError" not in r1.text
            assert "DetachedInstanceError" not in r2.text
        finally:
            self._cleanup(plan_id, item_id)


def _parse_sse_events(body: str) -> list[dict]:
    """把 SSE 响应体解析成事件列表。"""
    events: list[dict] = []
    for part in body.split("\n\n"):
        part = part.strip()
        if not part.startswith("data: "):
            continue
        events.append(json.loads(part[len("data: ") :]))
    return events


class TestM1DateAnchorAndFinalText:
    """M1：当前轮日期锚点只进 LLM 输入；done.content 与落库一致用校正后正文。"""

    def test_sse_injects_current_date_anchor_not_persisted(self, real_client):
        """锚点只进 LLM 输入，用户消息落库保持原文（不污染展示与历史）。"""
        from datetime import timedelta

        from app.features.agent import date_guard

        token, child_id = _teacher_token_and_child_id(real_client)
        sid = real_client.post(
            "/api/chat/sessions", json={"student_id": child_id},
            headers={"Authorization": f"Bearer {token}"},
        ).json()["id"]
        captured_messages: dict[str, list] = {}

        async def capture_stream(*, messages, **kwargs):
            captured_messages["messages"] = [dict(m) for m in messages]
            return _mock_text_stream("今天是 " + (date_guard.local_today() - timedelta(days=5)).isoformat())

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=capture_stream):
            r = real_client.post(
                f"/api/chat/sessions/{sid}/messages",
                json={"content": "今天帮我安排数学"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        anchor = date_guard.current_round_date_anchor()
        llm_user = [m for m in captured_messages["messages"] if m.get("role") == "user"][-1]
        assert llm_user["content"].startswith(anchor)
        assert "今天帮我安排数学" in llm_user["content"]

        persisted = real_client.get(
            f"/api/chat/sessions/{sid}/messages",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        user_msg = [m for m in persisted if m["role"] == "user"][-1]
        assert user_msg["content"] == "今天帮我安排数学"
        assert anchor not in (user_msg["content"] or "")

    def test_sse_done_content_uses_corrected_final_text(self, real_client):
        """今天标签命中时，done.content 与落库正文都返回校正后文本。"""
        from datetime import timedelta

        from app.features.agent import date_guard

        token, child_id = _teacher_token_and_child_id(real_client)
        sid = real_client.post(
            "/api/chat/sessions", json={"student_id": child_id},
            headers={"Authorization": f"Bearer {token}"},
        ).json()["id"]
        past = (date_guard.local_today() - timedelta(days=5)).isoformat()
        today = date_guard.local_today().isoformat()
        reply = f"今天是 {past}，开始数学复习。"
        expected = f"今天是 {today}，开始数学复习。"

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, return_value=_mock_present_response_stream([{"type": "paragraph", "text": reply}])):
            r = real_client.post(
                f"/api/chat/sessions/{sid}/messages",
                json={"content": "今天帮我安排数学"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        done_event = [e for e in _parse_sse_events(r.text) if e["type"] == "done"][-1]
        assert done_event["content"] == expected + "\n"

        messages = real_client.get(
            f"/api/chat/sessions/{sid}/messages",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["content"] == expected + "\n"

    def test_sse_does_not_rewrite_wrong_question_history_date(self, real_client):
        """反例（误伤边界）：今天复习 2026-07-23 的错题 不被改成今天。"""
        token, child_id = _teacher_token_and_child_id(real_client)
        sid = real_client.post(
            "/api/chat/sessions", json={"student_id": child_id},
            headers={"Authorization": f"Bearer {token}"},
        ).json()["id"]
        reply = "好的，今天复习 2026-07-23 的错题。"

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, return_value=_mock_present_response_stream([{"type": "paragraph", "text": reply}])):
            r = real_client.post(
                f"/api/chat/sessions/{sid}/messages",
                json={"content": "今天复习 2026-07-23 的错题"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        done_event = [e for e in _parse_sse_events(r.text) if e["type"] == "done"][-1]
        assert done_event["content"] == reply + "\n"

        messages = real_client.get(
            f"/api/chat/sessions/{sid}/messages",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        assert messages[-1]["content"] == reply + "\n"

    def test_sse_keeps_plain_date_qa_untouched(self, real_client):
        """普通日期问答（用户没提今天/今日）不做任何校正。"""
        token, child_id = _teacher_token_and_child_id(real_client)
        sid = real_client.post(
            "/api/chat/sessions", json={"student_id": child_id},
            headers={"Authorization": f"Bearer {token}"},
        ).json()["id"]
        reply = "2026-07-23 是周三。"

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, return_value=_mock_present_response_stream([{"type": "paragraph", "text": reply}])):
            r = real_client.post(
                f"/api/chat/sessions/{sid}/messages",
                json={"content": "2026-07-23 是周几"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        done_event = [e for e in _parse_sse_events(r.text) if e["type"] == "done"][-1]
        assert done_event["content"] == reply + "\n"
        messages = real_client.get(
            f"/api/chat/sessions/{sid}/messages",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        assert messages[-1]["content"] == reply + "\n"
