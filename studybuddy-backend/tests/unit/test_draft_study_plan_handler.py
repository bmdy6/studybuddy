"""draft_study_plan handler 测试：调工具存草案返回 draft_id。"""

import asyncio
from datetime import date

from app.features.agent.handlers.learning import _handle_draft_study_plan
from app.features.agent import study_plan_flow
from app.models import StudyPlan, StudyPlanDraft


TODAY = date(2026, 8, 3)


def _patch_today(monkeypatch, today: date) -> None:
    """固定服务端时钟：date_guard.local_today 由 handler 按模块属性调用。"""
    monkeypatch.setattr("app.features.agent.date_guard.local_today", lambda: today)


def test_handle_draft_study_plan_returns_draft_id(db):
    args = {
        "student_id": 2,
        "title": "数学复习",
        "items": [{"title": "复习概念", "minutes": 20}],
        "focus": "函数",
    }
    result = asyncio.run(_handle_draft_study_plan(args, "student", db, 1))
    assert result.get("drafted") is True
    assert result.get("draft_id") is not None
    assert result.get("title") == "数学复习"
    assert result.get("item_count") == 1
    # 草案确实存了
    draft = db.get(StudyPlanDraft, result["draft_id"])
    assert draft is not None
    assert draft.status == "pending"
    assert draft.draft_data["title"] == "数学复习"
    assert draft.draft_data["focus"] == "函数"
    assert draft.created_plan_id is None


def test_handle_draft_study_plan_rejects_empty_title(db):
    result = asyncio.run(_handle_draft_study_plan(
        {"student_id": 2, "title": "", "items": [{"title": "x", "minutes": 10}]},
        "student", db, 1,
    ))
    assert result.get("error")
    assert "名称" in result["error"]


def test_handle_draft_study_plan_rejects_empty_items(db):
    result = asyncio.run(_handle_draft_study_plan(
        {"student_id": 2, "title": "有标题", "items": []},
        "student", db, 1,
    ))
    assert result.get("error")
    assert "任务" in result["error"]


def _draft_args(**overrides):
    args = {
        "student_id": 2,
        "title": "数学复习",
        "items": [{"title": "复习概念", "minutes": 20}],
    }
    args.update(overrides)
    return args


def test_draft_old_planned_date_forced_to_today_three_places_consistent(monkeypatch, db):
    """旧日期回今天：handler 返回值 / draft_data / 确认后 plan.planned_date 三处一致。"""
    _patch_today(monkeypatch, TODAY)
    result = asyncio.run(_handle_draft_study_plan(
        _draft_args(planned_date="2026-08-02"), "student", db, 1,
    ))
    assert result.get("planned_date") == "2026-08-03"
    draft = db.get(StudyPlanDraft, result["draft_id"])
    assert draft.draft_data["planned_date"] == "2026-08-03"

    # 确认后正式计划日期也必须与草案一致
    confirm = study_plan_flow.confirm_and_create(db, draft.id, draft.revision, draft.student_id, None)
    assert confirm.ok
    plan = db.get(StudyPlan, confirm.plan_id)
    assert plan.planned_date == TODAY


def test_draft_invalid_planned_date_forced_to_today(monkeypatch, db):
    _patch_today(monkeypatch, TODAY)
    result = asyncio.run(_handle_draft_study_plan(
        _draft_args(planned_date="不是日期"), "student", db, 1,
    ))
    assert result.get("planned_date") == "2026-08-03"
    draft = db.get(StudyPlanDraft, result["draft_id"])
    assert draft.draft_data["planned_date"] == "2026-08-03"


def test_draft_future_planned_date_kept(monkeypatch, db):
    _patch_today(monkeypatch, TODAY)
    result = asyncio.run(_handle_draft_study_plan(
        _draft_args(planned_date="2026-08-05"), "student", db, 1,
    ))
    assert result.get("planned_date") == "2026-08-05"
    draft = db.get(StudyPlanDraft, result["draft_id"])
    assert draft.draft_data["planned_date"] == "2026-08-05"


def test_draft_today_label_title_date_synced(monkeypatch, db):
    """B4 形态：标题末尾括号旧日期同步为权威 planned_date，三处一致。"""
    _patch_today(monkeypatch, TODAY)
    result = asyncio.run(_handle_draft_study_plan(
        _draft_args(title="今日生物·细胞呼吸补漏（2026-08-02）", planned_date="2026-08-02"),
        "student", db, 1,
    ))
    assert result.get("title") == "今日生物·细胞呼吸补漏（2026-08-03）"
    assert result.get("planned_date") == "2026-08-03"
    draft = db.get(StudyPlanDraft, result["draft_id"])
    assert draft.draft_data["title"] == "今日生物·细胞呼吸补漏（2026-08-03）"
    assert draft.draft_data["planned_date"] == "2026-08-03"

    confirm = study_plan_flow.confirm_and_create(db, draft.id, draft.revision, draft.student_id, None)
    assert confirm.ok
    plan = db.get(StudyPlan, confirm.plan_id)
    assert plan.title == "今日生物·细胞呼吸补漏（2026-08-03）"
    assert plan.planned_date == TODAY


def test_draft_does_not_rewrite_history_date_in_body(monkeypatch, db):
    """description/focus/items 里的历史日期引用不得被替换。"""
    _patch_today(monkeypatch, TODAY)
    result = asyncio.run(_handle_draft_study_plan(
        _draft_args(
            title="今日复习",
            planned_date="2026-08-02",
            description="复习 2026-07-23 的错题",
            items=[{"title": "复习 2026-07-23 错题", "minutes": 20, "target": "2026-07-23 错题"}],
        ),
        "student", db, 1,
    ))
    assert result.get("planned_date") == "2026-08-03"
    draft = db.get(StudyPlanDraft, result["draft_id"])
    assert draft.draft_data["description"] == "复习 2026-07-23 的错题"
    assert draft.draft_data["items"][0]["title"] == "复习 2026-07-23 错题"
    assert draft.draft_data["items"][0]["target"] == "2026-07-23 错题"
