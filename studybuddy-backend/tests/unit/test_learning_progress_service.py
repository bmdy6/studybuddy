from datetime import date
from types import SimpleNamespace

from app.features.learning.progress_service import build_progress_metrics


def _record(day: date, evidence=None, pending=None):
    return SimpleNamespace(
        id=day.day,
        record_date=day,
        facts_snapshot={"evidence": evidence or [], "pending_tasks": pending or []},
    )


def _plan_item(source_id: int):
    return {"source_type": "study_plan_item", "source_id": source_id, "version": 1, "tier": "self_reported"}


def test_no_plan_has_null_completion_rate():
    result = build_progress_metrics(2, date(2026, 7, 18), [])

    assert result["today"] == {"completed_count": 0, "total_count": 0, "completion_rate": None, "status": "no_plan"}


def test_partial_completion_and_duplicate_evidence_are_counted_once():
    today = date(2026, 7, 18)
    duplicate = _plan_item(10)
    result = build_progress_metrics(
        2,
        today,
        [_record(today, [duplicate, duplicate], [{"item_title": "待办"}])],
    )

    assert result["today"] == {"completed_count": 1, "total_count": 2, "completion_rate": 0.5, "status": "planned"}
    assert result["recent_7_days_completed_tasks"] == 1


def test_full_completion_and_streak_stop_at_gap():
    records = [
        _record(date(2026, 7, 15), [_plan_item(1)]),
        _record(date(2026, 7, 17), [{"source_type": "note", "source_id": 2, "version": 1, "tier": "verified"}]),
        _record(date(2026, 7, 18), [_plan_item(3)]),
    ]

    result = build_progress_metrics(2, date(2026, 7, 18), records)

    assert result["today"]["completion_rate"] == 1.0
    assert result["today"]["status"] == "completed"
    assert result["streak_days"] == 2


def test_week_statuses_do_not_mix_previous_week_or_future_days():
    records = [
        _record(date(2026, 7, 12), [_plan_item(1)]),
        _record(date(2026, 7, 13), pending=[{"item_title": "周一任务"}]),
        _record(date(2026, 7, 14), [{"source_type": "material", "source_id": 2, "version": 1, "tier": "machine_extracted"}]),
    ]

    result = build_progress_metrics(2, date(2026, 7, 15), records)

    assert [day["status"] for day in result["week"]] == ["planned", "active", "no_plan", "future", "future", "future", "future"]
