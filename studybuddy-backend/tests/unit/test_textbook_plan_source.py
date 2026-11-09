"""计划工具教材来源校验测试（M2 C，方案 2.4.5.5-2.4.5.8）。

覆盖（M2 验收）：
- 无来源的具体课文 draft 写入数 0（draft_study_plan 执行前以 retryable error 拦截）
- 中性「课本第 X 课」draft 可成功但 description 含「尚未核验」
- 来源分级：profile_only 不放行具体课名；user_statement/confirmed_material 放行；
  auto_ready_material 保留 OCR 来源和 material_id；unconfirmed_material 不能生成
  带具体课名/作者断言的草案
- 有来源 draft 和正式 plan 的 context_refs 100% 一致（confirm_and_create 传递）
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.core import ai_service
from app.features.agent import agent_loop, study_plan_flow
from app.features.agent.handlers.learning import _handle_draft_study_plan
from app.features.agent.textbook_honesty_guard import (
    TextbookEvidence,
    annotate_draft_textbook_source,
    check_draft_plan_textbook_source,
)
from app.models import StudyPlan, StudyPlanDraft


async def _async_iter(items):
    for item in items:
        yield item


def _chunk(content=None, reasoning=None, tool_call=None, finish=None):
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


def _mock_present_response_stream(text):
    """构造一次 present_response 工具调用流（结构化终态协议）。"""
    args_str = json.dumps({"blocks": [{"type": "paragraph", "text": text}]}, ensure_ascii=False)
    return _async_iter(
        [
            _chunk(tool_call={"index": 0, "id": "call_1", "name": "present_response", "arguments": ""}),
            _chunk(tool_call={"index": 0, "id": None, "name": None, "arguments": args_str}),
            _chunk(finish="tool_calls"),
        ]
    )


def _count_drafts(db):
    return db.query(StudyPlanDraft).filter(StudyPlanDraft.student_id == 2).count()


SPECIFIC_ARGS = {
    "student_id": 2,
    "title": "语文第8课复习",
    "description": "按课本内容安排",
    "items": [{"title": "《美丽的颜色》阅读练习", "minutes": 20}],
}

NEUTRAL_ARGS = {
    "student_id": 2,
    "title": "语文课本第8课复习",
    "description": "按学生课本页面执行",
    "items": [{"title": "朗读第8课课文", "minutes": 15}],
}


# === 纯函数：来源校验（方案 2.4.5.5） ===

def test_no_source_specific_lesson_draft_blocked():
    block = check_draft_plan_textbook_source(dict(SPECIFIC_ARGS), TextbookEvidence(level="none"))
    assert block is not None
    assert "无法确认" in block or "没有可核验" in block


def test_no_source_author_assertion_draft_blocked():
    args = dict(SPECIFIC_ARGS)
    args["items"] = [{"title": "分析课文作者是鲁迅", "minutes": 20}]
    block = check_draft_plan_textbook_source(args, TextbookEvidence(level="none"))
    assert block is not None


def test_profile_only_specific_lesson_draft_blocked():
    block = check_draft_plan_textbook_source(
        dict(SPECIFIC_ARGS), TextbookEvidence(level="profile_only")
    )
    assert block is not None


def test_unconfirmed_material_specific_lesson_draft_blocked():
    block = check_draft_plan_textbook_source(
        dict(SPECIFIC_ARGS), TextbookEvidence(level="unconfirmed_material")
    )
    assert block is not None
    assert "确认" in block


def test_user_statement_specific_lesson_draft_allowed():
    evidence = TextbookEvidence(
        level="user_statement", lesson_no="8", lesson_title="美丽的颜色",
        user_statement_summary="第8课是《美丽的颜色》",
    )
    assert check_draft_plan_textbook_source(dict(SPECIFIC_ARGS), evidence) is None


def test_confirmed_material_specific_lesson_draft_allowed():
    evidence = TextbookEvidence(level="confirmed_material", material_ids=[7])
    assert check_draft_plan_textbook_source(dict(SPECIFIC_ARGS), evidence) is None


def test_auto_ready_material_specific_lesson_draft_allowed():
    evidence = TextbookEvidence(level="auto_ready_material", material_ids=[9])
    assert check_draft_plan_textbook_source(dict(SPECIFIC_ARGS), evidence) is None


def test_neutral_draft_allowed_without_source():
    assert check_draft_plan_textbook_source(dict(NEUTRAL_ARGS), TextbookEvidence(level="none")) is None


def test_non_textbook_draft_not_checked():
    args = {
        "student_id": 2,
        "title": "英语一般过去时复习",
        "items": [{"title": "背20个单词", "minutes": 20}],
    }
    assert check_draft_plan_textbook_source(args, TextbookEvidence(level="none")) is None


# === 纯函数：服务端来源标注（方案 2.4.5.6/2.4.5.8） ===

def test_neutral_draft_annotated_with_unverified_note():
    args = dict(NEUTRAL_ARGS)
    annotate_draft_textbook_source(args, TextbookEvidence(level="none"))
    assert "尚未核验" in args["description"]
    assert "context_refs" not in args or "textbook_source" not in (args.get("context_refs") or {})


def test_user_statement_draft_annotated_with_source():
    evidence = TextbookEvidence(
        level="user_statement", lesson_no="8", lesson_title="美丽的颜色",
        user_statement_summary="第8课是《美丽的颜色》",
    )
    args = dict(SPECIFIC_ARGS)
    annotate_draft_textbook_source(args, evidence)
    assert args["context_refs"]["textbook_source"]["source_type"] == "user_statement"
    assert args["context_refs"]["textbook_source"]["lesson_title"] == "美丽的颜色"
    assert "计划依据" in args["description"]


def test_confirmed_material_draft_keeps_material_ids():
    evidence = TextbookEvidence(level="confirmed_material", material_ids=[7])
    args = dict(SPECIFIC_ARGS)
    annotate_draft_textbook_source(args, evidence)
    assert args["context_refs"]["textbook_source"]["source_type"] == "confirmed_material"
    assert args["context_refs"]["textbook_source"]["material_ids"] == [7]
    assert "material_id=7" in args["description"]


def test_auto_ready_material_draft_keeps_ocr_source():
    evidence = TextbookEvidence(level="auto_ready_material", material_ids=[9])
    args = dict(SPECIFIC_ARGS)
    annotate_draft_textbook_source(args, evidence)
    assert args["context_refs"]["textbook_source"]["source_type"] == "auto_ready_material"
    assert args["context_refs"]["textbook_source"]["material_ids"] == [9]
    assert "识别结果" in args["description"]


def test_unconfirmed_material_neutral_draft_annotated_not_blocked():
    evidence = TextbookEvidence(level="unconfirmed_material", material_ids=[5])
    args = dict(NEUTRAL_ARGS)
    assert check_draft_plan_textbook_source(args, evidence) is None
    annotate_draft_textbook_source(args, evidence)
    assert "尚未核验" in args["description"]
    assert "textbook_source" not in (args.get("context_refs") or {})


def test_model_filled_context_refs_overwritten_by_server():
    evidence = TextbookEvidence(level="user_statement", lesson_no="8", lesson_title="美丽的颜色",
                                user_statement_summary="第8课是《美丽的颜色》")
    args = dict(SPECIFIC_ARGS)
    args["context_refs"] = {"textbook_source": {"source_type": "confirmed_material"}}  # 模型自填，不可信
    annotate_draft_textbook_source(args, evidence)
    assert args["context_refs"]["textbook_source"]["source_type"] == "user_statement"


# === agent_loop 集成：拦截不落库 / 中性成功 / 来源保留 ===

def test_agent_loop_no_source_specific_draft_blocked_no_rows(db):
    """无来源具体课文 draft 写入数 0：网关 retryable 拦截，模型修正后诚实回复。"""
    streams = [
        _mock_tool_stream(
            "draft_study_plan",
            {
                "student_id": 2,
                "title": "语文第8课复习",
                "items": [{"title": "《美丽的颜色》阅读练习", "minutes": 20}],
            },
        ),
        _mock_present_response_stream("草案引用了具体课名，但服务端没有教材来源，我先不能生成。请上传课本目录或告诉我课名。"),
    ]
    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "帮我根据语文课本第8课做个学习计划"}],
                role="student", db=db, teacher_id=2, emit=collect,
            )
        )

    assert _count_drafts(db) == 0
    tool_results = [d for t, d in events if t == "tool_result" and d.get("name") == "draft_study_plan"]
    assert len(tool_results) == 1 and tool_results[0]["status"] == "blocked"
    assert result[-1]["content"] == "草案引用了具体课名，但服务端没有教材来源，我先不能生成。请上传课本目录或告诉我课名。\n"


def test_agent_loop_neutral_draft_succeeds_with_unverified_note(db):
    """中性「课本第 X 课」draft 可成功，description 含「尚未核验」。"""
    streams = [
        _mock_tool_stream(
            "draft_study_plan",
            {
                "student_id": 2,
                "title": "语文课本第8课复习",
                "items": [{"title": "朗读第8课课文", "minutes": 15}],
            },
        ),
        _mock_present_response_stream("已生成语文第8课复习草案，请确认。"),
    ]
    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "帮我根据语文课本第8课做个学习计划"}],
                role="student", db=db, teacher_id=2, emit=collect,
            )
        )

    assert _count_drafts(db) == 1
    tool_results = [d for t, d in events if t == "tool_result" and d.get("name") == "draft_study_plan"]
    assert len(tool_results) == 1 and tool_results[0]["status"] == "succeeded"
    draft = db.query(StudyPlanDraft).filter(StudyPlanDraft.student_id == 2).first()
    assert "尚未核验" in draft.draft_data["description"]
    assert result[-1]["content"] == "已生成语文第8课复习草案，请确认。\n"


def test_draft_to_formal_plan_context_refs_consistent(db):
    """有来源 draft 与正式 plan 的 context_refs 100% 一致（方案 2.4.5.7）。"""
    evidence = TextbookEvidence(
        level="user_statement", lesson_no="8", lesson_title="美丽的颜色",
        user_statement_summary="第8课是《美丽的颜色》",
    )
    args = dict(SPECIFIC_ARGS)
    assert check_draft_plan_textbook_source(args, evidence) is None
    annotate_draft_textbook_source(args, evidence)

    result = asyncio.run(_handle_draft_study_plan(args, "student", db, 2))
    assert result["drafted"] is True
    draft = db.get(StudyPlanDraft, result["draft_id"])
    draft_refs = draft.draft_data["context_refs"]
    assert draft_refs["textbook_source"]["source_type"] == "user_statement"

    confirm = study_plan_flow.confirm_and_create(db, draft.id, draft.revision, 2, None)
    assert confirm.ok
    plan = db.get(StudyPlan, confirm.plan_id)
    assert plan.context_refs == draft_refs  # 100% 一致
