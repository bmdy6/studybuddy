"""每日对齐状态与快捷选择 API。"""

from datetime import date, timedelta

from app.models.daily_learning_record import DailyLearningRecord
from app.models.p2 import StudyPlan, StudyPlanItem
from app.features.growth import daily_record_service as daily_learning_record_service


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token(client, username: str, password: str) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _plan(db, student_id: int, planned_date: date, *, todo: int = 1, done: int = 0) -> StudyPlan:
    plan = StudyPlan(student_id=student_id, title=f"计划-{planned_date}", status="active", planned_date=planned_date)
    db.add(plan)
    db.flush()
    for index in range(todo + done):
        db.add(StudyPlanItem(plan_id=plan.id, title=f"任务-{index}", minutes=15, status="done" if index < done else "todo", sort_order=index))
    db.commit()
    return plan


def _record(db, student_id: int, record_date: date, pending: list[dict] | None = None) -> DailyLearningRecord:
    record = daily_learning_record_service.get_or_create(db, student_id, record_date)
    record.facts_snapshot = {**record.facts_snapshot, "pending_tasks": pending or [], "evidence": []}
    db.commit()
    return record


def test_status_reports_no_plan_without_creating_plan(client):
    token = _token(client, "student", "student123")
    response = client.get("/api/daily-checkin?as_of=2026-07-18", headers=_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "no_plan"
    assert body["task_count"] == 0
    assert body["estimated_minutes"] == 0
    assert len(body["choices"]) >= 2


def test_status_distinguishes_yesterday_incomplete_and_consecutive(client, db):
    today = date(2026, 7, 18)
    _plan(db, 2, today, todo=2)
    _record(db, 2, today - timedelta(days=1), [{"plan_title": "昨天", "item_title": "数学"}])
    token = _token(client, "student", "student123")
    response = client.get("/api/daily-checkin?as_of=2026-07-18", headers=_headers(token))
    assert response.json()["status"] == "yesterday_incomplete"

    _record(db, 2, today - timedelta(days=2), [{"plan_title": "前天", "item_title": "英语"}])
    response = client.get("/api/daily-checkin?as_of=2026-07-18", headers=_headers(token))
    assert response.json()["status"] == "consecutive_incomplete"


def test_unrefreshed_yesterday_record_still_uses_plan_todos(client, db):
    today = date(2026, 7, 18)
    _plan(db, 2, today, todo=1)
    _plan(db, 2, today - timedelta(days=1), todo=1)
    # get_or_create creates the empty skeleton; PR-03 refresh has not produced a hash yet.
    daily_learning_record_service.get_or_create(db, 2, today - timedelta(days=1))
    token = _token(client, "student", "student123")
    response = client.get("/api/daily-checkin?as_of=2026-07-18", headers=_headers(token))
    assert response.json()["status"] == "yesterday_incomplete"


def test_status_reports_yesterday_completed(client, db):
    today = date(2026, 7, 18)
    _plan(db, 2, today, todo=1)
    _record(db, 2, today - timedelta(days=1))
    token = _token(client, "student", "student123")
    response = client.get("/api/daily-checkin?as_of=2026-07-18", headers=_headers(token))
    assert response.json()["status"] == "yesterday_completed"


def test_submit_checkin_is_idempotent_and_does_not_change_plan(client, db):
    today = date(2026, 7, 18)
    plan = _plan(db, 2, today, todo=2)
    token = _token(client, "student", "student123")
    first = client.post("/api/daily-checkin", json={"choice": "follow_plan"}, headers=_headers(token))
    assert first.status_code == 200, first.text
    assert first.json()["checkin_status"] == "done"
    assert first.json()["checkin_response"] == "follow_plan"
    second = client.post("/api/daily-checkin", json={"choice": "follow_plan"}, headers=_headers(token))
    assert second.status_code == 200
    different = client.post("/api/daily-checkin", json={"choice": "reduce"}, headers=_headers(token))
    assert different.status_code == 409
    assert db.get(StudyPlan, plan.id).status == "active"
    assert len(db.query(StudyPlanItem).filter(StudyPlanItem.plan_id == plan.id, StudyPlanItem.status == "todo").all()) == 2


def test_checkin_permission_uses_bound_student(client):
    teacher_token = _token(client, "teacher", "teacher123")
    response = client.get("/api/daily-checkin?student_id=9999&as_of=2026-07-18", headers=_headers(teacher_token))
    assert response.status_code == 403


def test_parent_cannot_submit_checkin(client):
    teacher_token = _token(client, "teacher", "teacher123")
    response = client.post(
        "/api/daily-checkin?student_id=2",
        json={"choice": "follow_plan"},
        headers=_headers(teacher_token),
    )
    assert response.status_code == 403
