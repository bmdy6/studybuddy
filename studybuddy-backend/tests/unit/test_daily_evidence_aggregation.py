from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.models.p2 import LearningFeedback, StudyPlan, StudyPlanItem
from app.features.growth.daily_record_service import aggregate_daily_facts, evidence_hash


def test_daily_facts_dedupes_and_excludes_plan_estimates(db):
    plan = StudyPlan(student_id=2, title="今日计划", status="active", planned_date=date(2026, 7, 12))
    db.add(plan)
    db.flush()
    item = StudyPlanItem(plan_id=plan.id, title="背单词", status="done", completed_at=datetime(2026, 7, 12, 9))
    db.add(item)
    db.add(LearningFeedback(student_id=2, feedback_type="duration", content="完成学习计划任务「背单词」，预计用时 20 分钟。", created_at=datetime(2026, 7, 12, 9)))
    db.add(LearningFeedback(student_id=2, feedback_type="duration", content="今天学习 35 分钟", created_at=datetime(2026, 7, 12, 10)))
    db.commit()
    facts = aggregate_daily_facts(db, 2, date(2026, 7, 12), now=datetime(2026, 7, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert len([x for x in facts["evidence"] if x["source_type"] == "study_plan_item"]) == 1
    assert facts["self_reported_duration_minutes"] == 35
    assert facts["evidence"] == sorted(facts["evidence"], key=lambda x: (x["source_type"], x["source_id"], x["version"]))


def test_evidence_hash_changes_for_pending_duration_and_tier():
    base = {"evidence": [{"source_type": "note", "source_id": 1, "version": 1, "tier": "verified"}], "pending_tasks": [], "self_reported_duration_minutes": 0, "has_verified_evidence": True, "period_end": "a"}
    assert evidence_hash(base) == evidence_hash({**base, "period_end": "b"})
    assert evidence_hash(base) != evidence_hash({**base, "pending_tasks": [{"item_title": "x"}]})
    assert evidence_hash(base) != evidence_hash({**base, "self_reported_duration_minutes": 1})
    assert evidence_hash(base) != evidence_hash({**base, "evidence": [{**base["evidence"][0], "tier": "self_reported"}], "has_verified_evidence": False})
