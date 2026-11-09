"""study_plan_flow 草案状态机测试：幂等、原子、用 draft_data、跨学生拒绝、过期、superseded。"""

from datetime import date, datetime, timedelta, timezone

from app.models import StudyPlan, StudyPlanDraft
from app.features.agent import study_plan_flow as flow


TODAY = date(2026, 8, 3)


def _patch_today(monkeypatch, today: date) -> None:
    """固定服务端时钟：confirm_and_create 按模块属性调用 date_guard.local_today。"""
    monkeypatch.setattr("app.features.agent.date_guard.local_today", lambda: today)


def _make_draft(
    db,
    student_id=2,
    status="pending",
    revision=1,
    draft_data=None,
    expires_at=None,
):
    d = StudyPlanDraft(
        student_id=student_id,
        chat_session_id=None,
        draft_data=draft_data or {"title": "数学复习", "items": [{"title": "复习概念", "minutes": 20}]},
        revision=revision,
        status=status,
        expires_at=expires_at,
    )
    db.add(d)
    db.flush()
    return d


def _naive_utc(dt):
    return dt.replace(tzinfo=None, microsecond=0) if dt.tzinfo else dt


def test_confirm_creates_plan_with_draft_data(db):
    d = _make_draft(db)
    r = flow.confirm_and_create(db, d.id, 1, d.student_id, None)
    assert r.ok
    plan = db.get(StudyPlan, r.plan_id)
    assert plan.title == "数学复习"
    assert plan.student_id == 2


def test_confirm_returns_same_plan_id_on_duplicate(db):
    d = _make_draft(db)
    r1 = flow.confirm_and_create(db, d.id, 1, d.student_id, None)
    r2 = flow.confirm_and_create(db, d.id, 1, d.student_id, None)
    assert r1.ok and r2.ok
    assert r1.plan_id == r2.plan_id  # 幂等


def test_old_revision_rejected(db):
    d = _make_draft(db, revision=1)
    r = flow.confirm_and_create(db, d.id, 2, d.student_id, None)
    assert not r.ok
    assert "revision" in r.error or "修改" in r.error


def test_uses_draft_data_title_not_args(db):
    d = _make_draft(db, draft_data={"title": "草案标题", "items": [{"title": "任务1", "minutes": 15}], "focus": "函数"})
    r = flow.confirm_and_create(db, d.id, 1, d.student_id, None)
    plan = db.get(StudyPlan, r.plan_id)
    assert plan.title == "草案标题"
    assert plan.focus == "函数"


def test_cross_student_rejected(db):
    d = _make_draft(db, student_id=2)
    r = flow.confirm_and_create(db, d.id, 1, 999, None)  # 别的学生
    assert not r.ok
    assert r.plan_id is None


def test_expired_draft_rejected(db):
    past = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(minutes=1)
    d = _make_draft(db, expires_at=past)
    r = flow.confirm_and_create(db, d.id, 1, d.student_id, None)
    assert not r.ok
    assert "过期" in r.error


def test_superseded_draft_rejected(db):
    d = _make_draft(db, status="superseded")
    r = flow.confirm_and_create(db, d.id, 1, d.student_id, None)
    assert not r.ok


def test_create_draft_supersedes_old_pending(db):
    d1 = _make_draft(db)
    d2 = flow.create_draft(db, d1.student_id, None, {"title": "新草案", "items": [{"title": "x", "minutes": 10}]}, None)
    db.refresh(d1)
    assert d1.status == "superseded"
    assert d2.status == "pending"


def test_get_draft_isolated_by_student(db):
    d = _make_draft(db, student_id=2)
    assert flow.get_draft(db, d.id, 2) is not None
    assert flow.get_draft(db, d.id, 999) is None  # 跨学生查不到


def test_confirm_re_corrects_planned_date_across_midnight(monkeypatch, db):
    """跨午夜确认：草案生成时还是昨天，确认时已过午夜，日期二次校正到今天。"""
    _patch_today(monkeypatch, TODAY)
    d = _make_draft(db, draft_data={
        "title": "今日数学（2026-08-02）",
        "items": [{"title": "复习概念", "minutes": 20}],
        "planned_date": "2026-08-02",
    })
    r = flow.confirm_and_create(db, d.id, 1, d.student_id, None)
    assert r.ok
    plan = db.get(StudyPlan, r.plan_id)
    # 正式计划日期与标题日期都按服务端今天校正
    assert plan.planned_date == TODAY
    assert plan.title == "今日数学（2026-08-03）"
    # 草案数据同步校正（随确认事务一起提交），卡片与正式计划一致
    db.refresh(d)
    assert d.draft_data["planned_date"] == "2026-08-03"
    assert d.draft_data["title"] == "今日数学（2026-08-03）"


def test_confirm_future_planned_date_kept(monkeypatch, db):
    """确认时未来日期仍保留，不被拉回今天。"""
    _patch_today(monkeypatch, TODAY)
    d = _make_draft(db, draft_data={
        "title": "周末复习",
        "items": [{"title": "复习概念", "minutes": 20}],
        "planned_date": "2026-08-08",
    })
    r = flow.confirm_and_create(db, d.id, 1, d.student_id, None)
    assert r.ok
    plan = db.get(StudyPlan, r.plan_id)
    assert plan.planned_date == date(2026, 8, 8)
