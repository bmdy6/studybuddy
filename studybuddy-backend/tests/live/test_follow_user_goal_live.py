"""Agent 顺着用户目标 live 测试：真实 MiMo 验证汇报场景不被误读成生成/保存信号。

⚠️ @pytest.mark.live：默认 skip，带 --run-live 才跑（耗 token、需网络+真实 key）。
跑法：.venv/bin/python -m pytest tests/live/test_follow_user_goal_live.py --run-live -s --no-cov

回归场景：学生只说「今天的任务做完了」时，旧 prompt 让 agent 自动 save_note 了一份
「英语第一单元单词表（简版）」笔记，学生根本没要求。本测试真实发 MiMo，断言本轮：
- 不调用 save_note（不自动保存笔记）
- 不调用 create_exam / 不生成新内容
- 回复是肯定 + 问下一步，而不是「已生成单词表/已保存笔记」
"""

import asyncio
import json
import re
from typing import Any

import pytest

from app.features.agent import agent_loop
from app.models.note import Note
from app.features.p2.schemas import StudyPlanItemInput
from app.features.p2 import study_plan

STUDENT_ID = 2


def _extract_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 agent_loop 返回消息中抽取 assistant 发起的工具调用及参数。"""
    calls = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tool_call in msg.get("tool_calls") or []:
            function = tool_call.get("function", {})
            try:
                args = json.loads(function.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            calls.append({"name": function.get("name"), "args": args})
    return calls


def _assistant_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(str(msg.get("content") or "") for msg in messages if msg.get("role") == "assistant")


def _assert_compact_numbered_questions(text: str) -> None:
    numbered_indexes = [
        index
        for index, line in enumerate(text.splitlines())
        if re.match(r"^\d+\.\s+", line.strip())
    ]
    assert len(numbered_indexes) >= 3, f"应输出至少 3 条编号问题，实际回复：{text}"
    first_three = numbered_indexes[:3]
    assert first_three == list(range(first_three[0], first_three[0] + 3)), (
        f"编号项之间不应留空行，实际回复：{text}"
    )


@pytest.mark.live
class TestFollowUserGoalLive:
    """真实 MiMo 验证：汇报类发言不应触发笔记/内容生成工具。"""

    def test_report_done_does_not_save_note_or_generate_content(self, db):
        """学生汇报「今天的任务做完了」时，agent 不应自动 save_note 或生成单词表。"""
        # 给学生一个进行中的英语单词计划，复现截图上下文
        plan = study_plan.create_study_plan(
            db,
            student_id=STUDENT_ID,
            title="英语第一单元单词背诵",
            items=[StudyPlanItemInput(title="背诵第一单元 15 个单词", minutes=20)],
            created_by=STUDENT_ID,
        )
        try:
            before_note_ids = {
                row[0]
                for row in db.query(Note.id).filter(Note.student_id == STUDENT_ID).all()
            }

            messages = asyncio.run(
                agent_loop.agent_loop(
                    [
                        {
                            "role": "user",
                            "content": "今天的任务做完了",
                        }
                    ],
                    "student",
                    db,
                    STUDENT_ID,
                )
            )

            calls = _extract_tool_calls(messages)
            call_names = [call["name"] for call in calls]
            text = _assistant_text(messages)

            # 硬性断言：汇报不触发笔记保存、不触发出题、不生成新内容
            assert "save_note" not in call_names, (
                f"汇报「任务做完了」不应自动 save_note，实际调了: {call_names}"
            )
            assert "create_exam" not in call_names, (
                f"汇报不应触发出题，实际调了: {call_names}"
            )

            # 不应新增笔记
            new_notes = [
                note
                for note in db.query(Note).filter(Note.student_id == STUDENT_ID).all()
                if note.id not in before_note_ids
            ]
            assert not new_notes, (
                f"汇报不应新增笔记，但出现了: {[(n.id, n.title) for n in new_notes]}"
            )

            # 回复不应出现「已生成/已保存笔记/单词表已生成」这类自作主张的内容
            for forbidden in ["已保存笔记", "单词表已生成", "已生成单词表", "简版单词表已生成"]:
                assert forbidden not in text, f"回复不应出现「{forbidden}」：{text}"
        finally:
            # 清理临时计划，避免污染
            study_plan.archive_study_plan(db, plan_id=plan.id)

    @pytest.mark.parametrize(
        ("role", "business_actor", "prompt_text"),
        [
            (
                "student",
                None,
                "不要调用工具。先用一句话回应，再连续用 3 条编号问题确认我今天学习计划的科目、可用时长和优先顺序。编号项之间不要留空行。",
            ),
            (
                "teacher",
                None,
                "不要调用工具。先用一句话回应，再连续用 3 条编号问题确认我想帮示例学生安排学习的科目、可用时长和优先顺序。编号项之间不要留空行。",
            ),
            (
                "teacher",
                "channel_guardian",
                "不要查询数据。先用一句话回应，再连续用 3 条编号问题确认我想调整孩子学习陪伴的关注科目、可用时长和优先顺序。编号项之间不要留空行。",
            ),
        ],
    )
    def test_all_chat_roles_follow_compact_response_format(self, db, role, business_actor, prompt_text):
        """网页/微信共用的三类 Agent 均应输出连续的紧凑 Markdown 列表。"""
        messages = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": prompt_text}],
                role,
                db,
                STUDENT_ID if role == "student" else 1,
                student_id=STUDENT_ID if role == "teacher" else 0,
                business_actor=business_actor,
            )
        )

        _assert_compact_numbered_questions(_assistant_text(messages))
