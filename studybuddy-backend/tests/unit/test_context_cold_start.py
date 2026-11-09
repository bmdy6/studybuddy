"""冷启动首次引导：按固定顺序注入硬指令的判定与上下文构造。

覆盖 next_cold_start_field（纯函数判定）与 _build_profile_context 的冷启动注入。
独立于 profile.PROFILE_REQUIRED_FIELDS（后者含 semester/study_preferences，走用时补全）。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.features.agent import context as ctx


def _summary(summary_dict, *, needs_onboarding=None, missing_fields=None):
    """轻量替身，模拟 profile.ProfileSummary（.summary dict + needs_onboarding + missing_fields）。"""
    return SimpleNamespace(
        summary=summary_dict,
        needs_onboarding=needs_onboarding if needs_onboarding is not None else bool(missing_fields),
        missing_fields=missing_fields or [],
    )


def test_cold_start_fields_only_grade_and_weak_subjects():
    assert ctx.COLD_START_FIELDS == ("grade", "weak_subjects")


def test_next_field_returns_grade_when_both_missing():
    assert ctx.next_cold_start_field(_summary({"grade": None, "weak_subjects": []})) == "grade"


def test_next_field_returns_weak_subjects_when_grade_set():
    assert ctx.next_cold_start_field(_summary({"grade": "初一", "weak_subjects": []})) == "weak_subjects"


def test_next_field_returns_none_when_both_set():
    assert ctx.next_cold_start_field(_summary({"grade": "初一", "weak_subjects": ["数学"]})) is None


def test_next_field_respects_order_grade_first():
    assert ctx.next_cold_start_field(_summary({"grade": "", "weak_subjects": None})) == "grade"


def _patch_profile_sources(monkeypatch, summary):
    """把 _build_profile_context 依赖的五个数据源全替换，只留冷启动注入可控。"""
    monkeypatch.setattr(ctx.profile, "get_profile_summary", lambda db, sid: summary)
    monkeypatch.setattr(ctx.attribute, "get_latest_attributes", lambda db, sid: None)
    monkeypatch.setattr(ctx.interests, "list_interests", lambda db, sid: [])
    monkeypatch.setattr(ctx.feedback, "list_feedback", lambda db, sid: [])
    monkeypatch.setattr("app.features.note.service.list_notes", lambda db, sid, status=None: [])


def test_build_profile_context_injects_hard_instruction_when_cold_start_pending(monkeypatch):
    s = _summary({"grade": None, "weak_subjects": []}, needs_onboarding=True, missing_fields=["grade"])
    _patch_profile_sources(monkeypatch, s)

    out = ctx._build_profile_context(MagicMock(), 1)

    assert "【冷启动进行中】" in out
    assert "grade" in out
    # 旧的自由发挥话术不应再出现
    assert "温和询问" not in out
    assert "冷启动画像待补全" not in out


def test_build_profile_context_no_cold_start_instruction_when_done(monkeypatch):
    s = _summary({"grade": "初一", "weak_subjects": ["数学"]}, needs_onboarding=False, missing_fields=[])
    _patch_profile_sources(monkeypatch, s)

    out = ctx._build_profile_context(MagicMock(), 1)

    assert "【冷启动进行中】" not in out


def test_build_profile_context_done_but_semester_missing_uses_light_hint(monkeypatch):
    # 冷启动已完成（grade+weak_subjects 都有），但 semester 缺 -> 用时补全轻提示，不主动追问
    s = _summary(
        {"grade": "初一", "weak_subjects": ["数学"], "semester": None},
        needs_onboarding=True,
        missing_fields=["semester"],
    )
    _patch_profile_sources(monkeypatch, s)

    out = ctx._build_profile_context(MagicMock(), 1)

    assert "【冷启动进行中】" not in out
    assert "用时补全" in out or "不必现在追问" in out


def test_non_empty_user_turn_defers_profile_question(monkeypatch):
    """M2 D：非空用户轮不注入「本轮只问」强指令，改为 deferred 提示（主线最多末段一个画像问题）。"""
    s = _summary({"grade": None, "weak_subjects": []}, needs_onboarding=True, missing_fields=["grade"])
    _patch_profile_sources(monkeypatch, s)

    out = ctx._build_profile_context(MagicMock(), 1, latest_user_content="我语文书第8课是哪篇？")

    assert "【冷启动进行中】" not in out
    assert "本轮只问" not in out
    assert "最后一段" in out  # 冷启动问题只能出现在最后一个独立段落
    assert "年级" in out


def test_empty_user_turn_keeps_active_cold_start(monkeypatch):
    """M2 D：空消息轮（冷启动自动触发）继续注入 active 硬指令，本轮只问一个字段。"""
    s = _summary({"grade": None, "weak_subjects": []}, needs_onboarding=True, missing_fields=["grade"])
    _patch_profile_sources(monkeypatch, s)

    out = ctx._build_profile_context(MagicMock(), 1, latest_user_content="")

    assert "【冷启动进行中】" in out
    assert "本轮只问" in out


def test_forced_profile_chips_grade_even_when_llm_called_update_profile_without_grade(monkeypatch):
    """LLM 调了 update_profile 但没传 grade，grade 仍 missing 时，_forced 应强制补 grade。

    回归 testverify(836)：冷启动点八年级选项，LLM 调 update_profile 漏传 grade，grade 丢失。
    """
    import json
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "present_profile_question", "arguments": json.dumps({"field": "grade"})}}]},
        {"role": "user", "content": "八年级"},
        {"role": "assistant", "tool_calls": [{"id": "t2", "type": "function", "function": {"name": "update_profile", "arguments": json.dumps({"student_id": 1})}}]},
    ]
    summary = _summary({"grade": None}, needs_onboarding=True, missing_fields=["grade", "study_preferences"])
    monkeypatch.setattr(ctx.profile, "get_profile_summary", lambda db, sid: summary)
    forced = ctx._forced_profile_onboarding_tool(messages, MagicMock(), 1)
    assert forced is not None
    assert forced["name"] == "update_profile"
    assert forced["args"]["grade"] == "八年级"


def test_forced_profile_skips_when_llm_already_saved_grade(monkeypatch):
    """LLM 调 update_profile 存了 grade，grade 不再 missing，_forced 不重复补。"""
    import json
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "present_profile_question", "arguments": json.dumps({"field": "grade"})}}]},
        {"role": "user", "content": "八年级"},
        {"role": "assistant", "tool_calls": [{"id": "t2", "type": "function", "function": {"name": "update_profile", "arguments": json.dumps({"student_id": 1, "grade": "八年级"})}}]},
    ]
    summary = _summary({"grade": "八年级"}, needs_onboarding=True, missing_fields=["study_preferences"])
    monkeypatch.setattr(ctx.profile, "get_profile_summary", lambda db, sid: summary)
    forced = ctx._forced_profile_onboarding_tool(messages, MagicMock(), 1)
    assert forced is None


def test_extract_profile_args_colloquial_bu_math():
    """回归 testverify3(840)：「我是八年级学生，想先补数学」应同时抽出 grade+weak_subjects。

    修复前 weak_subjects 只认科目后置薄弱词（数学比较薄弱），「想先补数学」抽不到 →
    又因 len(args)>=3 门槛把 grade 一起丢弃，画像完全没落库。
    """
    args = ctx._extract_profile_onboarding_args("我是八年级学生，想先补数学", 1)
    assert args is not None
    assert args["grade"] == "八年级"
    assert args["weak_subjects"] == ["数学"]


def test_extract_profile_args_grade_only_not_dropped():
    """只说了年级（没提薄弱科目）时，grade 也应落库，不能被 weak_subjects 缺失连坐丢弃。"""
    args = ctx._extract_profile_onboarding_args("我是八年级学生", 1)
    assert args is not None
    assert args["grade"] == "八年级"


def test_extract_profile_args_subject_after_weak_word():
    """原有模式保持：科目后置薄弱词仍能抽出。"""
    args = ctx._extract_profile_onboarding_args("我数学比较薄弱，英语也不好", 1)
    assert args is not None
    assert args["weak_subjects"] == ["数学", "英语"]


def test_extract_profile_args_weak_subjects_only():
    """只说薄弱科目（无年级）也能落库。"""
    args = ctx._extract_profile_onboarding_args("我想补一补英语", 1)
    assert args is not None
    assert args["weak_subjects"] == ["英语"]


def test_extract_profile_args_no_signal_returns_none():
    """没有任何画像信号时不落库。"""
    assert ctx._extract_profile_onboarding_args("今天天气不错", 1) is None
