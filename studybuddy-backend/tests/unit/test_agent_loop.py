"""agent_loop 单元测试（mock LLM，测工具分发/权限/落库链路）。

覆盖：
- 工具注册器一致性（定义 name == handler name）
- 角色权限：teacher 能出题，student 不能（403）
- create_exam 工具：mock LLM 返回 tool_use → 试卷真实落库
- query_diagnosis：mock LLM 返回 tool_use → 调用诊断 service
- 熔断降级：CircuitOpenError → 返回"稍后处理"不白屏
"""

import asyncio
import base64
import json
from io import BytesIO
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.core import ai_service
from app.prompts import load
from app.features.agent import agent_loop
from app.models.error_book import ErrorBook
from app.models.chat import ChatSession
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.material import Material
from app.models.p2 import StudentAttribute
from app.models.question import Question
from app.models.user import User
from app.features.p2.schemas import ProfileOnboardingRequest, StudyPlanItemInput, UpdateProfileRequest
from app.features.note import service as note_service
from app.features.p2 import feedback, profile, recommendation, study_plan
from app.features.exams import batch_service as exam_batch_service


async def _async_iter(items):
    """把普通 list 包成 async-iterable，供 `async for chunk in stream` 消费。

    call_llm_stream 改 async 后返回 AsyncStream，mock 需返回 async-iterable。
    """
    for item in items:
        yield item


def _chunk(content: str | None = None, reasoning: str | None = None, tool_call: dict | None = None, finish: str | None = None) -> MagicMock:
    """构造一个流式 chunk（OpenAI ChatCompletionChunk）。delta 含 content/reasoning_content/tool_calls。"""
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


def _mock_tool_stream(tool_name: str, tool_input: dict, text: str = ""):
    """构造流式 chunks（包成 async-iterable）：可选正文 + 一个 tool_call。"""
    args_str = json.dumps(tool_input, ensure_ascii=False)
    chunks = []
    if text:
        chunks.append(_chunk(content=text))
    chunks.append(_chunk(tool_call={"index": 0, "id": "call_1", "name": tool_name, "arguments": ""}))
    chunks.append(_chunk(tool_call={"index": 0, "id": None, "name": None, "arguments": args_str}))
    chunks.append(_chunk(finish="tool_calls"))
    return _async_iter(chunks)


def _mock_multi_tool_stream(tool_name: str, tool_input: dict, count: int):
    """单轮多个同工具 tool_call（循环检测测试用）。"""
    args_str = json.dumps(tool_input, ensure_ascii=False)
    chunks = []
    for i in range(count):
        chunks.append(_chunk(tool_call={"index": i, "id": f"call_{i}", "name": tool_name, "arguments": ""}))
        chunks.append(_chunk(tool_call={"index": i, "id": None, "name": None, "arguments": args_str}))
    chunks.append(_chunk(finish="tool_calls"))
    return _async_iter(chunks)


def _mock_text_stream(text: str):
    """构造纯文本流式 chunks（包成 async-iterable）。"""
    return _async_iter([_chunk(content=text), _chunk(finish="stop")])


def _mock_present_response_stream(blocks: list[dict]):
    """构造一次 present_response 工具调用流（结构化终态协议）。"""
    return _mock_tool_stream("present_response", {"blocks": blocks})


def _mock_reasoning_only_stream(reasoning: str):
    """构造只有 reasoning、content 为空的流（模拟 MiMo 把完整答案放进 reasoning_content 的情况）。"""
    return _async_iter([_chunk(reasoning=reasoning), _chunk(finish="stop")])


class TestToolRegistry:
    """工具注册器一致性（审查避坑点）。"""

    def test_all_tools_have_handlers(self):
        # present_response 是结构化终态协议工具（不走 run_tool/_dispatch，在 agent_loop 内拦截），
        # 其余工具必须都有 handler
        names = {t["name"] for t in agent_loop.ALL_TOOLS if t["name"] != "present_response"}
        handlers = set(agent_loop._HANDLERS.keys())
        assert names == handlers, f"工具定义与handler不一致: {names} vs {handlers}"

    def test_present_response_is_terminal_protocol_tool(self):
        """present_response 是终态协议工具：无 handler（不走 run_tool），且在 ALL_TOOLS 中。"""
        names = {t["name"] for t in agent_loop.ALL_TOOLS}
        assert "present_response" in names
        assert "present_response" not in agent_loop._HANDLERS

    def test_present_response_registered_for_all_actors(self):
        """终态协议工具必须对所有 actor 可见（student/teacher/channel_guardian），
        否则模型看不到该工具只能输出自由正文 → 强制补调也失败（批次3 live 实测暴露）。"""
        for role, actor in [("student", None), ("teacher", None), ("teacher", "channel_guardian")]:
            tool_names = {t["name"] for t in agent_loop.tools_for_actor(role, actor)}
            assert "present_response" in tool_names, (
                f"present_response 未注册到 role={role} actor={actor}"
            )

    def test_teacher_has_create_exam(self):
        teacher_tools = {t["name"] for t in agent_loop.tools_for_role("teacher")}
        assert "create_exam" in teacher_tools

    def test_student_cannot_create_exam(self):
        student_tools = {t["name"] for t in agent_loop.tools_for_role("student")}
        assert "create_exam" not in student_tools

    def test_student_can_record_feedback(self):
        student_tools = {t["name"] for t in agent_loop.tools_for_role("student")}
        assert "record_feedback" in student_tools

    def test_student_uses_draft_not_direct_create(self):
        student_tools = {t["name"] for t in agent_loop.tools_for_role("student")}
        assert "draft_study_plan" in student_tools
        assert "create_study_plan" not in student_tools  # Web 学生不再直接建，必须先 draft 再卡片确认
        assert "query_study_plans" in student_tools
        assert "archive_study_plan" in student_tools

    def test_student_can_save_profile_onboarding(self):
        student_tools = {t["name"] for t in agent_loop.tools_for_role("student")}
        assert "save_profile_onboarding" in student_tools

    def test_student_can_grade_homework_photo(self):
        student_tools = {t["name"] for t in agent_loop.tools_for_role("student")}
        assert "recognize_homework_photo_markdown" in student_tools
        assert "grade_homework_photo" in student_tools
        assert "save_graded_homework_errors" in student_tools

    def test_student_can_list_materials(self):
        student_tools = {t["name"] for t in agent_loop.tools_for_role("student")}
        assert "list_materials" in student_tools

    def test_channel_guardian_only_has_safe_read_tools(self):
        tools = agent_loop.tools_for_actor("teacher", "channel_guardian")

        assert {tool["name"] for tool in tools} == {
            "query_diagnosis",
            "query_learning_map",
            "query_error_book",
            "query_study_plans",
            "get_attributes",
            "present_response",
        }

    def test_channel_guardian_cannot_execute_unregistered_write_tool(self):
        tool_stream = _mock_tool_stream(
            "create_study_plan",
            {
                "student_id": 2,
                "title": "越权计划",
                "planned_date": "2026-07-12",
                "confirmed": True,
                "items": [{"title": "不应创建"}],
            },
        )
        text_stream = _mock_text_stream("我不能替你修改孩子的学习计划。")

        with (
            patch.object(agent_loop, "_build_profile_context", return_value=""),
            patch.object(
                ai_service,
                "call_llm_stream",
                new_callable=AsyncMock,
                side_effect=[tool_stream, text_stream],
            ),
            patch.object(agent_loop, "_dispatch", new_callable=AsyncMock) as dispatch,
        ):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "给孩子建一个计划"}],
                    role="teacher",
                    db=MagicMock(),
                    teacher_id=1,
                    student_id=2,
                    business_actor="channel_guardian",
                )
            )

        dispatch.assert_not_awaited()
        # 渠道家长执行写工具被网关白名单拦截（语义等同旧"权限不足"，但更硬）
        assert "不在可用列表" in result[-2]["content"]

    def test_channel_guardian_cannot_query_another_bound_student_in_same_session(self):
        tool_stream = _mock_tool_stream("query_diagnosis", {"student_id": 3})
        text_stream = _mock_text_stream("当前只能查看已经选中的孩子。")

        with (
            patch.object(agent_loop, "_build_profile_context", return_value=""),
            patch.object(
                ai_service,
                "call_llm_stream",
                new_callable=AsyncMock,
                side_effect=[tool_stream, text_stream],
            ),
            patch.object(agent_loop, "_dispatch", new_callable=AsyncMock) as dispatch,
        ):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "看看另一个孩子"}],
                    role="teacher",
                    db=MagicMock(),
                    teacher_id=1,
                    student_id=2,
                    business_actor="channel_guardian",
                )
            )

        dispatch.assert_not_awaited()
        assert result[-2]["content"].startswith("权限不足")

    def test_channel_guardian_does_not_inject_student_private_profile_context(self):
        captured_system = ""

        async def fake_stream(*args, **kwargs):
            nonlocal captured_system
            captured_system = kwargs.get("system") or args[2]
            return _mock_text_stream("只能根据允许的学习数据回答。")

        with (
            patch.object(
                agent_loop,
                "_build_profile_context",
                return_value="\n[学生画像] PRIVATE_DAILY_REVIEW_SENTINEL",
            ),
            patch.object(
                ai_service,
                "call_llm_stream",
                new_callable=AsyncMock,
                side_effect=fake_stream,
            ),
        ):
            asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "孩子最近怎么样"}],
                    role="teacher",
                    db=MagicMock(),
                    teacher_id=1,
                    student_id=2,
                    business_actor="channel_guardian",
                )
            )

        assert "PRIVATE_DAILY_REVIEW_SENTINEL" not in captured_system

    def test_student_can_query_learning_map(self):
        student_tools = {t["name"] for t in agent_loop.tools_for_role("student")}
        assert "query_learning_map" in student_tools


def test_save_note_tool_requires_error_review_confirmation():
    from app.features.agent.agent_loop import _TOOL_SAVE_NOTE

    description = _TOOL_SAVE_NOTE["description"]

    assert "错题复盘" in description
    assert "商量好内容" in description  # 错题复盘先商量再落草稿，不自动保存
    assert "确认后" in description
    assert "source_ref" in description
    assert "不要说已保存" in description  # 落的是待确认草稿，不能说已保存


def test_homework_photo_tools_require_answer_confirmation_before_grading():
    from app.features.agent.agent_loop import _TOOL_GRADE_HOMEWORK_PHOTO, _TOOL_RECOGNIZE_HOMEWORK_PHOTO_MARKDOWN

    recognize_description = _TOOL_RECOGNIZE_HOMEWORK_PHOTO_MARKDOWN["description"]
    grade_description = _TOOL_GRADE_HOMEWORK_PHOTO["description"]

    assert "低置信" in recognize_description
    assert "先追问学生确认" in recognize_description
    assert "自然语言修正" in recognize_description
    assert "复述确认后的作答" in grade_description
    assert "student_answer 必须来自 confirmed_markdown" in grade_description


def test_agent_loop_injects_growth_strategy_for_speech_training():
    captured_systems = []

    async def fake_stream(*, messages, tools, system):
        captured_systems.append(system)
        return _mock_text_stream("先说说你想在哪个场景练口才？")

    with (
        patch.object(agent_loop, "_build_profile_context", return_value=""),
        patch.object(agent_loop, "_build_learning_memory_context", return_value=""),
        patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=fake_stream),
    ):
        asyncio.run(
            agent_loop.agent_loop(
                messages=[{"role": "user", "content": "我想练口才"}],
                role="student",
                db=object(),
                teacher_id=2,
                student_id=0,
            )
        )

    assert "[成长目标策略]" in captured_systems[0]
    assert "计划草案" in captured_systems[0]
    assert "确认" in captured_systems[0]


def test_agent_loop_does_not_inject_growth_strategy_for_login_question():
    captured_systems = []

    async def fake_stream(*, messages, tools, system):
        captured_systems.append(system)
        return _mock_text_stream("我帮你看登录问题。")

    with (
        patch.object(agent_loop, "_build_profile_context", return_value=""),
        patch.object(agent_loop, "_build_learning_memory_context", return_value=""),
        patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=fake_stream),
    ):
        asyncio.run(
            agent_loop.agent_loop(
                messages=[{"role": "user", "content": "登录失败怎么办"}],
                role="student",
                db=object(),
                teacher_id=2,
                student_id=0,
            )
        )

    assert "[成长目标策略]" not in captured_systems[0]


class TestErrorImportIntentGuard:
    """错题导入高置信意图守卫。"""

    def test_uploaded_batch_forces_process_tool(self):
        """已上传批次并要求解析时强制走解析工具。"""
        forced = agent_loop._forced_error_import_tool(
            [{"role": "user", "content": "[错题导入] 已上传 2 张照片到批次 #999，请解析并帮我判分入错题本。"}]
        )

        assert forced == {"name": "import_errors_process", "args": {"batch_id": 999}}

    def test_homework_photo_batch_forces_markdown_recognition_first(self):
        """拍题批改批次应先走 Markdown 识别，而不是直接要求 JSON 批改。"""
        forced = agent_loop._forced_error_import_tool(
            [
                {
                    "role": "user",
                    "content": "[拍题批改] 已上传 1 张照片到批次 #999，请先把照片识别成 Markdown，再让我确认。",
                }
            ]
        )

        assert forced == {"name": "recognize_homework_photo_markdown", "args": {"batch_id": 999}}

    def test_confirmed_homework_photo_batch_forces_grading_without_recognition(self):
        """用户确认逐题作答后必须直接批改，不能被“拍题批改”前缀再次路由到识别。"""
        forced = agent_loop._forced_error_import_tool(
            [
                {
                    "role": "user",
                    "content": "[拍题批改] 我已确认批次 #999 的逐题作答，请基于我刚确认的逐题作答进行批改，逐题给正确答案、错因和知识点。",
                }
            ]
        )

        assert forced == {"name": "grade_homework_photo", "args": {"batch_id": 999}}

    def test_manual_scores_force_grade_tool(self):
        """用户给出老师分数时强制走判分工具并保留字符串题号。"""
        forced = agent_loop._forced_error_import_tool(
            [
                {"role": "user", "content": "[错题导入] 已上传照片到批次 #888，请解析。"},
                {"role": "assistant", "content": "已解析出题目，请问试卷上有老师打的分数吗？"},
                {"role": "user", "content": "有分数，第3题65分，第5题0分，帮我入错题本"},
            ]
        )

        assert forced == {
            "name": "import_errors_grade",
            "args": {"batch_id": 888, "grade_mode": "has_score", "manual_scores": {"3": 65, "5": 0}},
        }

    def test_does_not_force_same_tool_twice_after_latest_user(self):
        """最近用户消息之后已调用过目标工具时不重复强制。"""
        forced = agent_loop._forced_error_import_tool(
            [
                {"role": "user", "content": "[错题导入] 已上传 2 张照片到批次 #999，请解析。"},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "forced",
                            "type": "function",
                            "function": {"name": "import_errors_process", "arguments": '{"batch_id":999}'},
                        }
                    ],
                },
            ]
        )

        assert forced is None

    def test_photo_markdown_force_runs_tool_before_llm_reasoning(self, db):
        """拍题上传应先执行识别工具，避免先按画像猜学科再展示思考过程。"""

        async def fake_recognize(args, role, db, teacher_id):
            return {
                "batch_id": args["batch_id"],
                "recognized_markdown": "### 物理刻度尺读数",
                "summary": "已识别为 Markdown。请先核对题目和作答。",
            }

        events = []

        async def collect(evt_type, data):
            events.append((evt_type, data))

        with (
            patch.dict(agent_loop._HANDLERS, {"recognize_homework_photo_markdown": fake_recognize}),
            patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[_mock_present_response_stream([{"type": "paragraph", "text": "请先确认识别稿。"}])]) as mock_stream,
        ):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [
                        {
                            "role": "user",
                            "content": "[拍题批改] 已上传 1 张照片到批次 #999，请先把照片识别成 Markdown。",
                        }
                    ],
                    role="student",
                    db=db,
                    teacher_id=2,
                    emit=collect,
                )
            )

        assert mock_stream.call_count == 1
        assert events[0][0] == "tool_call"
        assert events[0][1]["name"] == "recognize_homework_photo_markdown"
        assert not any(evt_type == "reasoning" for evt_type, _ in events[:1])
        assert result[-1]["content"] == "请先确认识别稿。\n"


class TestVisionPhotoPayload:
    """发给视觉模型的照片载荷应先压缩，避免大图导致长时间 SSE 断线。"""

    def test_encode_photo_for_vision_downscales_large_png(self, tmp_path):
        from app.features.materials.markdown_extraction_service import encode_image_for_vision

        image_path = tmp_path / "large.png"
        Image.new("RGB", (4200, 3100), color="white").save(image_path, format="PNG")
        original_size = image_path.stat().st_size

        payload = encode_image_for_vision(str(image_path))
        encoded = payload["image_url"]["url"].split(",", 1)[1]
        compressed_size = len(base64.b64decode(encoded))

        assert payload["type"] == "image_url"
        assert payload["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert compressed_size < original_size * 0.5
        compressed_image = Image.open(BytesIO(base64.b64decode(encoded)))
        assert max(compressed_image.size) <= 1800

    def test_recognize_homework_photo_markdown_uses_common_markdown_extraction_service(self, db, tmp_path, monkeypatch):
        """拍题 Markdown 识别应复用通用提取服务，并透传结果字段。"""
        from app.models.exam_batch import ExamBatch
        from app.features.exams import batch_service as exam_batch_service
        from app.features.materials import markdown_extraction_service

        folder = "ocr_provider_batch"
        folder_path = tmp_path / folder
        folder_path.mkdir()
        image_path = folder_path / "homework.png"
        Image.new("RGB", (120, 80), color="white").save(image_path)
        monkeypatch.setattr(exam_batch_service, "UPLOAD_ROOT", str(tmp_path))
        batch = ExamBatch(
            student_id=2,
            subject="auto",
            exam_name="外部OCR测试",
            exam_date="2026-07-05",
            photo_material_ids=[],
            folder_name=folder,
            status="uploaded",
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)

        extraction_result = markdown_extraction_service.MarkdownExtractionResult(
            markdown="### 外部 OCR 识别稿\n\n学生作答：[?]\n\n**识别置信度**：高",
            provider="external_cli",
            elapsed_ms=18,
        )
        with patch.object(
            markdown_extraction_service,
            "recognize_images_to_markdown",
            new_callable=AsyncMock,
            return_value=extraction_result,
        ) as mock_recognize:
            result = asyncio.run(
                agent_loop._handle_recognize_homework_photo_markdown(
                    {"batch_id": batch.id},
                    "student",
                    db,
                    2,
                )
            )

        assert mock_recognize.await_count == 1
        assert mock_recognize.call_args.args == ([str(image_path)],)
        assert mock_recognize.call_args.kwargs == {"mode": "homework_photo"}
        assert result["recognized_markdown"].startswith("### 外部 OCR 识别稿")
        assert result["recognition_provider"] == "external_cli"
        assert result["recognition_elapsed_ms"] == 18

    def test_recognize_homework_photo_markdown_returns_common_service_mimo_result(self, db, tmp_path, monkeypatch):
        """拍题 Markdown 识别应透传通用服务返回的 MiMo 结果。"""
        from app.models.exam_batch import ExamBatch
        from app.features.exams import batch_service as exam_batch_service
        from app.features.materials import markdown_extraction_service

        folder = "ocr_fallback_batch"
        folder_path = tmp_path / folder
        folder_path.mkdir()
        image_path = folder_path / "homework.png"
        Image.new("RGB", (120, 80), color="white").save(image_path)
        monkeypatch.setattr(exam_batch_service, "UPLOAD_ROOT", str(tmp_path))
        batch = ExamBatch(
            student_id=2,
            subject="auto",
            exam_name="外部OCR回退测试",
            exam_date="2026-07-05",
            photo_material_ids=[],
            folder_name=folder,
            status="uploaded",
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)

        extraction_result = markdown_extraction_service.MarkdownExtractionResult(
            markdown="### MiMo 识别稿\n\n学生作答：[?]\n\n**识别置信度**：85%",
            provider="mimo",
            elapsed_ms=42,
            warnings=["vision-fallback"],
        )
        with patch.object(
            markdown_extraction_service,
            "recognize_images_to_markdown",
            new_callable=AsyncMock,
            return_value=extraction_result,
        ) as mock_recognize:
            result = asyncio.run(
                agent_loop._handle_recognize_homework_photo_markdown(
                    {"batch_id": batch.id},
                    "student",
                    db,
                    2,
                )
            )

        assert mock_recognize.await_count == 1
        assert mock_recognize.call_args.args == ([str(image_path)],)
        assert mock_recognize.call_args.kwargs == {"mode": "homework_photo"}
        assert result["recognized_markdown"].startswith("### MiMo 识别稿")
        assert result["recognition_provider"] == "mimo"
        assert result["recognition_elapsed_ms"] == 42
        assert result["recognition_warnings"] == ["vision-fallback"]

    def test_recognize_homework_photo_markdown_returns_answer_review_state(self, db, tmp_path, monkeypatch):
        """拍题 Markdown 识别后应返回并持久化逐题作答核对状态。"""
        from app.models.exam_batch import ExamBatch
        from app.features.exams import batch_service as exam_batch_service
        from app.features.materials import markdown_extraction_service

        folder = "answer_review_batch"
        folder_path = tmp_path / folder
        folder_path.mkdir()
        image_path = folder_path / "homework.png"
        Image.new("RGB", (120, 80), color="white").save(image_path)
        monkeypatch.setattr(exam_batch_service, "UPLOAD_ROOT", str(tmp_path))
        batch = ExamBatch(
            student_id=2,
            subject="auto",
            exam_name="作答核对测试",
            exam_date="2026-07-07",
            photo_material_ids=[],
            folder_name=folder,
            status="uploaded",
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)

        extraction_result = markdown_extraction_service.MarkdownExtractionResult(
            markdown="1. 选择正确读数\n学生作答：B\n作答置信度：低\n需确认：圈选痕迹太淡",
            provider="mimo",
            elapsed_ms=20,
        )
        with patch.object(
            markdown_extraction_service,
            "recognize_images_to_markdown",
            new_callable=AsyncMock,
            return_value=extraction_result,
        ):
            result = asyncio.run(
                agent_loop._handle_recognize_homework_photo_markdown(
                    {"batch_id": batch.id},
                    "student",
                    db,
                    2,
                )
            )

        review_state = result["answer_review_state"]
        assert review_state["status"] == "pending_review"
        assert review_state["items"][0]["question_no"] == "1"
        assert review_state["items"][0]["detected_answer"] == "B"
        assert review_state["items"][0]["needs_review"] is True
        db.refresh(batch)
        assert batch.answer_review_state["items"][0]["review_reason"] == "圈选痕迹太淡"


class TestRecommendResourceBoundary:
    """推荐资源工具应遵守家长边界。"""

    def test_blocked_keyword_stops_recommendation_before_search(self, db):
        recommendation.update_recommendation_boundary(
            db,
            student_id=2,
            allowed_platforms=["bilibili"],
            blocked_keywords=["游戏直播"],
            daily_limit=3,
            allow_entertainment_interests=False,
            updated_by=1,
        )

        result = asyncio.run(
            agent_loop._handle_recommend_resource(
                {"student_id": 2, "keyword": "英语 游戏直播"},
                "teacher",
                db,
                teacher_id=1,
            )
        )

        assert result["error"] == "家长推荐边界已屏蔽关键词：游戏直播"
        assert "先不推荐新资源" in result["summary"]


class TestAgentStudentIdResolver:
    """Agent 工具统一解析 student_id，避免各 handler 权限分支漂移。"""

    def test_student_tool_ignores_passed_student_id(self, db):
        sid = agent_loop._resolve_tool_student_id({"student_id": 999}, "student", db, user_id=2)

        assert sid == 2

    def test_teacher_without_student_id_returns_zero(self, db):
        sid = agent_loop._resolve_tool_student_id({}, "teacher", db, user_id=1)

        assert sid == 0

    def test_teacher_cannot_access_unbound_student(self, db):
        student = User(
            username="unbound-student",
            password_hash="x",
            role="student",
            display_name="未绑定学生",
        )
        db.add(student)
        db.commit()
        db.refresh(student)

        with pytest.raises(PermissionError, match="无权访问该学生"):
            agent_loop._resolve_tool_student_id({"student_id": student.id}, "teacher", db, user_id=1)


class TestStudyPlanReminder:
    """学习计划提醒应进入 Agent 查询结果，方便继续督促。"""

    def test_unclear_study_plan_intent_does_not_create_plan(self, db):
        """学生只说粗略意图时，即使模型误调 create_study_plan 也不能落库。"""
        tool_stream = _mock_tool_stream(
            "create_study_plan",
            {
                "student_id": 2,
                "title": "英语词汇与语法巩固",
                "planned_date": "2025-01-06",
                "confirmed": True,
                "items": [{"title": "背单词", "minutes": 20}],
            },
        )
        text_stream = _mock_text_stream("先确认一下：你下午英语想学单词、语法还是阅读？大概有多久？")

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "下午要学英语"}],
                    role="student",
                    db=db,
                    teacher_id=2,
                )
            )

        plans = study_plan.list_study_plans(db, 2, status="")
        assert all(plan.title != "英语词汇与语法巩固" for plan in plans)
        # 学生已移除 create_study_plan（Task3 改草案卡片），网关白名单拦截该幻觉调用
        assert any(m["role"] == "tool" and "不在可用列表" in m["content"] for m in result)

    def test_main_session_cannot_generate_practice_for_plan_item(self, db):
        """关联计划项的练习必须进入具体任务会话，主会话不能直接生成。"""
        tool_stream = _mock_tool_stream(
            "create_practice_exam",
            {
                "title": "代数基础练习",
                "subject": "math",
                "plan_item_id": 5912,
                "questions": [],
            },
        )

        with (
            patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, return_value=tool_stream),
            patch.object(agent_loop, "_dispatch", new_callable=AsyncMock) as mock_dispatch,
        ):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "开始这个计划"}],
                    role="student",
                    db=db,
                    teacher_id=2,
                    session_type="main",
                )
            )

        mock_dispatch.assert_not_awaited()
        assert "不能在主规划会话直接开始" in result[-1]["content"]
        assert "进入具体计划任务" in result[-1]["content"]

    def test_confirmed_study_plan_defaults_to_today(self, db):
        """学生不再能直接调 create_study_plan（网关白名单拦截）；创建走草案卡片确认。"""
        tool_stream = _mock_tool_stream(
            "create_study_plan",
            {
                "student_id": 2,
                "title": "下午英语计划",
                "confirmed": True,
                "items": [{"title": "背单词", "minutes": 20}],
            },
        )
        text_stream = _mock_text_stream("已按确认的草案创建。")

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]):
            asyncio.run(
                agent_loop.agent_loop(
                    [
                        {"role": "user", "content": "下午要学英语"},
                        {"role": "assistant", "content": "计划草案：背单词 20 分钟。是否可行？"},
                        {"role": "user", "content": "可以，按这个创建吧"},
                    ],
                    role="student",
                    db=db,
                    teacher_id=2,
                )
            )

        plans = [plan for plan in study_plan.list_study_plans(db, 2, status="") if plan.title == "下午英语计划"]
        # 学生不再能直接调 create_study_plan（Web 强制草案卡片确认），网关白名单拦截
        assert len(plans) == 0

    def test_expired_study_plan_draft_does_not_create_plan(self, db):
        """用户确认了过期草案时不能落库，必须重新确认当前计划。"""
        tool_stream = _mock_tool_stream(
            "create_study_plan",
            {
                "student_id": 2,
                "title": "过期草案计划",
                "planned_date": date.today().isoformat(),
                "confirmed": True,
                "items": [{"title": "英语阅读", "minutes": 30}],
            },
        )
        text_stream = _mock_text_stream("这个计划草案已经过期了，我们先重新确认一下今天还适不适合。")

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [
                        {
                            "role": "assistant",
                            "content": "计划草案：英语阅读 30 分钟。是否可行？",
                            "created_at": "2026-07-07T10:00:00",
                        },
                        {"role": "user", "content": "可以", "created_at": "2026-07-07T11:00:00"},
                    ],
                    role="student",
                    db=db,
                    teacher_id=2,
                )
            )

        plans = study_plan.list_study_plans(db, 2, status="")
        assert all(plan.title != "过期草案计划" for plan in plans)
        assert "重新确认" in result[-1]["content"]

    def test_direct_confirmation_without_plan_draft_does_not_create_plan(self, db):
        """用户说直接创建但前面没有草案时，不能绕过协商流程。"""
        tool_stream = _mock_tool_stream(
            "create_study_plan",
            {
                "student_id": 2,
                "title": "无草案计划",
                "confirmed": True,
                "items": [{"title": "背单词", "minutes": 20}],
            },
        )
        text_stream = _mock_text_stream("我先给你一个计划草案，你确认后我再创建。")

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "直接创建一个学习计划"}],
                    role="student",
                    db=db,
                    teacher_id=2,
                )
            )

        plans = study_plan.list_study_plans(db, 2, status="")
        assert all(plan.title != "无草案计划" for plan in plans)
        assert "计划草案" in result[-1]["content"]

    def test_query_study_plans_returns_reminders(self, db):
        recent_past_date = (date.today() - timedelta(days=2)).isoformat()
        study_plan.create_study_plan(
            db,
            student_id=2,
            title="今天数学补漏",
            items=[StudyPlanItemInput(title="先复盘错题", minutes=15)],
            planned_date=recent_past_date,
            created_by=1,
        )

        result = asyncio.run(agent_loop._handle_query_study_plans({"student_id": 2}, "teacher", db, teacher_id=1))

        assert result["reminders"]
        assert "计划「今天数学补漏」已逾期" in result["reminders"][0]
        assert "提醒：" in result["summary"]

    def test_query_study_plans_empty_status_includes_archived_history(self, db):
        plan = study_plan.create_study_plan(
            db,
            student_id=2,
            title="历史英语计划",
            items=[StudyPlanItemInput(title="继续复习", minutes=20)],
            planned_date=(date.today() - timedelta(days=2)).isoformat(),
        )
        study_plan.archive_study_plan(db, plan.id)

        result = asyncio.run(
            agent_loop._handle_query_study_plans(
                {"student_id": 2, "status": "", "topic": "英语"}, "student", db, teacher_id=2
            )
        )

        assert any(item["id"] == plan.id and item["status"] == "archived" for item in result["plans"])

    def test_query_study_plans_requires_topic_for_student_history_lookup(self, db):
        result = asyncio.run(
            agent_loop._handle_query_study_plans(
                {"student_id": 2, "status": ""}, "student", db, teacher_id=2
            )
        )

        assert result == {"error": "查询历史计划时必须提供 topic（当前科目或板块）"}

    def test_query_study_plans_topic_filters_history_candidates(self, db):
        english = study_plan.create_study_plan(
            db,
            student_id=2,
            title="历史英语计划",
            items=[StudyPlanItemInput(title="复习时态", minutes=20)],
            planned_date=(date.today() - timedelta(days=2)).isoformat(),
        )
        math = study_plan.create_study_plan(
            db,
            student_id=2,
            title="历史数学计划",
            items=[StudyPlanItemInput(title="复习函数", minutes=20)],
            planned_date=(date.today() - timedelta(days=2)).isoformat(),
        )

        result = asyncio.run(
            agent_loop._handle_query_study_plans(
                {"student_id": 2, "status": "", "topic": "英语"}, "student", db, teacher_id=2
            )
        )

        assert [item["id"] for item in result["plans"]] == [english.id]
        assert math.id not in [item["id"] for item in result["plans"]]

    def test_archive_study_plan_requires_confirmation_and_keeps_history(self, db):
        plan = study_plan.create_study_plan(
            db,
            student_id=2,
            title="今日英语计划",
            items=[StudyPlanItemInput(title="完成阅读练习", minutes=20)],
            created_by=2,
        )

        unconfirmed = asyncio.run(
            agent_loop._handle_archive_study_plan(
                {"plan_id": plan.id, "confirmed": False},
                "student",
                db,
                teacher_id=2,
            )
        )
        assert unconfirmed == {"error": "归档计划前需要用户明确确认"}
        assert study_plan.get_study_plan(db, plan.id).status == "active"

        archived = asyncio.run(
            agent_loop._handle_archive_study_plan(
                {"plan_id": plan.id, "confirmed": True},
                "student",
                db,
                teacher_id=2,
            )
        )
        assert archived["status"] == "archived"
        assert archived["history_retained"] is True
        assert study_plan.get_study_plan(db, plan.id) is not None

    def test_student_cannot_archive_another_students_plan(self, db):
        db.add(
            User(
                id=999,
                username="another-student",
                password_hash="test-only",
                role="student",
                display_name="其他学生",
            )
        )
        db.commit()
        plan = study_plan.create_study_plan(
            db,
            student_id=999,
            title="其他学生计划",
            items=[StudyPlanItemInput(title="不应被归档")],
            created_by=1,
        )

        result = asyncio.run(
            agent_loop._handle_archive_study_plan(
                {"plan_id": plan.id, "confirmed": True},
                "student",
                db,
                teacher_id=2,
            )
        )

        assert result == {"error": "无权归档该学习计划"}
        assert study_plan.get_study_plan(db, plan.id).status == "active"


class TestWrongReasonFeedbackContext:
    """错因反馈应进入 Agent 上下文，供计划和同类练习使用。"""

    def test_profile_context_includes_recent_wrong_reasons(self, db):
        feedback.submit_feedback(
            db,
            student_id=2,
            feedback_type="difficulty",
            content="错题原因：第 1 题「He ___ to school.」；错因：概念不清；知识点：过去时",
        )
        feedback.submit_feedback(
            db,
            student_id=2,
            feedback_type="difficulty",
            content="这条是普通困难反馈，不应当作错因",
        )

        context = agent_loop._build_profile_context(db, 2)

        assert "近期错因反馈" in context
        assert "错因：概念不清" in context
        assert "这条是普通困难反馈" not in context

    def test_query_feedback_returns_wrong_reason_bucket(self, db):
        feedback.submit_feedback(
            db,
            student_id=2,
            feedback_type="difficulty",
            content="错题原因：第 2 题「计算」；错因：粗心；知识点：有理数",
        )

        result = asyncio.run(agent_loop._handle_query_feedback({"student_id": 2}, "student", db, teacher_id=2))

        assert result["wrong_reasons"][0]["content"].startswith("错题原因：第 2 题")
        assert "1 条错因反馈" in result["summary"]


class TestLearningMemoryContext:
    """错题优先学习记忆上下文。"""

    @pytest.mark.parametrize(
        "text",
        [
            "今天英语怎么学",
            "下午想练两道类似题",
            "帮我复盘最近错题",
            "我哪里反复错了",
            "给我制定一个数学计划",
            "最近需要督促什么",
        ],
    )
    def test_learning_memory_trigger_for_study_intents(self, text):
        assert agent_loop._should_include_learning_memory(text)

    @pytest.mark.parametrize(
        "text",
        [
            "怎么登录",
            "帮助页面在哪里",
            "切换账号失败了",
        ],
    )
    def test_learning_memory_skips_non_study_intents(self, text):
        assert not agent_loop._should_include_learning_memory(text)

    @pytest.mark.parametrize(
        "text",
        [
            "你好",
            "接下来我该干嘛",
            "你还记得我最近传了什么吗",
        ],
    )
    def test_learning_memory_defaults_on_without_keyword_whitelist(self, text):
        assert agent_loop._should_include_learning_memory(text)

    def test_shorten_learning_memory_text_strips_space_and_limits_length(self):
        text = "  第一行\n\n第二行很长" + "好" * 120

        shortened = agent_loop._shorten_learning_memory_text(text, limit=20)

        assert "\n" not in shortened
        assert len(shortened) <= 21
        assert shortened.endswith("…")

    def test_summarize_error_book_groups_respects_limit_and_answer_window(self):
        groups = [
            SimpleNamespace(
                tag=f"知识点{i}",
                questions=[
                    SimpleNamespace(
                        error_id=i,
                        stem=f"题干{i} " + ("题" * 180),
                        student_answer="学" * 150,
                        correct_answer="答" * 150,
                        error_count=10 - i,
                    )
                ],
            )
            for i in range(6)
        ]

        lines = agent_loop._summarize_error_book_groups(groups, limit=5)

        assert len(lines) == 5
        assert "error_id=0" in lines[0]
        assert "error_id=5" not in "".join(lines)
        stem = lines[0].split("题干=", 1)[1].split("，学生答案=", 1)[0]
        student_answer = lines[0].split("学生答案=", 1)[1].split("，正确答案=", 1)[0]
        correct_answer = lines[0].split("正确答案=", 1)[1].split("，错过 ", 1)[0]
        assert 80 < len(stem) <= 121
        assert 80 < len(student_answer) <= 121
        assert 80 < len(correct_answer) <= 121
        assert stem.endswith("…")
        assert student_answer.endswith("…")
        assert correct_answer.endswith("…")

    def test_summarize_error_review_notes_caps_each_line_and_filters_by_category(self):
        notes = [
            SimpleNamespace(
                title="复盘标题" + ("标" * 80),
                content="复盘内容" + ("内" * 200),
                category="错题复盘",
                source="其他来源",
            ),
            SimpleNamespace(
                title="讲解笔记" + ("讲" * 80),
                content="讲解内容" + ("解" * 200),
                category="普通笔记",
                source="错题讲解",
            ),
            SimpleNamespace(
                title="第三条" + ("三" * 80),
                content="第三条内容" + ("条" * 200),
                category="错题复盘",
                source="错题讲解",
            ),
            SimpleNamespace(
                title="不会被收录",
                content="普通内容",
                category="普通笔记",
                source="课堂总结",
            ),
        ]

        lines = agent_loop._summarize_error_review_notes(notes, limit=3)

        assert len(lines) == 3
        assert all("不会被收录" not in line for line in lines)
        assert all(len(line) <= 120 for line in lines)
        assert all(line.endswith("…") for line in lines)

    def test_learning_memory_context_mock_degrades_without_data(self):
        with patch("app.features.note.service.get_blind_spots", return_value=[]), patch(
            "app.features.error_book.service.get_error_book", return_value=[]
        ), patch("app.features.note.service.list_notes", return_value=[]):
            context = agent_loop._build_learning_memory_context(object(), 2, "今天英语怎么学")

        assert "目前错题和复盘笔记数据较少" in context
        assert "不要编造历史" in context

    def test_learning_memory_context_mock_caps_counts_total_length_and_plan_confirmation(self):
        blind_spots = [
            SimpleNamespace(
                tag=f"盲点{i}" + ("盲" * 40),
                error_count=10 + i,
                last_wrong_at=f"2026-07-{i + 1:02d}",
                note_count=i,
            )
            for i in range(7)
        ]
        error_groups = [
            SimpleNamespace(
                tag=f"知识点{i}",
                questions=[
                    SimpleNamespace(
                        error_id=i,
                        stem=f"题干{i}" + ("题" * 180),
                        student_answer="学生答案" + ("学" * 160),
                        correct_answer="正确答案" + ("答" * 160),
                        error_count=20 - i,
                    )
                ],
            )
            for i in range(7)
        ]
        notes = [
            SimpleNamespace(
                title=f"复盘{i}" + ("标" * 80),
                content="内容" + ("内" * 200),
                category="错题复盘",
                source="错题讲解",
            )
            for i in range(5)
        ]

        with patch("app.features.note.service.get_blind_spots", return_value=blind_spots), patch(
            "app.features.error_book.service.get_error_book", return_value=error_groups
        ), patch("app.features.note.service.list_notes", return_value=notes):
            context = agent_loop._build_learning_memory_context(object(), 2, "给我制定一个数学计划")

        assert "[学习记忆]" in context
        assert len(context) <= 1200
        assert "创建学习计划前仍必须先和学生确认" in context
        assert "盲点5" not in context
        assert "error_id=5" not in context
        assert "《复盘3" not in context

    def test_learning_memory_context_mock_keeps_first_error_answers_in_final_context(self):
        error_groups = [
            SimpleNamespace(
                tag="长知识点" + ("知" * 40),
                questions=[
                    SimpleNamespace(
                        error_id=1,
                        stem="题干" + ("题" * 180),
                        student_answer="学生答案" + ("学" * 160),
                        correct_answer="正确答案" + ("答" * 160),
                        error_count=9,
                    )
                ],
            )
        ]

        with patch("app.features.note.service.get_blind_spots", return_value=[]), patch(
            "app.features.error_book.service.get_error_book", return_value=error_groups
        ), patch("app.features.note.service.list_notes", return_value=[]):
            context = agent_loop._build_learning_memory_context(object(), 2, "给我制定一个英语计划")

        assert "代表性错题：1. error_id=1" in context
        assert "学生答案=" in context
        assert "正确答案=" in context
        first_error_line = context.split("代表性错题：", 1)[1].split("；", 1)[0]
        assert "学生答案=" in first_error_line
        assert "正确答案=" in first_error_line

    def test_learning_memory_context_mock_handles_service_errors(self):
        with patch("app.features.note.service.get_blind_spots", side_effect=RuntimeError("boom")):
            context = agent_loop._build_learning_memory_context(object(), 2, "今天英语怎么学")

        assert context == ""

    def _create_wrong_question(self, db, tag: str = "一般过去时", error_count: int = 3) -> None:
        exam = Exam(title="学习记忆测试卷", subject="english", created_by=1)
        db.add(exam)
        db.commit()
        db.refresh(exam)

        question = Question(
            exam_id=exam.id,
            type="single_choice",
            stem="He ___ to school yesterday.",
            options=["go", "goes", "went", "gone"],
            answer_json=["went"],
            score=5,
            knowledge_tags=[tag],
        )
        db.add(question)
        db.commit()
        db.refresh(question)

        record = ExamRecord(exam_id=exam.id, student_id=2, total_score=0, status="graded")
        db.add(record)
        db.commit()
        db.refresh(record)

        db.add(
            ErrorBook(
                student_id=2,
                question_id=question.id,
                exam_record_id=record.id,
                knowledge_tags=[tag],
                error_count=error_count,
                last_wrong_at=datetime(2026, 7, 5, 18, 30, 0),
            )
        )
        db.commit()

    def test_learning_memory_context_includes_blind_spots_errors_and_review_notes(self, db):
        self._create_wrong_question(db)
        note_service.create_note(
            db,
            {
                "student_id": 2,
                "title": "一般过去时复盘",
                "subject": "英语",
                "category": "错题复盘",
                "content": "下次先找 yesterday 这种时间标志词，再判断动词过去式。",
                "knowledge_tags": ["一般过去时"],
                "source": "错题讲解",
                "source_ref": [1],
                "status": "confirmed",
            },
        )

        context = agent_loop._build_learning_memory_context(db, 2, "今天英语怎么学")

        assert "[学习记忆]" in context
        assert "近期高频错题" in context
        assert "一般过去时" in context
        assert "错 3 次" in context
        assert "代表性错题" in context
        assert "He ___ to school yesterday." in context
        assert "错题复盘笔记" in context
        assert "一般过去时复盘" in context
        assert "不要编造" in context

    def test_learning_memory_context_returns_empty_for_non_study_intent(self, db):
        self._create_wrong_question(db)

        context = agent_loop._build_learning_memory_context(db, 2, "怎么登录")

        assert context == ""

    def test_learning_memory_context_handles_service_errors(self, db):
        with patch("app.features.note.service.get_blind_spots", side_effect=RuntimeError("boom")):
            context = agent_loop._build_learning_memory_context(db, 2, "今天英语怎么学")

        assert context == ""

    def test_learning_memory_context_includes_recent_materials(self):
        fake_db = MagicMock()
        fake_db.get.return_value = SimpleNamespace(id=2, username="student", role="student", display_name="弟弟")
        materials = [
            SimpleNamespace(
                id=712,
                name="物理秒表读数",
                type="image",
                source="student",
                knowledge_tags=["物理", "测量"],
                recognition_status="confirmed",
                uploaded_by="弟弟",
                created_at="2026-07-07 09:30:00",
            )
        ]

        with patch("app.features.note.service.get_blind_spots", return_value=[]), patch(
            "app.features.error_book.service.get_error_book", return_value=[]
        ), patch("app.features.note.service.list_notes", return_value=[]), patch(
            "app.features.materials.service.list_materials", return_value=materials
        ):
            context = agent_loop._build_learning_memory_context(fake_db, 2, "根据我上传的素材复习")

        assert "最近素材" in context
        assert "#712" in context
        assert "物理秒表读数" in context
        assert "已确认" in context

    def test_agent_loop_injects_learning_memory_into_llm_system(self):
        captured_system = ""
        captured_memory_args = None

        async def fake_stream(*args, **kwargs):
            nonlocal captured_system
            captured_system = kwargs.get("system") or args[2]
            return _mock_present_response_stream(
                [{"type": "paragraph", "text": "我会先参考你最近的一般过去时错题。"}]
            )

        def fake_learning_memory(db, student_id, latest_user_text):
            nonlocal captured_memory_args
            captured_memory_args = (db, student_id, latest_user_text)
            return "\n[学习记忆] 一般过去时错 3 次；创建学习计划前仍必须先和学生确认。"

        with (
            patch.object(agent_loop, "_build_profile_context", return_value="\n[学生画像] 英语基础一般。"),
            patch.object(agent_loop, "_build_learning_memory_context", side_effect=fake_learning_memory),
            patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=fake_stream),
        ):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [
                        {"role": "user", "content": "先聊点别的"},
                        {"role": "assistant", "content": "可以。"},
                        {"role": "user", "content": "今天英语怎么学"},
                    ],
                    role="student",
                    db=MagicMock(),
                    teacher_id=2,
                )
            )

        assert captured_memory_args is not None
        assert captured_memory_args[1] == 2
        assert captured_memory_args[2] == "今天英语怎么学"
        assert captured_system.index("[学生画像]") < captured_system.index("[学习记忆]")
        assert "[学习记忆]" in captured_system
        assert "一般过去时" in captured_system
        assert "创建学习计划前仍必须先和学生确认" in captured_system
        assert result[-1]["content"] == "我会先参考你最近的一般过去时错题。\n"

    def test_agent_loop_does_not_inject_learning_memory_for_help_question(self):
        captured_system = ""

        async def fake_stream(*args, **kwargs):
            nonlocal captured_system
            captured_system = kwargs.get("system") or args[2]
            return _mock_text_stream("帮助页面在右上角。")

        with (
            patch.object(agent_loop, "_build_profile_context", return_value="\n[学生画像] 英语基础一般。"),
            patch.object(agent_loop, "_build_learning_memory_context", return_value=""),
            patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=fake_stream),
        ):
            asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "帮助页面在哪里"}],
                    role="student",
                    db=MagicMock(),
                    teacher_id=2,
                )
            )

        assert "[学习记忆]" not in captured_system

    def test_learning_memory_does_not_bypass_study_plan_confirmation(self):
        tool_stream = _mock_tool_stream(
            "create_study_plan",
            {
                "student_id": 2,
                "title": "英语错题补漏",
                "planned_date": "2026-07-06",
                "confirmed": True,
                "items": [{"title": "复盘一般过去时错题", "minutes": 20}],
            },
        )
        text_stream = _mock_text_stream("先确认一下：你今天有多少时间复盘一般过去时？")

        with (
            patch.object(agent_loop, "_build_profile_context", return_value="\n[学生画像] 英语基础一般。"),
            patch.object(
                agent_loop,
                "_build_learning_memory_context",
                return_value="\n[学习记忆] 一般过去时错 3 次；创建学习计划前仍必须先和学生确认。",
            ),
            patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]),
            patch.object(agent_loop, "_dispatch", new_callable=AsyncMock) as mock_dispatch,
        ):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "今天英语怎么学"}],
                    role="student",
                    db=MagicMock(),
                    teacher_id=2,
                )
            )

        mock_dispatch.assert_not_awaited()
        # 学生已移除 create_study_plan，网关白名单拦截（不落库）
        assert any(m["role"] == "tool" and "不在可用列表" in m["content"] for m in result)


class TestDailyReviewContext:
    """每日回顾应进入 Agent 上下文，帮助后续计划和督促。"""

    def test_profile_context_includes_recent_daily_review_notes(self, db):
        note_service.create_note(
            db,
            {
                "student_id": 2,
                "title": "2026.7.4 每日回顾",
                "subject": "其他",
                "category": "每日回顾",
                "content": "## 2026.7.4 总结\n\n今天背了英语单词。\n\n## 2026.7.5 目标\n\n明天继续做错题复盘。",
                "knowledge_tags": ["每日回顾", "目标"],
                "source": "每日回顾",
                "status": "confirmed",
            },
        )

        context = agent_loop._build_profile_context(db, 2)

        assert "最近每日回顾" in context
        assert "2026.7.4 每日回顾" in context
        assert "今天背了英语单词" in context
        assert "明天继续做错题复盘" in context

    def test_profile_context_reminds_when_today_daily_review_missing(self, db):
        class FixedDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 7, 5)

        note_service.create_note(
            db,
            {
                "student_id": 2,
                "title": "2026.7.4 每日回顾",
                "subject": "其他",
                "category": "每日回顾",
                "content": "## 昨日回顾（2026.7.3）\n\n复盘了英语错题。\n\n## 今日目标（2026.7.4）\n\n- [ ] 背单词",
                "knowledge_tags": ["每日回顾", "目标"],
                "source": "每日回顾",
                "status": "confirmed",
            },
        )

        with patch("app.features.agent.context.date", FixedDate):
            context = agent_loop._build_profile_context(db, 2)

        assert "今日每日回顾：尚未填写" in context
        assert "昨日回顾 + 今日目标" in context

    def test_profile_context_does_not_remind_when_today_daily_review_exists(self, db):
        class FixedDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 7, 5)

        note_service.create_note(
            db,
            {
                "student_id": 2,
                "title": "2026.7.5 每日回顾",
                "subject": "其他",
                "category": "每日回顾",
                "content": "## 昨日回顾（2026.7.4）\n\n复盘了英语错题。\n\n## 今日目标（2026.7.5）\n\n- [ ] 做数学错题",
                "knowledge_tags": ["每日回顾", "目标"],
                "source": "每日回顾",
                "status": "confirmed",
            },
        )

        with patch("app.features.agent.context.date", FixedDate):
            context = agent_loop._build_profile_context(db, 2)

        assert "今日每日回顾：尚未填写" not in context


class TestCreateExamTool:
    """create_exam 工具：mock LLM → 试卷真实落库。"""

    def test_create_exam_persists_exam_and_questions(self, db):
        """mock LLM 返回 create_exam tool_use → 试卷+题目落库。"""
        exam_input = {
            "title": "单元测试出题卷",
            "subject": "english",
            "feedback_mode": "after_submit",
            "questions": [
                {
                    "type": "single_choice",
                    "stem": "The man ___ called is my teacher.",
                    "options": ["who", "which", "what", "whose"],
                    "answer": [0],
                    "score": 5,
                    "knowledge_tags": ["定语从句"],
                    "grading": {"rule_type": "auto_exact", "matcher": "exact", "match_params": {}},
                }
            ],
        }
        mock_resp = [_mock_tool_stream("create_exam", exam_input, "出题中"), _mock_text_stream("试卷已生成")]

        session = ChatSession(user_id=1, student_id=2, role_at_create="teacher", title="test")
        db.add(session)
        db.commit()
        db.refresh(session)

        try:
            with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=mock_resp):
                result = asyncio.run(agent_loop.agent_loop([{"role": "user", "content": "出题"}], "teacher", db, 1, student_id=2))
            exam = db.query(Exam).filter(Exam.title == "单元测试出题卷").first()
            assert exam is not None, "试卷未落库"
            qs = db.query(Question).filter(Question.exam_id == exam.id).all()
            assert len(qs) == 1, f"题目数不对: {len(qs)}"
            assert qs[0].type == "single_choice"
            assert qs[0].knowledge_tags == ["定语从句"]
            assert qs[0].answer_json is not None  # 答案存在但不下发客户端
        finally:
            if exam := db.query(Exam).filter(Exam.title == "单元测试出题卷").first():
                db.delete(exam)
            db.delete(session)
            db.commit()
            db.close()


class TestCircuitDegradation:
    """熔断降级：CircuitOpenError → 不白屏。"""

    def test_circuit_open_returns_fallback_text(self, db):
        """LLM 熔断时 agent_loop 返回降级提示，不抛异常。"""
        session = ChatSession(user_id=1, student_id=2, role_at_create="teacher", title="test")
        db.add(session)
        db.commit()
        db.refresh(session)

        events = []

        async def collect(t, d):
            events.append(t)

        try:
            with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=ai_service.CircuitOpenError("熔断中")):
                result = asyncio.run(agent_loop.agent_loop([{"role": "user", "content": "hi"}], "teacher", db, 1, emit=collect))
            # 应返回降级文本，不抛异常
            assert "稍后" in result[-1].get("content", "") or "网络" in result[-1].get("content", "")
            assert "text" in events  # 推了 text 事件
        finally:
            db.delete(session)
            db.commit()
            db.close()


class TestQueryDiagnosisTool:
    """query_diagnosis 工具：mock LLM → 调诊断 service。"""

    def test_query_diagnosis_calls_service(self, db):
        """mock LLM 返回 query_diagnosis tool_use → 调用真实 service。"""
        mock_resp = [
            _mock_tool_stream("query_diagnosis", {"student_id": 2, "top_n": 5}, "查询中"),
            _mock_text_stream("弟弟暂无错题记录"),
        ]
        session = ChatSession(user_id=1, student_id=2, role_at_create="teacher", title="test")
        db.add(session)
        db.commit()
        db.refresh(session)

        try:
            with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=mock_resp):
                result = asyncio.run(agent_loop.agent_loop([{"role": "user", "content": "查诊断"}], "teacher", db, 1, student_id=2))
            # 最终应有文本回复（不报错即说明 service 被调用了）
            assert result[-1].get("content")
        finally:
            db.delete(session)
            db.commit()
            db.close()


class TestReadMaterialTool:
    """read_material 工具权限边界。"""

    def test_material_metadata_suggestion_from_text(self):
        suggestion = agent_loop._suggest_material_metadata("这是一张英语单词表，包含 shopkeeper、customer 等词汇。")

        assert suggestion["suggested_content_type"] == "单词表"
        assert "英语" in suggestion["suggested_tags"]
        assert "词汇" in suggestion["suggested_tags"]
        assert suggestion["suggested_summary"].startswith("这是一张英语单词表")

    def test_student_cannot_read_teacher_material(self, db):
        """学生不能通过 Agent 工具按 material_id 读取老师素材。"""
        material = Material(
            name="老师素材",
            type="image",
            source="teacher",
            content_ref="local:materials/private.png",
            knowledge_tags=[],
            uploaded_by=1,
        )
        db.add(material)
        db.commit()
        db.refresh(material)

        with pytest.raises(PermissionError, match="无权读取该素材"):
            asyncio.run(agent_loop._handle_read_material({"material_id": material.id}, "student", db, 2))

    def test_owner_can_read_non_image_material_fallback(self, db):
        """素材上传者本人读取非图片素材时返回描述兜底，不调用视觉。"""
        material = Material(
            name="老师 PDF",
            type="pdf",
            source="teacher",
            content_ref="local:materials/teacher.pdf",
            knowledge_tags=[],
            uploaded_by=1,
        )
        db.add(material)
        db.commit()
        db.refresh(material)

        result = asyncio.run(agent_loop._handle_read_material({"material_id": material.id}, "teacher", db, 1))

        assert result["material_id"] == material.id
        assert result["content"] is None
        assert "非图片无法直接识别内容" in result["fallback_hint"]

    def test_read_material_prefers_confirmed_markdown_without_vision(self, db):
        """素材已有确认稿时直接返回确认稿，不再即时读图。"""
        material = Material(
            name="已确认单词表",
            type="image",
            source="teacher",
            content_ref="local:materials/words.png",
            knowledge_tags=["英语", "词汇"],
            uploaded_by=1,
            recognized_markdown="### 旧识别稿\ncustomer",
            confirmed_markdown="### 确认后的单词表\nshopkeeper\ncustomer",
            recognition_status="confirmed",
            recognition_confidence="high",
        )
        db.add(material)
        db.commit()
        db.refresh(material)

        with patch.object(ai_service, "call_llm", new_callable=AsyncMock) as mock_call:
            result = asyncio.run(agent_loop._handle_read_material({"material_id": material.id}, "teacher", db, 1))

        assert result["content"] == "### 确认后的单词表\nshopkeeper\ncustomer"
        assert result["content_source"] == "confirmed_markdown"
        assert result["needs_confirmation"] is False
        assert "已读取已确认素材" in result["summary"]
        mock_call.assert_not_called()

    def test_read_material_uses_unconfirmed_markdown_with_confirmation_warning(self, db):
        """只有识别稿时返回未确认稿，并提醒 Agent 引导用户确认。"""
        material = Material(
            name="待确认讲义",
            type="image",
            source="student",
            content_ref="local:materials/note.png",
            knowledge_tags=[],
            uploaded_by=2,
            recognized_markdown="### 浮力笔记\n阿基米德原理",
            recognition_status="needs_review",
            recognition_confidence="medium",
            uncertain_points=["公式里的单位需要确认"],
        )
        db.add(material)
        db.commit()
        db.refresh(material)

        with patch.object(ai_service, "call_llm", new_callable=AsyncMock) as mock_call:
            result = asyncio.run(agent_loop._handle_read_material({"material_id": material.id}, "student", db, 2))

        assert result["content"] == "### 浮力笔记\n阿基米德原理"
        assert result["content_source"] == "recognized_markdown"
        assert result["needs_confirmation"] is True
        assert result["uncertain_points"] == ["公式里的单位需要确认"]
        assert "还没有人工确认" in result["fallback_hint"]
        mock_call.assert_not_called()

    def test_read_image_material_returns_metadata_suggestions(self, db, tmp_path):
        """图片素材读图后返回摘要、标签和内容类型建议。"""
        image_path = tmp_path / "words.png"
        image_path.write_bytes(b"fake image bytes")
        material = Material(
            name="英语单词表",
            type="image",
            source="teacher",
            content_ref="local:materials/words.png",
            knowledge_tags=[],
            uploaded_by=1,
        )
        db.add(material)
        db.commit()
        db.refresh(material)

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = MagicMock(
            content="这是一张英语单词表，包含 shopkeeper、customer 等词汇，适合整理词汇笔记。"
        )

        with (
            patch("app.features.materials.service.build_local_upload_path", return_value=str(image_path)),
            patch.object(ai_service, "call_llm", new_callable=AsyncMock, return_value=mock_resp),
        ):
            result = asyncio.run(agent_loop._handle_read_material({"material_id": material.id}, "teacher", db, 1))

        assert result["content"].startswith("这是一张英语单词表")
        assert result["suggested_content_type"] == "单词表"
        assert "英语" in result["suggested_tags"]
        assert "词汇" in result["suggested_tags"]
        assert result["suggested_summary"].startswith("这是一张英语单词表")


class TestListMaterialsTool:
    """list_materials 工具让 Agent 知道学生有哪些素材。"""

    def test_student_lists_only_own_materials_with_status_hint(self):
        fake_db = MagicMock()
        fake_db.get.return_value = SimpleNamespace(id=2, username="student", role="student", display_name="弟弟")
        materials = [
            SimpleNamespace(
                id=712,
                name="英语单词素材",
                type="image",
                source="student",
                knowledge_tags=["英语", "词汇"],
                recognition_status="confirmed",
                uploaded_by="弟弟",
                cos_url="/uploads/materials/words.png",
                created_at="2026-07-07 09:30:00",
            )
        ]

        with patch("app.features.materials.service.list_materials", return_value=materials):
            result = asyncio.run(agent_loop._handle_list_materials({}, "student", fake_db, 2))

        assert result["count"] == 1
        assert result["materials"][0]["id"] == 712
        assert result["materials"][0]["name"] == "英语单词素材"
        assert result["materials"][0]["status_label"] == "已确认"
        assert result["materials"][0]["ai_readiness"] == "可直接用于复习/讲解"
        assert "已确认 Markdown 可直接用于复习" in result["summary"]

    def test_list_materials_respects_limit(self):
        fake_db = MagicMock()
        fake_db.get.return_value = SimpleNamespace(id=2, username="student", role="student", display_name="弟弟")
        materials = [
            SimpleNamespace(
                id=index,
                name=f"素材 {index}",
                type="image",
                source="student",
                knowledge_tags=[],
                recognition_status="pending",
                uploaded_by="弟弟",
                cos_url=f"/uploads/materials/{index}.png",
                created_at="2026-07-07 09:30:00",
            )
            for index in range(3)
        ]

        with patch("app.features.materials.service.list_materials", return_value=materials):
            result = asyncio.run(agent_loop._handle_list_materials({"limit": 2}, "student", fake_db, 2))

        assert result["count"] == 2
        assert "共找到 3 个素材" in result["summary"]


class TestQueryLearningMapTool:
    """query_learning_map 工具让 Agent 用同一套学习地图口径回答薄弱点。"""

    def test_query_learning_map_returns_nodes_and_agent_summary(self):
        from app.features.learning.schemas.learning_map import LearningMapNode, LearningMapResponse

        fake_db = MagicMock()
        map_data = LearningMapResponse(
            student_id=2,
            generated_at="2026-07-07T10:00:00",
            nodes=[
                LearningMapNode(
                    tag="分数应用题",
                    status="weak",
                    error_count=3,
                    next_actions=["先选 1 道错题整理复盘笔记。"],
                )
            ],
            summary={"weak": 1, "reviewing": 0, "stable": 0, "unknown": 0},
        )

        with (
            patch("app.features.learning.map_service.build_learning_map", return_value=map_data),
            patch("app.features.learning.map_service.summarize_learning_map_for_agent", return_value=["分数应用题：需要优先补。"]),
        ):
            result = asyncio.run(agent_loop._handle_query_learning_map({"student_id": 2}, "student", fake_db, 2))

        assert result["student_id"] == 2
        assert result["summary"]["weak"] == 1
        assert result["nodes"][0]["tag"] == "分数应用题"
        assert result["agent_summary"] == ["分数应用题：需要优先补。"]


class TestPhotoGradingTool:
    """拍题批改工具真实 handler 行为。"""

    def test_grade_homework_photo_uses_confirmed_answer_review_without_reloading_photos(self, db):
        """已有逐题确认作答时，批改工具应基于确认答案，而不是重新读照片猜作答。"""
        student = db.query(User).filter(User.username == "student").one()
        batch_item = exam_batch_service.create_batch(db, student.id, "english", "确认作答批改", "2026-07-07")
        batch = exam_batch_service.get_batch(db, batch_item.id)
        batch.recognized_markdown = "1. 题目\n学生作答：D\n作答置信度：低"
        batch.answer_review_state = {
            "batch_id": batch.id,
            "recognized_markdown": batch.recognized_markdown,
            "items": [
                {
                    "question_no": "1",
                    "detected_answer": "D",
                    "confirmed_answer": "B",
                    "confidence": "low",
                    "needs_review": True,
                    "review_reason": "圈选痕迹太淡",
                    "answer_type": "choice",
                    "source_excerpt": "1. 题目",
                    "skipped": False,
                }
            ],
            "status": "confirmed",
            "confirmed_at": "2026-07-07T10:00:00",
        }
        db.commit()

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = MagicMock(
            content=json.dumps(
                {
                    "questions": [
                        {
                            "no": "1",
                            "stem": "题目",
                            "student_answer": "B",
                            "correct_answer": "B",
                            "is_correct": True,
                            "error_point": "",
                            "knowledge_tags": ["英语"],
                            "explanation": "答对了。",
                            "confidence": "high",
                            "needs_review": False,
                        }
                    ]
                },
                ensure_ascii=False,
            )
        )

        with patch.object(ai_service, "call_llm", new_callable=AsyncMock, return_value=mock_resp) as mock_llm:
            result = asyncio.run(agent_loop._handle_grade_homework_photo({"batch_id": batch.id}, "student", db, student.id))

        content = mock_llm.call_args.kwargs["messages"][0]["content"]
        assert content[0]["type"] == "text"
        assert "学生确认作答：B" in content[0]["text"]
        assert all(item.get("type") != "image_url" for item in content)
        assert result["questions"][0]["student_answer"] == "B"

    def test_grade_homework_photo_returns_question_feedback(self, db):
        """批次有照片时调用视觉 LLM，并返回正确答案、错因和知识点。"""
        student = db.query(User).filter(User.username == "student").one()
        batch_item = exam_batch_service.create_batch(db, student.id, "english", "拍题批改单测", "2026-07-05")
        batch = exam_batch_service.get_batch(db, batch_item.id)
        exam_batch_service.save_photo_to_batch(db, batch, "homework.jpg", b"fake image bytes", student.id, "拍题")

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = MagicMock(
            content=json.dumps(
                {
                    "questions": [
                        {
                            "no": "11",
                            "stem": "Choose the right answer.",
                            "student_answer": "A",
                            "correct_answer": "B",
                            "is_correct": False,
                            "error_point": "忽略固定搭配",
                            "knowledge_tags": ["英语", "固定搭配"],
                            "explanation": "这里应使用固定搭配。",
                            "confidence": "high",
                            "needs_review": False,
                        }
                    ]
                },
                ensure_ascii=False,
            )
        )

        with patch.object(ai_service, "call_llm", new_callable=AsyncMock, return_value=mock_resp):
            result = asyncio.run(agent_loop._handle_grade_homework_photo({"batch_id": batch.id}, "student", db, student.id))

        assert result["batch_id"] == batch.id
        assert result["summary"] == "已批改 1 道题。请先核对，确认后我再把错题保存进错题本。"
        question = result["questions"][0]
        assert question["correct_answer"] == "B"
        assert question["error_point"] == "忽略固定搭配"
        assert "固定搭配" in question["knowledge_tags"]


class TestReasoningOnlyFallback:
    """MiMo 偶尔把完整答案放进 reasoning_content 而 content 为空，需兜底为正文，否则用户看到空白回复。"""

    def test_stream_llm_turn_keeps_reasoning_server_side(self):
        """LLM 同时返回 reasoning 和 content 时，只向前端推正文，不暴露思考过程。"""
        stream = _async_iter([_chunk(reasoning="内部分析"), _chunk(content="测试回复"), _chunk(finish="stop")])
        events: list[tuple[str, dict]] = []

        async def collect(t, d):
            events.append((t, d))

        async def run():
            with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, return_value=stream):
                return await agent_loop._stream_llm_turn([], [], "", collect, buffer_text=False)

        assistant_text, tool_uses, reasoning_text = asyncio.run(run())

        assert assistant_text == "测试回复"
        assert tool_uses == []
        assert reasoning_text == "内部分析"
        assert ("text", {"content": "测试回复"}) in events
        assert not any(t == "reasoning" for t, _ in events)

    def test_reasoning_only_becomes_assistant_text(self, db):
        """LLM 只返回 reasoning（content 为空）→ reasoning 兜底为正文，走终态协议强制补调。"""
        mock_resp = [
            _mock_reasoning_only_stream("我是知了，可以帮你出题和讲解错题。"),
            _mock_present_response_stream(
                [{"type": "paragraph", "text": "我是知了，可以帮你出题和讲解错题。"}]
            ),
        ]
        session = ChatSession(user_id=1, student_id=2, role_at_create="teacher", title="test")
        db.add(session)
        db.commit()
        db.refresh(session)

        events: list[tuple[str, dict]] = []

        async def collect(t, d):
            events.append((t, d))

        try:
            with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=mock_resp):
                result = asyncio.run(agent_loop.agent_loop([{"role": "user", "content": "介绍下你自己"}], "teacher", db, 1, emit=collect))
            # 最终 assistant 消息 content 为渲染后的结构化正文（reasoning 兜底后过协议）
            assert result[-1].get("content") == "我是知了，可以帮你出题和讲解错题。\n"
            # 应 emit text 事件（把兜底正文推给前端）
            text_events = [d for t, d in events if t == "text"]
            assert text_events, "content 为空时应兜底 emit text 事件"
            assert text_events[-1]["content"] == "我是知了，可以帮你出题和讲解错题。\n"
            # reasoning 只能作为服务端兜底来源，不能暴露给学生端
            assert not any(t == "reasoning" for t, _ in events)
        finally:
            db.delete(session)
            db.commit()
            db.close()


class TestProfileContext:
    """学生画像上下文。"""

    def test_save_profile_onboarding_tool_updates_cold_start_profile(self, db):
        db.query(StudentAttribute).filter(StudentAttribute.student_id == 2).delete(synchronize_session=False)
        db.commit()

        result = asyncio.run(
            agent_loop._handle_save_profile_onboarding(
                {
                    "student_id": 2,
                    "grade": "八年级",
                    "semester": "上册",
                    "weak_subjects": ["英语"],
                    "study_preferences": {"preferred_time": "下午"},
                    "interests": ["唱歌"],
                },
                "student",
                db,
                teacher_id=2,
            )
        )

        assert result["saved"] is True
        assert result["summary"]["needs_onboarding"] is False
        assert result["summary"]["summary"]["grade"] == "八年级"
        assert result["summary"]["summary"]["semester"] == "上册"
        assert result["summary"]["summary"]["weak_subjects"] == ["英语"]
        assert result["summary"]["summary"]["study_preferences"]["preferred_time"] == "下午"
        assert "唱歌" in result["summary"]["summary"]["interests"]

    def test_forces_profile_onboarding_when_student_answers_cold_start_questions(self, db):
        db.query(StudentAttribute).filter(StudentAttribute.student_id == 2).delete(synchronize_session=False)
        db.commit()

        forced = agent_loop._forced_profile_onboarding_tool(
            [{"role": "user", "content": "我是七年级下，开学八年级上，英语薄弱，我对唱歌感兴趣，一般下午吧"}],
            db,
            student_id=2,
        )

        assert forced is not None
        assert forced["name"] == "update_profile"
        assert forced["args"]["student_id"] == 2
        assert forced["args"]["grade"] == "八年级"
        assert forced["args"]["semester"] == "上册"
        assert forced["args"]["weak_subjects"] == ["英语"]
        assert forced["args"]["add_interests"] == ["唱歌"]
        assert forced["args"]["study_preferences"]["preferred_time"] == "下午"

    def test_update_profile_tool_incrementally_updates_profile(self, db):
        db.query(StudentAttribute).filter(StudentAttribute.student_id == 2).delete(synchronize_session=False)
        db.commit()

        result = asyncio.run(
            agent_loop._handle_update_profile(
                {"student_id": 2, "grade": "八年级", "add_interests": ["篮球"]},
                "student",
                db,
                teacher_id=2,
            )
        )

        assert result["updated"] is True
        assert result["summary"]["summary"]["grade"] == "八年级"
        assert "篮球" in result["summary"]["summary"]["interests"]
        # 静默更新不写学习反馈
        assert feedback.list_feedback(db, student_id=2) == []

    def test_present_profile_question_is_display_only(self, db):
        db.query(StudentAttribute).filter(StudentAttribute.student_id == 2).delete(synchronize_session=False)
        db.commit()
        before = db.query(StudentAttribute).filter(StudentAttribute.student_id == 2).count()

        result = asyncio.run(
            agent_loop._handle_present_profile_question(
                {
                    "student_id": 2,
                    "field": "grade",
                    "question": "你现在几年级呀？",
                    "options": [{"label": "初二", "value": "八年级"}],
                    "allow_other": False,
                },
                "student",
                db,
                teacher_id=2,
            )
        )

        assert result["asked"] is True
        assert result["field"] == "grade"
        assert result["options"] == [{"label": "初二", "value": "八年级"}]
        # 展示型工具不落库
        after = db.query(StudentAttribute).filter(StudentAttribute.student_id == 2).count()
        assert before == after

    def test_student_tools_include_conversational_profile_tools(self):
        student_tools = agent_loop.tools_for_role("student")
        names = {t["name"] for t in student_tools}

        assert "update_profile" in names
        assert "present_profile_question" in names

    def test_student_prompt_steers_to_update_profile_and_present_question(self):
        prompt = agent_loop.system_prompt("student")

        assert "present_profile_question" in prompt
        assert "update_profile" in prompt
        # 静默写规则：明确陈述才写，推断转确认题
        assert "只记弟弟明确陈述的事实" in prompt

    def test_student_system_prompt_declares_cold_start_capability(self):
        prompt = agent_loop.system_prompt("student")

        assert "冷启动学习画像" in prompt
        assert "【冷启动进行中】" in prompt

    def test_profile_context_guides_cold_start_when_profile_missing(self, db):
        db.query(StudentAttribute).filter(StudentAttribute.student_id == 2).delete(synchronize_session=False)
        db.commit()

        context = agent_loop._build_profile_context(db, 2)

        assert "【冷启动进行中】" in context
        assert "年级" in context
        assert "grade" in context
        # 新行为：按固定顺序只问当前字段，不再自由列举学期/偏好
        assert "温和询问" not in context

    def test_profile_context_includes_cold_start_fields(self, db):
        profile.save_profile_onboarding(
            db,
            student_id=2,
            req=ProfileOnboardingRequest(
                grade="八年级",
                semester="上册",
                school="示例学校",
                district="苏州工业园区",
                weak_subjects=["英语"],
                study_preferences={"preferred_time": "下午", "session_minutes": 25},
                interests=["篮球"],
            ),
            actor_role="student",
        )

        context = agent_loop._build_profile_context(db, 2)

        assert "八年级" in context
        assert "上册" in context
        assert "示例学校" in context
        assert "英语" in context
        assert "下午" in context
        assert "篮球" in context


class TestChoiceQuestion:
    """U-043 通用动态选择工具 present_choice_question：画像以外的有限选项
    问题（计划协商/任务执行/试卷选择）用可点按钮，不必打字。纯展示不落库。"""

    def test_present_choice_question_is_display_only(self, db):
        result = asyncio.run(
            agent_loop._handle_present_choice_question(
                {
                    "question": "今天先做数学还是英语？",
                    "options": [
                        {"label": "先做数学", "value": "math"},
                        {"label": "先做英语", "value": "english"},
                    ],
                    "allow_other": True,
                },
                "student",
                db,
                teacher_id=2,
            )
        )

        assert result["asked"] is True
        assert result["question"] == "今天先做数学还是英语？"
        assert result["options"] == [
            {"label": "先做数学", "value": "math"},
            {"label": "先做英语", "value": "english"},
        ]
        assert result["allow_other"] is True

    def test_present_choice_question_forces_allow_other_true_even_when_false(self, db):
        result = asyncio.run(
            agent_loop._handle_present_choice_question(
                {
                    "question": "自己写还是看讲解？",
                    "options": [
                        {"label": "自己写", "value": "self"},
                        {"label": "看讲解", "value": "watch"},
                    ],
                    "allow_other": False,
                },
                "student",
                db,
                teacher_id=2,
            )
        )
        # allow_other 即使 AI 传 False 也强制 True
        assert result["allow_other"] is True

    def test_present_choice_question_validates_options(self, db):
        """P2-8：options 少于 2 个有效项返回 error；value 去重；非对象元素被过滤。"""
        # 少于 2 个有效选项 -> error
        r1 = asyncio.run(
            agent_loop._handle_present_choice_question(
                {"question": "x", "options": [{"label": "a", "value": "a"}]},
                "student", db, teacher_id=2,
            )
        )
        assert "error" in r1
        # value 重复 -> 去重后不足 2 个 -> error
        r2 = asyncio.run(
            agent_loop._handle_present_choice_question(
                {"question": "x", "options": [{"label": "a", "value": "dup"}, {"label": "b", "value": "dup"}]},
                "student", db, teacher_id=2,
            )
        )
        assert "error" in r2
        # 非对象元素被过滤，剩下 2 个有效选项 -> 正常
        r3 = asyncio.run(
            agent_loop._handle_present_choice_question(
                {"question": "x", "options": ["str", {"label": "a", "value": "a"}, {"label": "b", "value": "b"}]},
                "student", db, teacher_id=2,
            )
        )
        assert r3["asked"] is True
        assert len(r3["options"]) == 2

    def test_present_choice_question_in_student_tools(self):
        names = {t["name"] for t in agent_loop.tools_for_role("student")}
        assert "present_choice_question" in names

    def test_present_choice_question_in_parent_tools(self):
        names = {t["name"] for t in agent_loop.tools_for_role("teacher")}
        assert "present_choice_question" in names

    def test_student_prompt_mentions_present_choice_question(self):
        prompt = agent_loop.system_prompt("student")
        assert "present_choice_question" in prompt

    def test_choice_question_prompt_forbids_repeating_question_in_body(self):
        prompts = [
            agent_loop.system_prompt("student"),
            agent_loop.system_prompt("teacher"),
            agent_loop.task_system_prompt(),
        ]
        for prompt in prompts:
            # 选择按钮已停用：prompt 明确不调用按钮工具，改用正文编号选项
            assert "不要调用 present_choice_question 按钮工具" in prompt

    def test_choice_question_tool_does_not_instruct_model_to_repeat_question(self):
        tool = next(
            item for item in agent_loop.tools_for_role("student")
            if item["name"] == "present_choice_question"
        )
        assert "下一轮只输出问题文本" not in tool["description"]
        assert "正文不要重复 question 文本" in tool["description"]


class TestFollowUserGoalPrompt:
    """学生只说「任务做完了」这类汇报时，agent 不应自顾自跑预设工具流程
    （生成内容/保存笔记）。回归：曾把汇报当成触发信号，自动 save_note
    了一份单词表笔记，学生根本没要求。"""

    def test_student_prompt_has_follow_user_goal_clause(self):
        prompt = agent_loop.system_prompt("student")

        # 必须有「顺着用户目标」总纲，且明确「汇报」不是生成/保存信号
        assert "顺着" in prompt
        assert "汇报" in prompt
        assert "任务做完了" in prompt

    def test_student_prompt_requires_confirm_before_save_note(self):
        prompt = agent_loop.system_prompt("student")

        # 笔记自动化必须先问、得到明确同意才保存，绝不自动保存
        assert "绝不自动保存" in prompt
        assert "明确同意" in prompt
        # 汇报类发言不触发笔记自动化
        assert "汇报" in prompt
        assert "保存前把 Markdown 草稿" not in prompt
        assert "待确认草稿" in prompt

    def test_parent_prompt_has_follow_user_goal_clause(self):
        prompt = agent_loop.system_prompt("teacher")

        assert "顺着" in prompt
        assert "汇报" in prompt

    def test_parent_prompt_requires_confirm_before_save_note(self):
        prompt = agent_loop.system_prompt("teacher")

        assert "绝不自动保存" in prompt
        assert "明确同意" in prompt
        assert "保存前把 Markdown 草稿" not in prompt
        assert "待确认草稿" in prompt


class TestSharedResponseFormatPrompt:
    def test_all_chat_entry_prompts_share_one_response_format_contract(self):
        prompts = [
            agent_loop.system_prompt("student"),
            agent_loop.system_prompt("teacher"),
            agent_loop.system_prompt("teacher", business_actor="channel_guardian"),
        ]

        for prompt in prompts:
            assert load("agent/response_format") in prompt
            assert "【回复协议】" in prompt
            assert "present_response" in prompt
            assert "禁止 emoji" in prompt


def test_save_note_summary_includes_clickable_note_link(db):
    """save_note 落库后返回的 summary 必须带 #/notes/{id} 格式的可点击 markdown 链接，
    让 agent 在对话里转述时给出能直接点开进详情页的链接（前端 HashRouter）。"""
    result = asyncio.run(
        agent_loop._handle_save_note(
            {
                "student_id": 2,
                "title": "一般过去时",
                "subject": "英语",
                "category": "语法",
                "content": "## 我学到了什么\n\n一般过去时表示过去发生的动作。",
            },
            "teacher",
            db,
            teacher_id=1,
        )
    )

    assert result["saved"] is True
    note_id = result["id"]
    summary = result["summary"]
    # 链接必须是 #/notes/{id} 格式（HashRouter），不能是 /notes/{id} 或完整域名
    expected_link = f"#/notes/{note_id}"
    assert expected_link in summary, f"summary 应含 {expected_link}，实际：{summary}"
    # 必须是 markdown 链接格式 [文字](#/notes/{id})，让前端渲染成可点击 <a>
    assert f"]({expected_link})" in summary, f"summary 应是 markdown 链接格式，实际：{summary}"


class TestRunOutcome:
    """RunOutcome：工具结果带结构化 status，前端不靠 output 猜。"""

    def test_tool_result_succeeded(self, db):
        tool_stream = _mock_tool_stream("query_study_plans", {"student_id": 2, "status": "active"})
        text_stream = _mock_text_stream("好的")
        events: list[tuple[str, dict]] = []

        async def emit(evt_type, data):
            events.append((evt_type, data))

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]):
            asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "看看今天的计划"}],
                    role="student", db=db, teacher_id=2, emit=emit,
                )
            )
        results = [d for t, d in events if t == "tool_result"]
        assert results and results[0]["status"] == "succeeded"

    def test_gateway_blocked_status(self, db):
        # 学生幻觉调 create_study_plan（已移出学生工具集）-> 网关白名单拦 -> blocked
        tool_stream = _mock_tool_stream(
            "create_study_plan",
            {"student_id": 2, "title": "x", "confirmed": True, "items": [{"title": "t"}]},
        )
        text_stream = _mock_text_stream("好的")
        events: list[tuple[str, dict]] = []

        async def emit(evt_type, data):
            events.append((evt_type, data))

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]):
            asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "建个计划"}],
                    role="student", db=db, teacher_id=2, emit=emit,
                )
            )
        results = [d for t, d in events if t == "tool_result"]
        assert results and results[0]["status"] == "blocked"

    def test_business_error_status_failed(self, db):
        # 工具返回业务 error dict -> failed
        tool_stream = _mock_tool_stream("query_study_plans", {"student_id": 2, "status": "active"})
        text_stream = _mock_text_stream("好的")
        events: list[tuple[str, dict]] = []

        async def emit(evt_type, data):
            events.append((evt_type, data))

        with (
            patch.object(agent_loop, "_dispatch", new_callable=AsyncMock, return_value={"error": "业务失败", "saved": False}),
            patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]),
        ):
            asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "查计划"}],
                    role="student", db=db, teacher_id=2, emit=emit,
                )
            )
        results = [d for t, d in events if t == "tool_result"]
        assert results and results[0]["status"] == "failed"


class TestEmptyMessageTurn:
    """空消息轮（注册后冷启动自动触发，前端 skipUserMessage 发空 content）：
    拦截会创建/推进学习数据的工具，防 LLM 面对空输入编造事实落库（复现 841 假报背单词）。"""

    def test_empty_turn_injects_hard_constraint(self):
        # 空消息轮 system 尾部注入「本轮约束」，强制首轮只问冷启动引导问题
        captured = []

        async def fake_stream(*, messages, tools, system):
            captured.append(system)
            return _mock_text_stream("你是几年级？")

        with (
            patch.object(agent_loop, "_build_profile_context", return_value=""),
            patch.object(agent_loop, "_build_learning_memory_context", return_value=""),
            patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=fake_stream),
        ):
            asyncio.run(
                agent_loop.agent_loop(
                    messages=[{"role": "user", "content": ""}],
                    role="student", db=object(), teacher_id=2, student_id=0,
                )
            )
        assert captured and "[本轮约束]" in captured[0]
        assert "只输出一个冷启动引导问题" in captured[0]

    def test_non_empty_turn_no_hard_constraint(self):
        # 用户说真话时不注入空消息约束
        captured = []

        async def fake_stream(*, messages, tools, system):
            captured.append(system)
            return _mock_text_stream("好的")

        with (
            patch.object(agent_loop, "_build_profile_context", return_value=""),
            patch.object(agent_loop, "_build_learning_memory_context", return_value=""),
            patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=fake_stream),
        ):
            asyncio.run(
                agent_loop.agent_loop(
                    messages=[{"role": "user", "content": "我想练口才"}],
                    role="student", db=object(), teacher_id=2, student_id=0,
                )
            )
        assert captured and "[本轮约束]" not in captured[0]

    def test_empty_turn_blocks_record_feedback(self, db):
        # 空 user 消息 + LLM 幻觉调 record_feedback -> 被拦截为 blocked，工具不执行
        tool_stream = _mock_tool_stream(
            "record_feedback",
            {"student_id": 2, "feedback_type": "duration", "content": "今天背了6个单词"},
        )
        text_stream = _mock_text_stream("好的")
        events: list[tuple[str, dict]] = []

        async def emit(evt_type, data):
            events.append((evt_type, data))

        with (
            patch.object(agent_loop, "_dispatch", new_callable=AsyncMock) as dispatch,
            patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]),
        ):
            asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": ""}],
                    role="student", db=db, teacher_id=2, emit=emit,
                )
            )
        results = [d for t, d in events if t == "tool_result"]
        assert results and results[0]["status"] == "blocked"
        assert "尚未发言" in results[0].get("output", "") or "不能调用" in results[0].get("output", "")
        dispatch.assert_not_awaited()

    def test_empty_turn_keeps_query_tool(self, db):
        # 空消息轮查询类工具（query_study_plans）不拦
        tool_stream = _mock_tool_stream("query_study_plans", {"student_id": 2, "status": "active"})
        text_stream = _mock_text_stream("好的")
        events: list[tuple[str, dict]] = []

        async def emit(evt_type, data):
            events.append((evt_type, data))

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]):
            asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": ""}],
                    role="student", db=db, teacher_id=2, emit=emit,
                )
            )
        results = [d for t, d in events if t == "tool_result"]
        assert results and results[0]["status"] == "succeeded"

    def test_non_empty_turn_record_feedback_not_blocked(self, db):
        # 用户真说了话，record_feedback 正常执行
        tool_stream = _mock_tool_stream(
            "record_feedback",
            {"student_id": 2, "feedback_type": "duration", "content": "今天背了6个单词"},
        )
        text_stream = _mock_text_stream("记好了")
        events: list[tuple[str, dict]] = []

        async def emit(evt_type, data):
            events.append((evt_type, data))

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]):
            asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "我今天背了6个单词"}],
                    role="student", db=db, teacher_id=2, emit=emit,
                )
            )
        results = [d for t, d in events if t == "tool_result"]
        assert results and results[0]["status"] == "succeeded"


class TestLoopDetection:
    """循环检测增强：同工具同参数重复调用 ≥3 次被熔断，防 AI 死循环。"""
    def test_repeated_tool_call_blocked(self, db):
        # 单轮 3 次同工具同参数调用：第 3 次被循环检测熔断
        tool_stream = _mock_multi_tool_stream(
            "draft_study_plan",
            {"student_id": 2, "title": "重复计划", "items": [{"title": "t", "minutes": 10}]},
            3,
        )
        text_stream = _mock_text_stream("好的，换个方式")
        with patch.object(
            ai_service, "call_llm_stream", new_callable=AsyncMock,
            side_effect=[tool_stream, text_stream],
        ):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "定个计划"}],
                    role="student", db=db, teacher_id=2,
                )
            )
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert any("重复调用" in m["content"] for m in tool_msgs)

    def test_different_params_not_blocked(self, db):
        """同工具但参数不同（有变化）不触发重复熔断。"""
        s1 = _mock_tool_stream(
            "draft_study_plan",
            {"student_id": 2, "title": "计划A", "items": [{"title": "a", "minutes": 10}]},
        )
        s2 = _mock_tool_stream(
            "draft_study_plan",
            {"student_id": 2, "title": "计划B", "items": [{"title": "b", "minutes": 10}]},
        )
        text_stream = _mock_text_stream("好的")
        with patch.object(
            ai_service, "call_llm_stream", new_callable=AsyncMock,
            side_effect=[s1, s2, text_stream],
        ):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "定计划"}],
                    role="student", db=db, teacher_id=2,
                )
            )
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert not any("重复调用" in m["content"] for m in tool_msgs)


# ============ M1：当前轮日期锚点 + C2 服务端日期回灌 ============


def test_current_date_anchor_injected_into_llm_messages_only(db, monkeypatch):
    """锚点只进 LLM 输入（最新 user 消息带前缀），落库保持用户原文。"""
    from app.features.chat import agent as chat_agent
    from app.features.chat import sessions
    from app.features.agent import date_guard
    from app.models.chat import ChatMessage

    student = db.get(User, 2)
    session = sessions.create_session(db, student, student.id)
    captured: dict[str, list] = {}

    async def fake_agent_loop(messages, **_kwargs):
        captured["llm_messages"] = [dict(m) for m in messages]
        messages.append({"role": "assistant", "content": "好的"})
        return messages

    monkeypatch.setattr(chat_agent.agent_loop, "agent_loop", fake_agent_loop)

    asyncio.run(chat_agent.run_agent_turn(db, session, student, "今天帮我安排数学"))

    anchor = date_guard.current_round_date_anchor()
    llm_user = [m for m in captured["llm_messages"] if m.get("role") == "user"][-1]
    assert llm_user["content"].startswith(anchor)
    assert "今天帮我安排数学" in llm_user["content"]

    persisted_user = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id, ChatMessage.role == "user")
        .one()
    )
    assert persisted_user.content == "今天帮我安排数学"
    assert anchor not in (persisted_user.content or "")


def test_current_date_anchor_persists_across_tool_rounds(db, monkeypatch):
    """工具调用后的下一轮 LLM 沿用同一日期锚点（锚点在消息列表里不丢失）。"""
    from app.features.chat import agent as chat_agent
    from app.features.chat import sessions
    from app.features.agent import date_guard

    student = db.get(User, 2)
    session = sessions.create_session(db, student, student.id)
    captured: list[list[dict]] = []

    async def fake_stream(*, messages, tools, system):
        captured.append([dict(m) for m in messages if m.get("role") == "user"])
        if len(captured) == 1:
            return _mock_tool_stream("query_study_plans", {"student_id": 2})
        return _mock_text_stream("已为你查询计划。")

    monkeypatch.setattr(ai_service, "call_llm_stream", AsyncMock(side_effect=fake_stream))
    asyncio.run(chat_agent.run_agent_turn(db, session, student, "今天帮我查计划"))

    anchor = date_guard.current_round_date_anchor()
    assert len(captured) == 2
    for round_users in captured:
        assert round_users[-1]["content"].startswith(anchor)
        assert "今天帮我查计划" in round_users[-1]["content"]


def test_latest_user_content_strips_date_anchor_for_server_logic():
    """服务端逻辑读到的最新用户内容不带锚点（防 grade/weak_subjects 等被锚点污染）。"""
    from app.features.agent import context, date_guard

    anchor = date_guard.current_round_date_anchor()
    assert context._latest_user_content([{"role": "user", "content": anchor + "1"}]) == "1"
    assert context._latest_user_content([{"role": "user", "content": "1"}]) == "1"
    assert context._latest_user_content([{"role": "assistant", "content": "x"}]) == ""


def test_query_study_plans_returns_server_date(db):
    """query_study_plans 返回服务端 as_of_date，逾期天数以工具返回值为准。"""
    from app.features.agent import date_guard

    recent_past_date = (date.today() - timedelta(days=2)).isoformat()
    study_plan.create_study_plan(
        db,
        student_id=2,
        title="今天数学补漏",
        items=[StudyPlanItemInput(title="先复盘错题", minutes=15)],
        planned_date=recent_past_date,
        created_by=1,
    )

    result = asyncio.run(
        agent_loop._handle_query_study_plans({"student_id": 2}, "teacher", db, teacher_id=1)
    )

    assert result["as_of_date"] == date_guard.local_today().isoformat()
    assert result["plans"][0]["overdue_days"] >= 1
    assert "计划「今天数学补漏」已逾期" in result["reminders"][0]


def test_query_study_plans_tool_description_requires_server_overdue_days():
    """工具描述必须要求逾期天数引用服务端返回值，不能根据聊天历史自行计算。"""
    from app.features.agent.agent_loop import _TOOL_QUERY_STUDY_PLANS

    description = _TOOL_QUERY_STUDY_PLANS["description"]
    assert "overdue_days" in description
    assert "as_of_date" in description
    assert "不得" in description or "不能" in description


def test_profile_context_includes_textbook_versions(db):
    """M2 C：画像注入已存教材版本；新增语文后原英语版本仍保留，下一轮能读到两科版本。"""
    profile.save_profile_onboarding(
        db,
        student_id=2,
        req=ProfileOnboardingRequest(
            grade="八年级",
            weak_subjects=["英语"],
            textbook_versions={"英语": "译林版"},
        ),
        actor_role="student",
    )
    profile.update_profile(
        db,
        student_id=2,
        req=UpdateProfileRequest(textbook_versions={"语文": "人教版"}),
        actor_role="student",
    )

    context = agent_loop._build_profile_context(db, 2)

    assert "已确认教材版本" in context
    assert "人教版" in context
    assert "译林版" in context
