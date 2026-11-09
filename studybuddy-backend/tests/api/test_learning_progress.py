from datetime import date

from app.models.daily_learning_record import DailyLearningRecord


def _token(client, username: str, password: str) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _add_record(db, student_id: int = 2):
    db.add(
        DailyLearningRecord(
            student_id=student_id,
            record_date=date(2026, 7, 18),
            facts_snapshot={"evidence": [{"source_type": "note", "source_id": 1, "version": 1, "tier": "verified"}], "pending_tasks": []},
            generation_status="ready",
        )
    )
    db.commit()


def test_student_reads_own_progress(client, db):
    _add_record(db)
    token = _token(client, "student", "student123")
    response = client.get("/api/learning-progress?as_of=2026-07-18", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    assert response.json()["student_id"] == 2
    assert response.json()["streak_days"] == 1


def test_parent_reads_bound_student(client, db):
    _add_record(db)
    token = _token(client, "teacher", "teacher123")
    response = client.get("/api/learning-progress?student_id=2&as_of=2026-07-18", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_student_cannot_read_other_student(client):
    token = _token(client, "student", "student123")
    response = client.get("/api/learning-progress?student_id=999&as_of=2026-07-18", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_parent_cannot_read_unbound_student(client):
    token = _token(client, "teacher", "teacher123")
    response = client.get("/api/learning-progress?student_id=999&as_of=2026-07-18", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
