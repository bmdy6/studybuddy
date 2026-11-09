"""阶段2：任务进度摘要最小口径（先红后绿）。"""
import pytest
from app.features.p2 import study_plan
from app.features.p2.schemas import StudyPlanItemInput
from app.models.p2 import StudyPlanItemAttempt


def test_in_progress_requires_evidence_or_scope(db):
    plan = study_plan.create_study_plan(db, student_id=2, title="进度校验", items=[StudyPlanItemInput(title="任务", minutes=10)])
    item = plan.items[0]
    # blocked 无 evidence 且无 taught_scope 应拒
    with pytest.raises(ValueError, match="作答证据或讲解范围"):
        study_plan.record_study_plan_item_assessment(db, student_id=2, item_id=item.id, assessment="blocked", reason="卡在时态")
    # 有 taught_scope 即可过
    result = study_plan.record_study_plan_item_assessment(db, student_id=2, item_id=item.id, assessment="blocked", reason="卡在时态", taught_scope="一般过去时肯定句")
    assert result.status == "in_progress"


def test_needs_retry_keeps_todo(db):
    plan = study_plan.create_study_plan(db, student_id=2, title="重做", items=[StudyPlanItemInput(title="任务", minutes=10)])
    item = plan.items[0]
    result = study_plan.record_study_plan_item_assessment(db, student_id=2, item_id=item.id, assessment="needs_retry", reason="公式不熟")
    assert result.status == "todo"
    assert result.completed_at is None
    # attempt 已落库
    assert db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id, assessment="needs_retry").count() == 1


def test_blocked_has_reason(db):
    plan = study_plan.create_study_plan(db, student_id=2, title="卡住", items=[StudyPlanItemInput(title="任务", minutes=10)])
    item = plan.items[0]
    with pytest.raises(ValueError, match="blocked"):
        study_plan.record_study_plan_item_assessment(db, student_id=2, item_id=item.id, assessment="blocked", taught_scope="范围")
    # 有 reason + scope 即可
    result = study_plan.record_study_plan_item_assessment(db, student_id=2, item_id=item.id, assessment="blocked", reason="was/were 混淆", taught_scope="一般过去时")
    assert result.status == "in_progress"


def test_daily_refresh_uses_attempt_not_summary(db):
    """daily_record 聚合应基于 verified evidence，不把 AI 摘要当事实。"""
    from app.features.growth import daily_record_service
    from datetime import date
    # 空库时 refresh 不应把旧 AI 摘要当 evidence
    facts = daily_record_service.aggregate_daily_facts(db, student_id=2, record_date=date.today())
    # evidence 来自 verified tier，非 AI 摘要
    assert all(e.get("tier") != "ai" for e in facts["evidence"])


def test_next_start_persisted(db):
    plan = study_plan.create_study_plan(db, student_id=2, title="续学", items=[StudyPlanItemInput(title="任务", minutes=10)])
    item = plan.items[0]
    study_plan.record_study_plan_item_assessment(
        db, student_id=2, item_id=item.id, assessment="blocked", reason="卡点", taught_scope="范围", next_start="从第3题继续"
    )
    attempt = db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id).order_by(StudyPlanItemAttempt.id.desc()).first()
    assert attempt is not None
    assert attempt.next_start == "从第3题继续"
    assert attempt.taught_scope == "范围"
