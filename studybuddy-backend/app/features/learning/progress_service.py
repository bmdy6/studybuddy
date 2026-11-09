"""基于 PR-03 每日事实快照计算可解释的学习进度指标。"""

from datetime import date, timedelta
from typing import Any


def _facts(record: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    snapshot = record.facts_snapshot or {}
    return snapshot.get("evidence", []) or [], snapshot.get("pending_tasks", []) or []


def _dedup_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any, Any]] = set()
    result = []
    for item in evidence:
        key = (item.get("source_type"), item.get("source_id"), item.get("version"))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def build_progress_metrics(student_id: int, as_of: date, records: list[Any]) -> dict[str, Any]:
    by_date = {record.record_date: record for record in records}
    today_record = by_date.get(as_of)
    today_evidence, today_pending = _facts(today_record) if today_record else ([], [])
    today_evidence = _dedup_evidence(today_evidence)
    completed = [item for item in today_evidence if item.get("source_type") == "study_plan_item"]
    total = len({(item.get("source_id"), item.get("version")) for item in completed}) + len(today_pending)
    completed_count = len({(item.get("source_id"), item.get("version")) for item in completed})
    today_status = "no_plan" if total == 0 else ("completed" if completed_count == total else "planned")

    week_start = as_of - timedelta(days=as_of.weekday())
    week = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        record = by_date.get(day)
        if day > as_of:
            status = "future"
            count = 0
        else:
            evidence, pending = _facts(record) if record else ([], [])
            evidence = _dedup_evidence(evidence)
            count = len({(x.get("source_type"), x.get("source_id"), x.get("version")) for x in evidence if x.get("source_type") == "study_plan_item"})
            status = "active" if evidence else ("planned" if pending else "no_plan")
        week.append({"record_date": day, "status": status, "completed_count": count})

    recent_start = as_of - timedelta(days=6)
    recent_completed = set()
    for day, record in by_date.items():
        if recent_start <= day <= as_of:
            evidence, _ = _facts(record)
            for item in _dedup_evidence(evidence):
                if item.get("source_type") == "study_plan_item":
                    recent_completed.add((day, item.get("source_id"), item.get("version")))

    streak = 0
    cursor = as_of
    while True:
        record = by_date.get(cursor)
        evidence, _ = _facts(record) if record else ([], [])
        if not _dedup_evidence(evidence):
            break
        streak += 1
        cursor -= timedelta(days=1)

    return {
        "student_id": student_id,
        "as_of": as_of,
        "today": {"completed_count": completed_count, "total_count": total, "completion_rate": completed_count / total if total else None, "status": today_status},
        "streak_days": streak,
        "week": week,
        "recent_7_days_completed_tasks": len(recent_completed),
    }
