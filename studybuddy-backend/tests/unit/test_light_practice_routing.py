"""P1 修复：轻练后试卷路由被上下文污染 —— 路由意图检测与约束注入单测。

复现场景：轻练会话（多轮 grade_light_answer + 讲解）后发「做一套卷子」，
LLM 被轻练语境带偏，不调 create_practice_exam。
修复：检测高置信试卷意图 → 注入强路由约束消息，纠偏 LLM 路由。
"""

import pytest

from app.features.agent.context import practice_exam_route_hint


def _light_history():
    """模拟走完轻练 3 题的会话历史（bug 复现场景的上下文污染源）。"""
    return [
        {"role": "user", "content": "练几道口算题吧"},
        {"role": "assistant", "content": "第一道：12 × 15 = ?"},
        {"role": "user", "content": "180"},
        {"role": "assistant", "content": "答对了！12×15=180。第二道：72 ÷ 9 = ?"},
        {"role": "user", "content": "8"},
        {"role": "assistant", "content": "对。第三道：15 × 15 = ?"},
        {"role": "user", "content": "225"},
        {"role": "assistant", "content": "全对！你答对了 3 道。要不要继续练，还是整理成正式练习？"},
    ]


class TestPracticeExamRouteHint:
    """高置信试卷意图 → 返回约束提示；非试卷意图 → None。"""

    def test_do_a_paper_after_light_practice_returns_hint(self):
        """bug 复现核心：轻练历史后发「做一套卷子」必须命中试卷路由。"""
        messages = _light_history() + [{"role": "user", "content": "做一套卷子"}]
        hint = practice_exam_route_hint(messages)
        assert hint is not None
        assert "create_practice_exam" in hint

    def test_explicit_math_paper_returns_hint(self):
        """「给我出一套数学试卷，10道题」明确试卷语义 → 命中。"""
        messages = _light_history() + [{"role": "user", "content": "给我出一套数学试卷，10道题"}]
        assert practice_exam_route_hint(messages) is not None

    def test_do_a_set_of_questions_returns_hint(self):
        """「做套题」正式套题语义 → 命中。"""
        messages = [{"role": "user", "content": "做套题"}]
        assert practice_exam_route_hint(messages) is not None

    def test_light_practice_intent_not_hit(self):
        """「练几道口算题」是轻练 → 不命中。"""
        messages = [{"role": "user", "content": "练几道口算题"}]
        assert practice_exam_route_hint(messages) is None

    def test_casual_single_question_not_hit(self):
        """「考我一道」随口单题 → 不命中（轻练）。"""
        messages = [{"role": "user", "content": "考我一道数学题"}]
        assert practice_exam_route_hint(messages) is None

    def test_query_history_paper_not_hit(self):
        """「看看我之前的试卷」是查询 → 不命中（防误触出卷）。"""
        messages = [{"role": "user", "content": "看看我之前的试卷在哪"}]
        assert practice_exam_route_hint(messages) is None

    def test_light_context_discussing_this_set_not_hit(self):
        """「这套题我明白了」是讨论轻练题目 → 不命中。"""
        messages = [{"role": "user", "content": "这套题我明白了"}]
        assert practice_exam_route_hint(messages) is None

    def test_already_routed_round_not_reinject(self):
        """上一轮已注入过路由约束（含稳定标记）→ 不重复注入。"""
        messages = _light_history() + [
            {"role": "user", "content": "做一套卷子"},
            {"role": "system", "content": "[route:create_practice_exam]"},
            {"role": "assistant", "content": "好的，这就为你出一套卷子。", "tool_calls": [{"function": {"name": "create_practice_exam"}}]},
        ]
        assert practice_exam_route_hint(messages) is None

    def test_force_retry_after_inject_not_reinject(self):
        """补调轮后（含稳定标记的 system 消息仍在历史）→ 下一轮不再注入。"""
        messages = _light_history() + [
            {"role": "user", "content": "做一套卷子"},
            {"role": "system", "content": "用户明确要求做正式试卷，本轮必须调用 create_practice_exam 生成自练卷并分发。\n[route:create_practice_exam]"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "create_practice_exam"}}]},
        ]
        assert practice_exam_route_hint(messages) is None

    def test_empty_or_short_no_hit(self):
        """空消息/普通闲聊 → 不命中。"""
        assert practice_exam_route_hint([{"role": "user", "content": "今天天气不错"}]) is None
        assert practice_exam_route_hint([]) is None
