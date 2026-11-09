"""验证 system prompt 注入后端当前本地日期，避免模型自行推断成训练数据日期。

关联 bug：[P1-高][待修复]学习计划-草案日期显示错误.md
"""

from app.config import settings
from app.prompts import load, render
from app.prompts.agent import system_prompt, task_system_prompt


def test_student_prompt_injects_current_date():
    p = system_prompt("student")
    assert "当前日期" in p
    # 含 ISO 日期 YYYY-MM-DD
    assert "20" in p


def test_student_prompt_injects_brand_name():
    p = system_prompt("student")
    assert settings.BRAND_NAME in p
    assert "{{BRAND_NAME}}" not in p


def test_guardian_prompt_injects_current_date():
    p = system_prompt("teacher", business_actor="channel_guardian")
    assert "当前日期" in p


def test_task_prompt_injects_current_date():
    p = task_system_prompt()
    assert "当前日期" in p


# ---- 批次2：提示词收拢到 app/prompts/agent/*.md ----


def test_agent_prompt_templates_loaded_nonempty():
    """8 个本批次收拢模板均可加载且非空。"""
    names = [
        "agent/practice_exam_route",
        "agent/present_response_failure",
        "agent/present_response_correction",
        "agent/plan_guard_failure",
        "agent/plan_guard_correction",
        "agent/plan_draft_history_placeholder",
        "agent/textbook_honesty_correction",
        "agent/textbook_honesty_fixed_reply",
    ]
    for name in names:
        assert load(name).strip(), f"模板不应为空：{name}"


def test_student_prompt_no_unresolved_placeholders():
    """发布给模型的 system prompt 中不允许存在未解析的双花括号占位符。"""
    p = system_prompt("student")
    assert "{{" not in p and "}}" not in p, f"存在未解析占位符：{p}"


def test_task_prompt_no_unresolved_placeholders():
    """task_system_prompt 同样不允许未解析占位符。"""
    p = task_system_prompt()
    assert "{{" not in p and "}}" not in p, f"存在未解析占位符：{p}"


def test_light_practice_question_count_injected():
    """轻练题数来自配置：min/max 替换进 student system prompt，且无未解析占位符。"""
    p = system_prompt("student")
    cfg = settings.config.agent.light_practice
    assert (
        f"出 {cfg.min_questions}-{cfg.max_questions} 道题" in p
    ), "student system prompt 应包含配置驱动的轻练题数范围"
    # 模板占位符已全部替换（由 test_student_prompt_no_unresolved_placeholders 兜底）
    assert "{{light_practice_min_questions}}" not in p
    assert "{{light_practice_max_questions}}" not in p


def test_light_practice_question_count_from_template_placeholders():
    """system_student.md 题数不裸写，统一用配置占位符（防止只改一处漂移）。"""
    content = load("agent/system_student")
    assert "{{light_practice_min_questions}}-{{light_practice_max_questions}}" in content
    assert "{{light_practice_max_questions}}" in content
    # 旧的裸写数字不再出现在模板里（“答完 3 题 / 1-3 道 / 2-3 道” 已参数化）
    import re

    assert not re.search(r"出\s*1-3\s*道|要\s*2-3\s*道|答完\s*3\s*题", content)


def test_textbook_fixed_reply_lesson_placeholder():
    """教材固定兜底模板 {{lesson}} 通过 render() 注入，无未解析占位符。"""
    tpl = load("agent/textbook_honesty_fixed_reply")
    assert "{{lesson}}" in tpl
    rendered = render("agent/textbook_honesty_fixed_reply", lesson="第 5 课")
    assert "第 5 课" in rendered
    assert "{{" not in rendered and "}}" not in rendered
    # 两处 lesson 都被替换
    assert rendered.count("第 5 课") == 2


def test_practice_exam_route_shared_template():
    """试卷路由初始注入与强制补调共用同一模板正文（消除重复实现）。"""
    from app.features.agent.agent_loop import PRACTICE_EXAM_ROUTE_RETRY_PROMPT
    from app.features.agent.context import _PRACTICE_EXAM_ROUTE_HINT

    tpl = load("agent/practice_exam_route")
    assert _PRACTICE_EXAM_ROUTE_HINT == tpl, "context 路由约束应等于模板正文"
    assert PRACTICE_EXAM_ROUTE_RETRY_PROMPT == tpl, "补调纠正应复用同一模板正文"
    # 模板正文不含手写 [路由约束] 标记；稳定标记在注入点附加
    assert "[路由约束]" not in tpl
    assert "create_practice_exam" in tpl


def test_route_hint_marker_at_beginning_and_persistence_filter():
    """P1 防回归：路由约束注入消息稳定标记在正文开头，LLM 截断回显（只复制正文开头、
    不带末尾标记）也会被落库过滤拦截，不展示给学生。"""
    from app.features.agent.context import _PRACTICE_EXAM_ROUTE_HINT, _ROUTE_HINT_INJECTED_MARKER
    from app.features.chat import agent as chat_agent

    # 1) 注入点：稳定标记在正文开头（agent_loop 拼接约定，见 app/features/agent/agent_loop.py）
    injected = _ROUTE_HINT_INJECTED_MARKER + "\n" + _PRACTICE_EXAM_ROUTE_HINT
    assert injected.startswith(_ROUTE_HINT_INJECTED_MARKER), "标记必须在注入消息开头"

    # 2) 截断回显：LLM 只复制正文开头若干字，未带标记
    truncated = _PRACTICE_EXAM_ROUTE_HINT[:12]

    # 3) 落库过滤：命中模板正文前缀 → 不落库
    captured: list[dict] = []

    class FakeDb:
        def __init__(self) -> None:
            self.added = []

        def add(self, obj) -> None:
            self.added.append(obj)

        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            pass

    def fake_persist_message(db, session_id, role, content=None, tool_calls=None, tool_result=None):
        captured.append({"role": role, "content": content})

    db = FakeDb()
    orig = chat_agent.persist_message
    chat_agent.persist_message = fake_persist_message
    try:
        # 普通 assistant 正文应落库
        chat_agent._persist_agent_response_messages(
            db, 1, [{"role": "assistant", "content": "给你出张卷子，点卡片开始。"}], {}, {}
        )
        # 截断回显约束正文开头 → 过滤不落库
        chat_agent._persist_agent_response_messages(db, 1, [{"role": "assistant", "content": truncated}], {}, {})
        # 完整回显带标记 → 过滤不落库
        chat_agent._persist_agent_response_messages(
            db, 1, [{"role": "assistant", "content": injected}], {}, {}
        )
    finally:
        chat_agent.persist_message = orig

    assert len(captured) == 1, f"仅普通正文应落库，实际 {captured}"
    assert captured[0]["content"] == "给你出张卷子，点卡片开始。"
    # 补一个纯标记回显（旧行为）也拦截
    chat_agent._persist_agent_response_messages(
        db, 1, [{"role": "assistant", "content": _ROUTE_HINT_INJECTED_MARKER}], {}, {}
    )
    assert len(captured) == 1
