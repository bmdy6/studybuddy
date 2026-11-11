"""Agent 工具 live 测试：真实 MiMo 验证推荐资源与保存笔记闭环。

⚠️ @pytest.mark.live：默认 skip，带 --run-live 才跑（耗 token、需网络+真实 key）。
跑法：.venv/bin/python -m pytest tests/live/test_agent_tools_live.py --run-live -s --no-cov

覆盖三个此前只做 mock/handler 验证的高风险点：
1. recommend_resource：自然语言推荐视频 → 真实选工具 → 真实搜 B站 → 推荐落库 → 回复含可点击视频链接。
2. save_note：示例学生确认保存笔记 → 真实选工具 → 生成结构化 Markdown → 草稿笔记落库。
3. archive_study_plan：学生明确确认移出计划 → 真实选工具 → 归档计划并保留历史。
"""

import asyncio
import json
from typing import Any

import pytest

from app.features.agent import agent_loop
from app.models.note import Note
from app.models.p2 import ResourceRecommendation
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
    """拼接 agent_loop 返回的 assistant 正文，便于断言最终回复内容。"""
    return "\n".join(str(msg.get("content") or "") for msg in messages if msg.get("role") == "assistant")


@pytest.mark.live
class TestAgentToolsLive:
    """真实 MiMo 工具选择测试：验证高风险 agent 行为不只停留在 mock。"""

    def test_agent_recommend_resource_searches_bilibili_and_saves_record(self, db):
        """示例学生自然语言请求视频推荐时，应调 recommend_resource、搜到具体 B站视频并落库。"""
        before_ids = {row[0] for row in db.query(ResourceRecommendation.id).filter(ResourceRecommendation.student_id == STUDENT_ID).all()}

        messages = asyncio.run(
            agent_loop.agent_loop(
                [
                    {
                        "role": "user",
                        "content": "请给我推荐一个适合初中生看的英语一般过去时讲解视频，要具体 B站链接。",
                    }
                ],
                "student",
                db,
                STUDENT_ID,
            )
        )

        calls = _extract_tool_calls(messages)
        recommend_calls = [call for call in calls if call["name"] == "recommend_resource"]
        assert recommend_calls, f"应调 recommend_resource，实际调了: {[call['name'] for call in calls]}"

        args = recommend_calls[0]["args"]
        assert args.get("student_id") == STUDENT_ID
        keyword = str(args.get("keyword") or "")
        assert "英语" in keyword and ("过去" in keyword or "past" in keyword.lower())

        new_records = [
            rec for rec in db.query(ResourceRecommendation).filter(ResourceRecommendation.student_id == STUDENT_ID).all() if rec.id not in before_ids
        ]
        assert new_records, "recommend_resource 应新增资源推荐记录"
        assert any(rec.platform == "bilibili" and rec.url.startswith("https://www.bilibili.com/video/") for rec in new_records)
        assert "https://www.bilibili.com/video/" in _assistant_text(messages)

    def test_agent_save_note_creates_structured_draft_note_after_confirmation(self, db):
        """示例学生确认保存笔记后，应调 save_note 并落库包含三段结构的草稿笔记。"""
        before_ids = {row[0] for row in db.query(Note.id).filter(Note.student_id == STUDENT_ID).all()}
        seed_messages = [
            {
                "role": "user",
                "content": "刚才你讲了英语一般过去时：规则动词加 ed，不规则动词要单独记，否定句用 didn't + 动词原形。",
            },
            {"role": "assistant", "content": "要不要把这个知识点整理成笔记？"},
            {
                "role": "user",
                "content": "要，帮我保存成笔记，标题叫一般过去时易错点，内容包括我学到了什么、关键例子、易错点。",
            },
        ]

        messages = asyncio.run(agent_loop.agent_loop(seed_messages, "student", db, STUDENT_ID))

        calls = _extract_tool_calls(messages)
        save_calls = [call for call in calls if call["name"] == "save_note"]
        assert save_calls, f"应调 save_note，实际调了: {[call['name'] for call in calls]}"

        args = save_calls[0]["args"]
        assert args.get("student_id") == STUDENT_ID
        assert args.get("title") == "一般过去时易错点"
        content = str(args.get("content") or "")
        for heading in ["我学到了什么", "关键例子", "易错点"]:
            assert heading in content

        new_notes = [note for note in db.query(Note).filter(Note.student_id == STUDENT_ID).all() if note.id not in before_ids]
        assert len(new_notes) == 1
        note = new_notes[0]
        assert note.title == "一般过去时易错点"
        assert note.type == "study_record"
        assert note.status == "draft"
        assert note.category
        assert "一般过去时" in note.content
        assert all(heading in note.content for heading in ["我学到了什么", "关键例子", "易错点"])

    def test_agent_archives_confirmed_study_plan_and_keeps_history(self, db):
        """学生明确确认移出计划时，应选择归档工具且保留计划记录。"""
        plan = study_plan.create_study_plan(
            db,
            student_id=STUDENT_ID,
            title="Live 测试临时计划",
            items=[StudyPlanItemInput(title="完成一组英语练习", minutes=10)],
            created_by=STUDENT_ID,
        )

        messages = asyncio.run(
            agent_loop.agent_loop(
                [
                    {
                        "role": "user",
                        "content": (
                            f"我确认把计划 ID {plan.id}「{plan.title}」移出当前计划，"
                            "请现在归档它并保留历史，不用再次询问。"
                        ),
                    }
                ],
                "student",
                db,
                STUDENT_ID,
            )
        )

        calls = _extract_tool_calls(messages)
        archive_calls = [call for call in calls if call["name"] == "archive_study_plan"]
        assert archive_calls, f"应调 archive_study_plan，实际调了: {[call['name'] for call in calls]}"
        assert archive_calls[0]["args"].get("plan_id") == plan.id
        assert archive_calls[0]["args"].get("confirmed") is True
        assert study_plan.get_study_plan(db, plan.id).status == "archived"

    def test_agent_presents_choice_question_for_finite_options(self, db):
        """学生在有限选项里做决定时，应调 present_choice_question 给可点按钮，而非把选项写进正文。

        先补全画像避免冷启动画像问题干扰，专注验证通用选择题工具被正确触发。
        """
        from app.features.p2 import profile
        from app.features.p2.schemas import ProfileOnboardingRequest

        profile.save_profile_onboarding(
            db,
            student_id=STUDENT_ID,
            req=ProfileOnboardingRequest(grade="八年级", semester="上册", weak_subjects=["英语"]),
            actor_role="student",
        )

        messages = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "今天我想学习，先做数学还是先做英语？你给我选项让我点一下。"}],
                "student",
                db,
                STUDENT_ID,
            )
        )

        calls = _extract_tool_calls(messages)
        choice_calls = [call for call in calls if call["name"] == "present_choice_question"]
        assert choice_calls, f"应调 present_choice_question，实际调了: {[call['name'] for call in calls]}"
        args = choice_calls[0]["args"]
        assert args.get("question")
        options = args.get("options") or []
        assert len(options) >= 2, f"应至少 2 个选项，实际: {options}"
        assert all("label" in o and "value" in o for o in options)
