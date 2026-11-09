"""每日对齐 service 的幂等和并发锁行为。"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from uuid import uuid4

import pytest

from app.database import SessionLocal, engine
from app.models.user import User
from app.features.growth import checkin_service as daily_checkin_service
from app.features.growth import daily_record_service as daily_learning_record_service
from app.utils.security import hash_password


@pytest.mark.skipif(engine.dialect.name == "sqlite", reason="SQLite 不提供 MySQL 行锁语义")
def test_concurrent_submissions_first_choice_wins_and_plan_is_untouched():
    target_date = date(2099, 1, 2)
    setup = SessionLocal()
    username = f"checkin-lock-{uuid4().hex}"
    try:
        user = User(username=username, password_hash=hash_password("x"), role="student", display_name="并发测试")
        setup.add(user)
        setup.commit()
        student_id = user.id
        daily_learning_record_service.get_or_create(setup, student_id, target_date)
    finally:
        setup.close()

    def submit(choice: str):
        session = SessionLocal()
        try:
            return daily_checkin_service.submit(session, student_id, choice, target_date=target_date)
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, choice) for choice in ("follow_plan", "reduce")]
            successes = []
            errors = []
            for future in as_completed(futures):
                try:
                    successes.append(future.result())
                except daily_checkin_service.CheckinAlreadyCompletedError as exc:
                    errors.append(exc)
        assert len(successes) == 1
        assert len(errors) == 1
        verify = SessionLocal()
        try:
            record = daily_checkin_service.daily_learning_record_service.get_by_date(verify, student_id, target_date)
            assert record is not None
            assert record.checkin_response == successes[0].checkin_response
        finally:
            verify.close()
    finally:
        cleanup = SessionLocal()
        try:
            record = daily_checkin_service.daily_learning_record_service.get_by_date(cleanup, student_id, target_date)
            if record:
                cleanup.delete(record)
            user = cleanup.get(User, student_id)
            if user:
                cleanup.delete(user)
            cleanup.commit()
        finally:
            cleanup.close()
