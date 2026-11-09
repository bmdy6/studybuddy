from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from app.models.daily_learning_record import DailyLearningRecord

GrowthPeriod = Literal["daily", "weekly"]


def guardian_summary_facts_from_record(record: DailyLearningRecord) -> dict[str, Any]:
    """Convert a stored daily record to the shared guardian-summary input."""
    snapshot = record.facts_snapshot or {}
    return {
        "student_id": record.student_id,
        "record_date": record.record_date.isoformat(),
        "evidence": snapshot.get("evidence") or [],
        "pending_tasks": snapshot.get("pending_tasks") or [],
        "self_reported_duration_minutes": snapshot.get("self_reported_duration_minutes") or 0,
        "has_verified_evidence": bool(snapshot.get("has_verified_evidence")),
        "ai_summary": record.summary_text if record.summary_source == "ai" else None,
    }


def guardian_summary_facts_from_records(
    records: list[DailyLearningRecord],
    *,
    period: GrowthPeriod,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    """Merge stored daily records into one guardian-summary input.

    This deliberately consumes only the persisted daily snapshots. It does not
    re-query notes, exams, plans, feedback, or materials for the push path.
    """
    evidence_by_key: dict[tuple[str, Any], dict[str, Any]] = {}
    pending_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    duration = 0
    daily_summaries: list[dict[str, str]] = []
    for record in records:
        facts = guardian_summary_facts_from_record(record)
        for item in facts["evidence"]:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("source_type") or ""), item.get("source_id"))
            if key not in evidence_by_key:
                evidence_by_key[key] = item
        for item in facts["pending_tasks"]:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("plan_title") or ""), str(item.get("item_title") or ""))
            if key[1] and key not in pending_by_key:
                pending_by_key[key] = item
        duration += int(facts["self_reported_duration_minutes"] or 0)
        if record.summary_text:
            daily_summaries.append({"record_date": facts["record_date"], "summary": record.summary_text})
    evidence = sorted(
        evidence_by_key.values(),
        key=lambda item: (str(item.get("source_type") or ""), str(item.get("source_id") or ""), int(item.get("version") or 0)),
    )
    return {
        "period": period,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "evidence": evidence,
        "pending_tasks": list(pending_by_key.values()),
        "self_reported_duration_minutes": duration,
        "has_verified_evidence": any(item.get("tier") == "verified" for item in evidence),
        "daily_summaries": daily_summaries,
    }
