from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.features.p2 import reminder_service


def _teacher_token(client: TestClient) -> str:
    return client.post("/auth/login", json={"username": "teacher", "password": "teacher123"}).json()["access_token"]


def _student_token(client: TestClient) -> str:
    return client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]


def test_dispatch_study_plan_reminders_creates_notifications_for_student_and_teacher(client: TestClient):
    teacher_token = _teacher_token(client)
    student_token = _student_token(client)
    created = client.post(
        "/api/students/2/study-plans",
        json={
            "title": "今日提醒计划",
            "planned_date": date.today().isoformat(),
            "items": [{"title": "先背单词", "minutes": 10}],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert created.status_code == 200, created.text
    plan_id = created.json()["id"]

    dispatched = client.post(
        "/api/notifications/study-plan-reminders/dispatch",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )

    assert dispatched.status_code == 200, dispatched.text
    data = dispatched.json()
    matching = [item for item in data["notifications"] if item["source_id"] == plan_id]
    assert len(matching) == 2
    assert data["skipped_count"] >= 0
    assert {item["recipient_id"] for item in matching} == {1, 2}
    assert all("今天计划「今日提醒计划」" in item["content"] for item in matching)

    teacher_notifications = client.get("/api/notifications", headers={"Authorization": f"Bearer {teacher_token}"})
    student_notifications = client.get("/api/notifications", headers={"Authorization": f"Bearer {student_token}"})

    assert teacher_notifications.status_code == 200
    assert teacher_notifications.json()["unread_count"] >= 1
    assert any("今日提醒计划" in item["content"] for item in teacher_notifications.json()["items"])
    assert student_notifications.status_code == 200
    assert student_notifications.json()["unread_count"] >= 1
    assert any("今日提醒计划" in item["content"] for item in student_notifications.json()["items"])


def test_dispatch_study_plan_reminders_is_deduped_per_day(client: TestClient):
    teacher_token = _teacher_token(client)
    created = client.post(
        "/api/students/2/study-plans",
        json={
            "title": "去重提醒计划",
            "planned_date": date.today().isoformat(),
            "items": [{"title": "做一道题", "minutes": 10}],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert created.status_code == 200, created.text

    first = client.post("/api/notifications/study-plan-reminders/dispatch", headers={"Authorization": f"Bearer {teacher_token}"})
    second = client.post("/api/notifications/study-plan-reminders/dispatch", headers={"Authorization": f"Bearer {teacher_token}"})

    assert first.status_code == 200
    assert first.json()["created_count"] >= 2
    assert second.status_code == 200
    assert second.json()["created_count"] == 0
    assert second.json()["skipped_count"] >= 2


def test_scheduled_dispatch_reuses_same_dedupe_logic(client: TestClient, db: Session):
    teacher_token = _teacher_token(client)
    created = client.post(
        "/api/students/2/study-plans",
        json={
            "title": "定时提醒计划",
            "planned_date": date.today().isoformat(),
            "items": [{"title": "读一页课本", "minutes": 15}],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert created.status_code == 200, created.text
    plan_id = created.json()["id"]

    first = reminder_service.dispatch_all_study_plan_reminder_notifications(db, limit=50)
    second = reminder_service.dispatch_all_study_plan_reminder_notifications(db, limit=50)

    matching = [item for item in first.notifications if item.source_id == plan_id]
    assert len(matching) == 2
    assert {item.recipient_id for item in matching} == {1, 2}
    assert any("定时提醒计划" in item.content for item in matching)
    assert second.created_count == 0
    assert second.skipped_count >= 2


def test_mark_notification_read_only_by_recipient(client: TestClient):
    teacher_token = _teacher_token(client)
    student_token = _student_token(client)
    created = client.post(
        "/api/students/2/study-plans",
        json={
            "title": "已读测试计划",
            "planned_date": date.today().isoformat(),
            "items": [{"title": "完成一项", "minutes": 10}],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert created.status_code == 200, created.text
    dispatched = client.post("/api/notifications/study-plan-reminders/dispatch", headers={"Authorization": f"Bearer {teacher_token}"})
    assert dispatched.status_code == 200
    teacher_item = next(item for item in dispatched.json()["notifications"] if item["recipient_id"] == 1)

    blocked = client.patch(f"/api/notifications/{teacher_item['id']}/read", headers={"Authorization": f"Bearer {student_token}"})
    marked = client.patch(f"/api/notifications/{teacher_item['id']}/read", headers={"Authorization": f"Bearer {teacher_token}"})

    assert blocked.status_code == 404
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None
