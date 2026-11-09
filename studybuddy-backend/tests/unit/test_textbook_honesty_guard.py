"""教材事实诚实守卫测试（M2 C + D）。

覆盖（方案 2.4.5 + M2 验收）：
- 无来源 3 种断言句式拦截 3/3（第X课是《Y》/ 作者是Y / 根据《Y》这篇课文做计划）
- 含「无法确认/可能/请核对/是不是」的 3 个诚实反例误拦 0/3
- 来源分级：profile_only 不放行具体课名；user_statement/confirmed_material 放行；
  auto_ready_material 必须带 OCR 归因；unconfirmed_material 必须带不确定提示
- 无来源连续违规：固定诚实回复 1/1，具体课名/作者/内容梗概命中数 0
- 教材敏感轮判定、用户陈述/素材证据提取、画像版本退路
- 非空教材问题轮 system 不含「本轮只问 weak_subjects」强指令（M2 D）
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import ai_service
from app.features.agent import agent_loop
from app.features.agent.textbook_honesty_guard import (
    TextbookEvidence,
    build_textbook_evidence,
    contains_deterministic_textbook_assertion,
    extract_lesson_no,
    is_textbook_sensitive_round,
    is_textbook_sensitive_text,
    textbook_body_reply_blocked,
    textbook_honesty_fixed_reply,
)
from app.features.p2.schemas import ProfileOnboardingRequest
from app.features.p2 import profile


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


# === 无来源断言句式正例：拦截 3/3 ===

BLOCKED_ASSERTIONS = [
    "人教版八年级语文上册第8课是《美丽的颜色》，作者是艾芙·居里。",
    "这篇课文的作者是鲁迅。",
    "根据《美丽的颜色》这篇课文来做计划，先读一遍再做题。",
]


@pytest.mark.parametrize("text", BLOCKED_ASSERTIONS)
def test_deterministic_assertions_blocked_without_source(text):
    assert contains_deterministic_textbook_assertion(text)
    assert textbook_body_reply_blocked(text, "none")


# === 诚实反例：误拦 0/3 ===

HONEST_COUNTEREXAMPLES = [
    "我现在无法确认你的教材版本，第8课是哪篇需要你告诉我或上传课本。",
    "人教版语文书第8课可能是《美丽的颜色》，请核对一下你课本的目录。",
    "你说的是不是《美丽的颜色》？我不确定你用的是哪个版本。",
]


@pytest.mark.parametrize("text", HONEST_COUNTEREXAMPLES)
def test_honest_counterexamples_not_blocked(text):
    assert not contains_deterministic_textbook_assertion(text)
    assert not textbook_body_reply_blocked(text, "none")


# === 来源分级（方案 2.4.1） ===

def test_profile_only_does_not_allow_specific_lesson():
    assert textbook_body_reply_blocked("第8课是《美丽的颜色》", "profile_only")


def test_user_statement_allows_specific_lesson():
    assert not textbook_body_reply_blocked("第8课是《美丽的颜色》", "user_statement")


def test_confirmed_material_allows_specific_lesson():
    assert not textbook_body_reply_blocked("第8课是《美丽的颜色》", "confirmed_material")


def test_auto_ready_material_requires_ocr_attribution():
    assert textbook_body_reply_blocked("第8课是《美丽的颜色》", "auto_ready_material")
    assert not textbook_body_reply_blocked(
        "根据你上传的图片识别结果，第8课是《美丽的颜色》。", "auto_ready_material"
    )


def test_unconfirmed_material_requires_uncertainty_hint():
    assert textbook_body_reply_blocked("第8课是《美丽的颜色》", "unconfirmed_material")
    assert not textbook_body_reply_blocked(
        "图片里暂时识别到第8课是《美丽的颜色》，可能有误，请核对。", "unconfirmed_material"
    )


# === 固定诚实回复：不含具体课名/作者/内容梗概 ===

def test_fixed_reply_has_no_specific_content():
    reply = textbook_honesty_fixed_reply("8")
    assert "不能确认" in reply
    assert "《" not in reply and "》" not in reply  # 具体课名 0
    assert "作者" not in reply  # 作者 0
    for word in ("故事", "讲述", "记叙", "居里", "镭"):  # 内容梗概 0
        assert word not in reply


def test_fixed_reply_embeds_lesson_no():
    assert "第 8 课" in textbook_honesty_fixed_reply("8")


def test_extract_lesson_no():
    assert extract_lesson_no("人教版八年级语文上册第8课是哪篇？") == "8"
    assert extract_lesson_no("随便聊聊") == ""


# === 敏感轮判定 ===

def test_textbook_sensitive_round_detected():
    messages = [{"role": "user", "content": "人教版八年级语文上册第8课是哪篇课文？"}]
    assert is_textbook_sensitive_round(messages)


def test_non_textbook_round_not_sensitive():
    messages = [{"role": "user", "content": "今天天气不错"}]
    assert not is_textbook_sensitive_round(messages)


def test_sensitive_text_keywords():
    assert is_textbook_sensitive_text("帮我根据语文课本做个计划")
    assert is_textbook_sensitive_text("第8课")
    assert not is_textbook_sensitive_text("今天学英语时态")


# === 证据提取（方案 2.4.5.2） ===

def _messages_with_read_material(content_source, material_id=7):
    return [
        {"role": "user", "content": "看看我上传的课本目录"},
        {"role": "assistant", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "read_material", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": json.dumps(
            {"material_id": material_id, "content_source": content_source, "needs_confirmation": content_source != "confirmed_markdown"}
        )},
    ]


def test_evidence_confirmed_material_from_current_round():
    ev = build_textbook_evidence(_messages_with_read_material("confirmed_markdown"))
    assert ev.level == "confirmed_material"
    assert ev.material_ids == [7]


def test_evidence_auto_ready_material_from_current_round():
    ev = build_textbook_evidence(_messages_with_read_material("auto_ready_markdown"))
    assert ev.level == "auto_ready_material"
    assert ev.material_ids == [7]


def test_evidence_unconfirmed_material_from_current_round():
    ev = build_textbook_evidence(_messages_with_read_material("recognized_markdown"))
    assert ev.level == "unconfirmed_material"
    assert ev.material_ids == [7]


def test_evidence_ignores_historical_material_before_user():
    """素材必须当前轮读取成功：最新 user 之前的 read_material 不算来源。"""
    messages = [
        {"role": "user", "content": "昨天上传了课本"},
        {"role": "assistant", "tool_calls": [{"id": "t0", "type": "function", "function": {"name": "read_material", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t0", "content": json.dumps({"material_id": 3, "content_source": "confirmed_markdown"})},
        {"role": "user", "content": "第8课是哪篇？"},
    ]
    ev = build_textbook_evidence(messages)
    assert ev.level == "none"


def test_evidence_user_statement_latest_wins():
    messages = [
        {"role": "user", "content": "我这本语文书第8课是《故乡》"},
        {"role": "user", "content": "第8课是《社戏》才对"},
    ]
    ev = build_textbook_evidence(messages)
    assert ev.level == "user_statement"
    assert ev.lesson_title == "社戏"


def test_evidence_profile_only_fallback():
    ev = build_textbook_evidence([{"role": "user", "content": "第8课是哪篇？"}], {"语文": "人教版"})
    assert ev.level == "profile_only"


def test_evidence_none_without_source():
    ev = build_textbook_evidence([{"role": "user", "content": "第8课是哪篇？"}])
    assert ev.level == "none"


# === agent_loop 接入 ===

def test_textbook_guard_twice_violation_fixed_reply(db):
    """无来源连续违规：最终固定诚实回复 1/1，具体课名/作者/内容梗概命中数 0。"""
    # 预置完整画像，避免「八年级」被冷启动强制工具劫持为 update_profile
    profile.save_profile_onboarding(
        db, student_id=2,
        req=ProfileOnboardingRequest(grade="八年级", weak_subjects=["英语"]),
        actor_role="student",
    )
    streams = [
        _mock_text_stream("人教版八年级语文上册第8课是《美丽的颜色》，作者是艾芙·居里。"),
        _mock_text_stream("第8课是《美丽的颜色》，讲的是居里夫妇提炼镭的故事。"),
    ]
    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "人教版八年级语文上册第8课是哪篇课文？"}],
                role="student", db=db, teacher_id=2, emit=collect,
            )
        )

    final = result[-1]["content"]
    assert final == textbook_honesty_fixed_reply("8")
    # 具体课名/作者/内容梗概命中数 0
    for word in ("美丽的颜色", "艾芙", "居里", "镭", "提炼", "故事"):
        assert word not in final
    # 被拒断言不进历史
    assert not any(
        m.get("role") == "assistant" and "美丽的颜色" in (m.get("content") or "") for m in result
    )


def test_textbook_guard_honest_first_reply_not_blocked(db):
    """模型第一轮就说无法确认时不拦截，直接放行。"""
    profile.save_profile_onboarding(
        db, student_id=2,
        req=ProfileOnboardingRequest(grade="八年级", weak_subjects=["英语"]),
        actor_role="student",
    )
    honest = "我现在没有可核验的教材目录，不能确认你这本书第 8 课是哪篇。请上传封面版权页或告诉我教材版本。"
    streams = [_mock_present_response_stream(honest)]
    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "人教版八年级语文上册第8课是哪篇课文？"}],
                role="student", db=db, teacher_id=2,
            )
        )
    assert result[-1]["content"] == honest + "\n"


def test_textbook_question_system_excludes_strong_cold_start(db, monkeypatch):
    """M2 D：非空教材问题轮 system 不含「本轮只问 weak_subjects」强指令；教材纪律已注入。"""
    # 画像缺 weak_subjects -> 冷启动未完成，但非空用户轮走 deferred
    profile.save_profile_onboarding(
        db, student_id=2, req=ProfileOnboardingRequest(grade="八年级"), actor_role="student"
    )
    captured: dict = {}
    honest = "我现在没有可核验的教材目录，不能确认你这本书第 8 课是哪篇。请上传封面版权页或告诉我教材版本。"

    async def fake_stream(messages, tools, system, emit, *, buffer_text=False, tool_choice=None):
        captured["system"] = system
        await emit("text", {"content": honest})
        return honest, [], ""

    monkeypatch.setattr(agent_loop, "_stream_llm_turn", fake_stream)
    result = asyncio.run(
        agent_loop.agent_loop(
            [{"role": "user", "content": "人教版八年级语文上册第8课是哪篇课文？"}],
            role="student", db=db, teacher_id=2,
        )
    )
    assert result[-1]["content"] == honest + "\n"
    system = captured["system"]
    assert "本轮只问" not in system
    assert "最后一段" in system  # 冷启动问题只能出现在最后一个独立段落
    assert "教材事实诚实纪律" in system
    assert "weak_subjects" not in system or "本轮只问" not in system
