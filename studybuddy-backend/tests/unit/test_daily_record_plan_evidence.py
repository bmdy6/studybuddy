"""P0 修复：daily record 聚合计划项最新 passed Attempt 证据。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.models.p2 import StudyPlan, StudyPlanItem, StudyPlanItemAttempt
from app.features.growth.daily_record_service import aggregate_daily_facts


def _setup_done_item(db, student_id: int, evidence_summary: str | None = None, completed_at=None) -> int:
    plan = StudyPlan(student_id=student_id, title="今日计划", status="active", planned_date=date(2026, 7, 12))
    db.add(plan)
    db.flush()
    item = StudyPlanItem(plan_id=plan.id, title="背单词", status="done", completed_at=completed_at or datetime(2026, 7, 12, 9))
    db.add(item)
    db.flush()
    if evidence_summary is not None:
        db.add(StudyPlanItemAttempt(plan_item_id=item.id, student_id=student_id, assessment="passed", evidence_summary=evidence_summary, created_at=datetime(2026, 7, 12, 9)))
    db.commit()
    return item.id


def _facts(db, student_id=2):
    return aggregate_daily_facts(db, student_id, date(2026, 7, 12), now=datetime(2026, 7, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai")))


def test_done_with_evidence_includes_evidence_summary(db):
    _setup_done_item(db, 2, evidence_summary="背出了全诗并说出主旨")
    facts = _facts(db)
    entry = next(x for x in facts["evidence"] if x["source_type"] == "study_plan_item")
    assert entry["evidence_summary"] == "背出了全诗并说出主旨"
    assert entry["tier"] == "self_reported"  # 学生自报，不冒充 verified


def test_done_without_attempt_omits_evidence(db):
    """历史 done 无 Attempt：保留记录但省略证据字段，不编造。"""
    _setup_done_item(db, 2, evidence_summary=None)
    facts = _facts(db)
    entry = next(x for x in facts["evidence"] if x["source_type"] == "study_plan_item")
    assert "evidence_summary" not in entry


def test_multiple_attempts_takes_latest(db):
    """多次 Attempt（重学/重试）取最新一条的证据。"""
    item_id = _setup_done_item(db, 2, evidence_summary="第一次回答", completed_at=datetime(2026, 7, 12, 8))
    db.add(StudyPlanItemAttempt(plan_item_id=item_id, student_id=2, assessment="passed", evidence_summary="复习后的完整回答", created_at=datetime(2026, 7, 12, 18)))
    db.commit()
    facts = _facts(db)
    entry = next(x for x in facts["evidence"] if x["source_type"] == "study_plan_item")
    assert entry["evidence_summary"] == "复习后的完整回答"


def test_blank_evidence_treated_as_missing(db):
    _setup_done_item(db, 2, evidence_summary="   \n ")
    facts = _facts(db)
    entry = next(x for x in facts["evidence"] if x["source_type"] == "study_plan_item")
    assert "evidence_summary" not in entry
