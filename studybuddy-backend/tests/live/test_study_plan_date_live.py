"""M2：真实 MiMo 跨天旧上下文 live 测试（P3 B4 修复验收）。

背景：跨天长期会话中 AI 会把昨天的日期写进"今天"的计划草案（B4 复现：
旧助手回复明确说过"今日计划（昨天日期）"，当前轮用户要"今天"的计划）。
M0/M1 修复：草案日期硬校正（date_guard.normalize_planned_date）+ 当前轮日期锚点
（current_round_date_anchor，只进 LLM 输入不落库）+ 最终文本窄范围校正
（correct_today_label_in_text）。本文件用真实 MiMo 验证修复在真实模型行为下生效
（AGENTS.md：mock 通过不算完成，必须真实 live 测试）。

场景构造：
- 测试事务里建独立临时学生 + 会话，历史中旧助手明确说过"今日计划（昨天）"
- 当前轮发"今天帮我定一个{subject}学习计划，只给草案不要创建"
- 走完整 agent turn（run_agent_turn：历史加载 -> 日期锚点 -> agent_loop -> 最终文本校正 -> 持久化）

断言（M2 阈值）：
① 最终正文不得把旧日期称为"今天/今日"（旧日期直接被称为今天命中数 = 0）
② 若调了 draft_study_plan：工具结果 planned_date 与标题今日标签 = 服务端今天；DB 草案 draft_data 一致
③ 日期锚点进入 LLM 输入（真实请求消息里最新 user 消息以锚点开头，含"今天是 <服务端今天>"）

不确认草案、不创建正式计划；数据全部在测试事务里，结束自动回滚，不污染本地开发库。
LLM/网络失败时 run_agent_turn 返回降级文案或空正文，测试断言明确失败，不把网络错误当通过。
"""

import asyncio
import json
import re
from datetime import date, timedelta

import pytest

from app.core import ai_service
from app.features.agent import date_guard
from app.features.chat import agent as chat_agent
from app.models import StudyPlanDraft
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User

# "今天/今日……（YYYY-MM-DD）"：同一句（不含句末标点/换行）内明确把某日称为今天的日期标签
_STALE_TODAY_LABEL = re.compile(r"(?:今天|今日)[^。！？!?\n；;]*[（(](\d{4}-\d{2}-\d{2})[）)]")
_TODAY_IS_DATE = re.compile(r"今天是\s*(\d{4}-\d{2}-\d{2})")


def _draft_tool_results(events: list[tuple[str, dict]]) -> list[dict]:
    """从 emit 事件中取出 draft_study_plan 的工具结果（handler 校正后的权威输出）。"""
    return [dict(data) for evt_type, data in events if evt_type == "tool_result" and data.get("name") == "draft_study_plan"]


@pytest.mark.live
@pytest.mark.parametrize(
    ("subject", "focus", "minutes"),
    [
        ("数学", "函数计算和基础巩固", 60),
        ("英语", "一般过去时语法和单词", 50),
        ("生物", "细胞结构和光合作用", 45),
    ],
    ids=["math", "english", "biology"],
)
def test_cross_day_old_context_today_plan_draft_uses_server_date(db, monkeypatch, subject, focus, minutes):
    today = date_guard.local_today()
    old_date = today - timedelta(days=1)
    old_iso = old_date.isoformat()

    # 独立临时学生：避免认领开发库已有主会话（primary_student_id 认领逻辑），
    # 数据都在测试事务里，结束整体回滚，不污染开发库。
    student = User(username=f"live_m2_{subject}", password_hash="not-used", role="student", display_name="测试学生")
    db.add(student)
    db.flush()
    session = ChatSession(
        user_id=student.id,
        student_id=student.id,
        role_at_create="student",
        title="学习对话",
        session_type="main",
    )
    db.add(session)
    db.flush()

    # 跨天旧上下文：旧助手回复明确把昨天称为"今天"（复现 B4 的上下文冲突来源）
    db.add(ChatMessage(session_id=session.id, role="user", content=f"帮我定一个{subject}学习计划，我这两天想集中复习。"))
    db.add(ChatMessage(session_id=session.id, role="assistant", content=f"好的，今日计划（{old_iso}）：{subject}基础巩固 + 错题复盘。"))
    db.flush()

    # 只观测不 mock：包一层真实 LLM 调用，捕获发给 MiMo 的 messages（验证锚点进入输入）
    captured_llm_messages: list[list[dict]] = []
    real_call_llm_stream = ai_service.call_llm_stream

    async def spy_call_llm_stream(messages, tools=None, system=None, max_tokens=4096):
        captured_llm_messages.append(list(messages))
        return await real_call_llm_stream(messages=messages, tools=tools, system=system, max_tokens=max_tokens)

    monkeypatch.setattr(ai_service, "call_llm_stream", spy_call_llm_stream)

    events: list[tuple[str, dict]] = []

    async def capture(evt_type: str, data: dict) -> None:
        events.append((evt_type, data))

    final_text = asyncio.run(
        chat_agent.run_agent_turn(
            db,
            session,
            student,
            f"今天帮我定一个{subject}学习计划，重点{focus}，今天能学 {minutes} 分钟，只给草案不要创建",
            emit=capture,
            auto_title_session=False,
        )
    )

    # 网络/LLM 失败时 run_agent_turn 返回降级文案或空正文：明确失败，不把网络错误当通过
    assert final_text, f"{subject}: agent turn 没有产出正文（LLM 请求失败或空回复）"
    assert "网络不太好" not in final_text, f"{subject}: 命中 LLM 降级文案，网络错误不能算通过: {final_text}"

    # ③ 日期锚点必须进入 LLM 输入（本轮时间事实 = 服务端今天）
    assert captured_llm_messages, f"{subject}: 应至少发起一次真实 LLM 请求"
    anchor = date_guard.current_round_date_anchor()
    latest_user = next((m for m in reversed(captured_llm_messages[0]) if m.get("role") == "user"), None)
    assert latest_user is not None, f"{subject}: LLM 输入中没有 user 消息"
    user_content = str(latest_user.get("content") or "")
    assert user_content.startswith(anchor), f"{subject}: LLM 输入应含当前轮日期锚点，实际开头: {user_content[:60]}..."
    assert f"今天是 {today.isoformat()}" in user_content, f"{subject}: 锚点应含服务端今天日期"

    # ① 最终正文不得把旧日期称为"今天/今日"（旧日期直接被称为今天命中数 = 0）
    assert _TODAY_IS_DATE.search(final_text) is None or _TODAY_IS_DATE.search(final_text).group(1) == today.isoformat(), (
        f"{subject}: 正文出现「今天是 <非今天>」: {final_text}"
    )
    stale_hits = [m.group(0) for m in _STALE_TODAY_LABEL.finditer(final_text) if m.group(1) == old_iso]
    assert not stale_hits, f"{subject}: 最终正文把旧日期({old_iso})称为今天: {stale_hits} | 正文: {final_text}"

    # ② draft_study_plan（若调用）：工具结果与 DB 草案的日期/标题今日标签必须 = 服务端今天
    draft_results = _draft_tool_results(events)
    if draft_results:
        output = json.loads(draft_results[0].get("output") or "{}")
        assert output.get("planned_date") == today.isoformat(), (
            f"{subject}: draft 工具 planned_date 应为今天({today.isoformat()})，实际: {output.get('planned_date')}"
        )
        title = str(output.get("title") or "")
        for label in ("今日", "今天"):
            for match in re.finditer(rf"{label}[^（(]*[（(](\d{{4}}-\d{{2}}-\d{{2}})[）)]", title):
                assert match.group(1) == today.isoformat(), (
                    f"{subject}: 标题「{title}」今日标签日期 {match.group(1)} != 今天 {today.isoformat()}"
                )
        drafts = db.query(StudyPlanDraft).filter(StudyPlanDraft.student_id == student.id).all()
        assert drafts, f"{subject}: draft_study_plan 应落库草案"
        for draft in drafts:
            assert draft.draft_data.get("planned_date") == today.isoformat(), (
                f"{subject}: DB 草案 planned_date 应为今天({today.isoformat()})，实际: {draft.draft_data.get('planned_date')}"
            )
    # 模型未调 draft 工具（纯文本草案旁路，即 B4 截图路径）：正文断言①已兜底，通过不伪造工具结果
