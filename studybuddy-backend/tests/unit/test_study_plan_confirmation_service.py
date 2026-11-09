import json
from datetime import datetime, timedelta

from app.features.agent.study_plan_confirmation import validate_study_plan_confirmation


def test_unclear_intent_without_draft_is_rejected():
    result = validate_study_plan_confirmation(
        [{"role": "user", "content": "下午要学英语"}],
        now=datetime(2026, 7, 7, 15, 0, 0),
    )

    assert result.allowed is False
    assert "计划草案" in result.reason
    assert "先询问" in result.next_step


def test_recent_draft_and_user_confirmation_is_allowed():
    now = datetime(2026, 7, 7, 15, 0, 0)
    result = validate_study_plan_confirmation(
        [
            {
                "role": "assistant",
                "content": "计划草案：背单词 20 分钟，语法练习 20 分钟。是否可行？",
                "created_at": (now - timedelta(minutes=5)).isoformat(),
            },
            {"role": "user", "content": "可以，就按这个来", "created_at": now.isoformat()},
        ],
        now=now,
    )

    assert result.allowed is True
    assert result.reason == "用户已确认最近的计划草案。"


def test_choice_card_plan_draft_and_clicked_confirmation_is_allowed():
    result = validate_study_plan_confirmation(
        [
            {
                "role": "assistant",
                "content": "你选哪个？",
                "tool_calls": [
                    {
                        "id": "choice-1",
                        "type": "function",
                        "function": {
                            "name": "present_choice_question",
                            "arguments": json.dumps(
                                {
                                    "question": "计划草案：复习代数基础并做练习，时间按状态调整。你觉得这样可以吗？",
                                    "options": [
                                        {"label": "可以，按这个创建", "value": "confirm"},
                                        {"label": "想调整一下", "value": "adjust"},
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "choice-1", "content": '{"shown":true}'},
            {"role": "assistant", "content": "你选哪个？"},
            {"role": "user", "content": "confirm"},
        ],
        now=datetime(2026, 7, 7, 15, 0, 0),
    )

    assert result.allowed is True


def test_expired_draft_is_rejected():
    now = datetime(2026, 7, 7, 15, 0, 0)
    result = validate_study_plan_confirmation(
        [
            {
                "role": "assistant",
                "content": "计划草案：阅读 30 分钟。要不要按这个安排？",
                "created_at": (now - timedelta(minutes=45)).isoformat(),
            },
            {"role": "user", "content": "可以", "created_at": now.isoformat()},
        ],
        now=now,
        ttl_minutes=30,
    )

    assert result.allowed is False
    assert "已过期" in result.reason


def test_direct_create_without_recent_draft_is_rejected():
    result = validate_study_plan_confirmation(
        [{"role": "user", "content": "直接创建一个计划"}],
        now=datetime(2026, 7, 7, 15, 0, 0),
    )

    assert result.allowed is False
    assert "计划草案" in result.reason


def test_confirmation_allowed_even_with_intervening_user_message():
    """草案后插了别的 user 消息，用户最终确认仍放行。

    guard 不再要求草案与确认严格相邻（AI 措辞多变，靠 marker 找草案不可靠）。
    只要用户最新消息是确认词即放行，靠 agent_loop 校验 confirmed=true 兜底。
    """
    allowed = validate_study_plan_confirmation(
        [
            {"role": "assistant", "content": "计划草案：数学错题 20 分钟。是否可行？"},
            {"role": "user", "content": "可以"},
        ],
        now=datetime(2026, 7, 7, 15, 0, 0),
    )
    with_intervening = validate_study_plan_confirmation(
        [
            {"role": "assistant", "content": "计划草案：数学错题 20 分钟。是否可行？"},
            {"role": "user", "content": "先等等"},
            {"role": "user", "content": "可以"},
        ],
        now=datetime(2026, 7, 7, 15, 0, 0),
    )

    assert allowed.allowed is True
    assert with_intervening.allowed is True


def test_natural_draft_phrase_is_recognized_as_draft():
    """AI 用自然语言给草案（如「这样可行就确认，我再创建」）必须被识别为草案。

    回归 docs/22-bug/[P1-高][待修复]学习计划-未确认循环失败与AI事实冲突.md：
    AI 不含「计划草案/是否可行」等固定词时，_is_plan_draft 误返回 False，
    导致用户自然确认后 guard 仍以「需要先给出计划草案」误拒。
    """
    now = datetime(2026, 7, 7, 15, 0, 0)
    result = validate_study_plan_confirmation(
        [
            {
                "role": "assistant",
                "content": "今天英语 30 分钟：10 分钟一般过去时用法，20 分钟练习。这样可行就确认，我再创建。",
                "created_at": (now - timedelta(minutes=3)).isoformat(),
            },
            {"role": "user", "content": "可以，就按这个创建。", "created_at": now.isoformat()},
        ],
        now=now,
    )

    assert result.allowed is True
    assert result.reason == "用户已确认最近的计划草案。"


def test_natural_draft_with_create_intent_recognized():
    """「可行我就按这个创建」这类把确认与创建意图连说的草案也要识别。"""
    now = datetime(2026, 7, 7, 15, 0, 0)
    result = validate_study_plan_confirmation(
        [
            {
                "role": "assistant",
                "content": "数学一元二次方程 30 分钟，15 分钟讲解 + 15 分钟例题。可行我就按这个创建。",
                "created_at": (now - timedelta(minutes=2)).isoformat(),
            },
            {"role": "user", "content": "可以，就按这个创建", "created_at": now.isoformat()},
        ],
        now=now,
    )

    assert result.allowed is True


def test_natural_confirmation_after_natural_draft_is_allowed():
    """完整复现 bug 第二角度场景：已有计划另建时自然草案 + 自然确认应放行。"""
    now = datetime(2026, 7, 7, 15, 0, 0)
    result = validate_study_plan_confirmation(
        [
            {"role": "user", "content": "我想另建一个今天英语语法20分钟计划，请先给草案，确认后再创建。"},
            {"role": "assistant", "content": "时态，重点练一般过去时。"},
            {
                "role": "assistant",
                "content": "10 分钟一般过去时用法/变形 + 10 分钟练习/错因复盘。这样可行就确认，我再创建。",
                "created_at": (now - timedelta(minutes=4)).isoformat(),
            },
            {"role": "user", "content": "可以，就按这个创建。", "created_at": now.isoformat()},
        ],
        now=now,
    )

    assert result.allowed is True


def test_expired_natural_draft_is_rejected():
    """自然草案过期后用户确认也不能放行，必须重新确认当前草案。"""
    now = datetime(2026, 7, 7, 15, 0, 0)
    result = validate_study_plan_confirmation(
        [
            {
                "role": "assistant",
                "content": "英语一般过去时 20 分钟。可行我就按这个创建。",
                "created_at": (now - timedelta(minutes=45)).isoformat(),
            },
            {"role": "user", "content": "可以，就按这个创建。", "created_at": now.isoformat()},
        ],
        now=now,
        ttl_minutes=30,
    )

    assert result.allowed is False
    assert "已过期" in result.reason


def test_normal_chat_with_confirmation_allowed_without_draft():
    """普通讲解 + 用户确认词 -> 放行。

    guard 不再校验「给没给过草案」（AI 措辞多变，靠 marker 识别不可靠）。
    只校验用户确认词 + agent_loop 校验 confirmed=true。AI 在非建计划场景
    调 create_study_plan 的风险靠 system_student.md 提示词约束。
    """
    now = datetime(2026, 7, 7, 15, 0, 0)
    result = validate_study_plan_confirmation(
        [
            {
                "role": "assistant",
                "content": "我帮你讲解这道一元二次方程的错题，先说说你卡在哪一步？",
                "created_at": (now - timedelta(minutes=2)).isoformat(),
            },
            {"role": "user", "content": "可以", "created_at": now.isoformat()},
        ],
        now=now,
    )

    assert result.allowed is True


def test_direct_create_without_draft_allowed_with_confirmation():
    """没有前置草案但用户明确确认 -> 放行（多计划场景 AI 草案措辞漏识别的兜底）。

    靠 agent_loop 校验 confirmed=true + 提示词约束 AI 先给草案。
    """
    now = datetime(2026, 7, 7, 15, 0, 0)
    result = validate_study_plan_confirmation(
        [{"role": "user", "content": "可以，就按这个创建"}],
        now=now,
    )

    assert result.allowed is True
