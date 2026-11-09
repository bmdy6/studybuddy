"""P2 修复：轻练轮禁止 record_feedback 落库——上下文检测单测。

复现场景：轻练轮（发「练几道口算题」后）AI 调 record_feedback 把负面推断落库
（learning_feedback 5395/5396）。修复：agent_loop 在轻练轮拒绝 record_feedback。
"""

import pytest

from app.features.agent.context import in_light_practice_round


def _light_history():
    """轻练轮上下文：用户发轻练意图，AI 出题，学生作答，grade_light_answer 判分。"""
    return [
        {"role": "user", "content": "练几道口算题吧"},
        {"role": "assistant", "content": "第一道：12 × 15 = ?"},
        {"role": "user", "content": "180"},
        {"role": "assistant", "content": "答对了！第二道：72 ÷ 9 = ?"},
        {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "grade_light_answer", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": '{"is_correct": true}'},
        {"role": "assistant", "content": "对！继续第三道：15 × 15 = ?"},
    ]


class TestInLightPracticeRound:
    def test_light_practice_round_detected(self):
        """轻练意图 + 判分进行中 → 判定为轻练轮（record_feedback 应被拒）。"""
        assert in_light_practice_round(_light_history()) is True

    def test_light_intent_without_answer_still_light(self):
        """刚发轻练意图（还没作答）→ 仍是轻练轮。"""
        messages = [
            {"role": "user", "content": "随便练几道口算题"},
            {"role": "assistant", "content": "好，第一道：3 × 7 = ?"},
        ]
        assert in_light_practice_round(messages) is True

    def test_formal_exit_after_light_not_light(self):
        """轻练后说「做一套卷子」（正式退出）→ 不再算轻练轮。"""
        messages = _light_history() + [{"role": "user", "content": "做一套卷子"}]
        assert in_light_practice_round(messages) is False

    def test_normal_conversation_not_light(self):
        """普通学习会话（无轻练意图）→ 不是轻练轮。"""
        messages = [
            {"role": "user", "content": "帮我复习一下一元二次方程"},
            {"role": "assistant", "content": "好，先看求根公式。"},
        ]
        assert in_light_practice_round(messages) is False

    def test_light_ended_by_student_not_light(self):
        """学生说「不练了」结束轻练 → 不再算轻练轮。"""
        messages = _light_history() + [{"role": "user", "content": "不练了，我去做别的"}]
        assert in_light_practice_round(messages) is False

    def test_empty_messages_not_light(self):
        """空消息 → 不是轻练轮。"""
        assert in_light_practice_round([]) is False
