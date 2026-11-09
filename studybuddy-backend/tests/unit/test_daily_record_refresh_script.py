import asyncio
import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.models.daily_learning_record import DailyLearningRecord


def _load_script_module():
    path = Path(__file__).parents[2] / "scripts" / "refresh_daily_learning_records.py"
    spec = importlib.util.spec_from_file_location("refresh_daily_learning_records", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refresh_service_updates_selected_students_and_finalizes_previous_day(db, monkeypatch):
    from app.models.user import User
    from app.features.growth import daily_record_service as daily_learning_record_service

    student = db.get(User, 2)
    db.add(
        DailyLearningRecord(
            student_id=student.id,
            record_date=date(2026, 7, 17),
            facts_snapshot={},
            generation_status="ready",
            evidence_hash="old",
            summary_text="old",
        )
    )
    db.commit()
    calls = []

    async def fake_refresh(db_arg, student_id, record_date, *, now=None):
        calls.append((student_id, record_date, now))
        return SimpleNamespace(id=9, record_date=record_date)

    monkeypatch.setattr(daily_learning_record_service, "refresh", fake_refresh)
    result = asyncio.run(
        daily_learning_record_service.refresh_students(
            db,
            student_ids=[student.id],
            record_date=date(2026, 7, 18),
            now=datetime(2026, 7, 18, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
    )

    assert result == {"processed": 1, "skipped": 0, "failed": 0}
    assert calls == [
        (student.id, date(2026, 7, 17), datetime(2026, 7, 18, 9, tzinfo=ZoneInfo("Asia/Shanghai"))),
        (student.id, date(2026, 7, 18), datetime(2026, 7, 18, 9, tzinfo=ZoneInfo("Asia/Shanghai"))),
    ]
    previous = db.query(DailyLearningRecord).filter_by(student_id=student.id, record_date=date(2026, 7, 17)).one()
    assert previous.finalized_at is not None


def test_refresh_script_prints_counts_without_sensitive_summary(monkeypatch, capsys):
    module = _load_script_module()
    session = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(module, "SessionLocal", lambda: session)
    monkeypatch.setattr(module, "run_refresh", lambda *args, **kwargs: {"processed": 2, "skipped": 1, "failed": 0})
    monkeypatch.setattr(sys, "argv", ["refresh_daily_learning_records.py", "--student-id", "2", "--date", "2026-07-18"])

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"processed": 2, "skipped": 1, "failed": 0}


def test_refresh_service_isolates_one_student_failure(db, monkeypatch):
    from app.models.user import User
    from app.features.growth import daily_record_service as daily_learning_record_service
    from app.utils.security import hash_password

    other = User(username="refresh_failure_student", password_hash=hash_password("x"), role="student")
    db.add(other)
    db.commit()

    async def fake_refresh(_db, student_id, _record_date, *, now=None):
        if student_id == other.id:
            raise RuntimeError("one student failed")
        return SimpleNamespace(id=1)

    monkeypatch.setattr(daily_learning_record_service, "refresh", fake_refresh)
    result = asyncio.run(
        daily_learning_record_service.refresh_students(
            db, student_ids=[2, other.id], record_date=date(2026, 7, 18)
        )
    )

    assert result == {"processed": 1, "skipped": 0, "failed": 1}
