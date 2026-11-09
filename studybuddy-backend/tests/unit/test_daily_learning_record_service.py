"""每日学习记录 service 单测。

覆盖 spec 12.1 中本 PR 范围：
- get_or_create 幂等：同一天多次调用返回同一条
- 日期唯一：同学生同天只有一条（依赖 UNIQUE 约束）
- 跨学生隔离：不同学生同天各一条
- 空记录骨架：facts_snapshot 符合 spec 3.2 空结构
- 创建后默认状态：generation_status=pending、evidence_hash=NULL

证据聚合、hash 计算、摘要生成不在本 PR 范围（PR-03/04）。
"""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.daily_learning_record import DailyLearningRecord
from app.features.growth import daily_record_service as daily_learning_record_service


def test_model_student_id_references_users() -> None:
    """ORM 与 SQL 迁移保持相同的学生外键约束。"""
    foreign_keys = DailyLearningRecord.__table__.c.student_id.foreign_keys
    assert {foreign_key.target_fullname for foreign_key in foreign_keys} == {"users.id"}


class TestGetOrCreate:
    """get_or_create 幂等与唯一性。"""

    def test_creates_empty_record_for_new_day(self, db):
        """新日期 -> 创建一条空记录，状态 pending。"""
        record = daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        assert record.id is not None
        assert record.student_id == 2
        assert record.record_date == date(2026, 7, 17)
        assert record.generation_status == "pending"
        assert record.evidence_hash is None
        assert record.summary_text is None
        assert record.summary_source is None

    def test_idempotent_same_day_returns_same_record(self, db):
        """同一天二次调用 -> 返回同一条，不创建新记录。"""
        first = daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        second = daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        assert first.id == second.id
        count = db.query(DailyLearningRecord).filter_by(student_id=2, record_date=date(2026, 7, 17)).count()
        assert count == 1

    def test_unique_conflict_returns_concurrent_winner(self, monkeypatch):
        """并发首次创建冲突时回滚，并返回另一请求已创建的记录。"""
        record_date = date(2026, 7, 17)
        winner = DailyLearningRecord(student_id=2, record_date=record_date, facts_snapshot={})
        lookups = iter([None, winner])
        monkeypatch.setattr(
            daily_learning_record_service,
            "get_by_date",
            lambda *_args, **_kwargs: next(lookups),
        )

        class ConcurrentSession:
            rolled_back = False

            def get(self, _model, _student_id):
                from types import SimpleNamespace

                return SimpleNamespace(role="student")

            def add(self, _record):
                pass

            def commit(self):
                raise IntegrityError("INSERT", {}, Exception("duplicate"))

            def rollback(self):
                self.rolled_back = True

            def refresh(self, _record):
                raise AssertionError("冲突方不应刷新未写入的记录")

        session = ConcurrentSession()
        result = daily_learning_record_service.get_or_create(session, student_id=2, record_date=record_date)

        assert result is winner
        assert session.rolled_back is True

    def test_rejects_non_student_owner(self, db):
        """每日学习记录只能归属于学生账号。"""
        from app.models.user import User
        from app.utils.security import hash_password

        teacher = User(username="daily_record_teacher", password_hash=hash_password("x"), role="teacher")
        db.add(teacher)
        db.commit()

        with pytest.raises(ValueError, match="学生"):
            daily_learning_record_service.get_or_create(
                db,
                student_id=teacher.id,
                record_date=date(2026, 7, 17),
            )

        assert db.query(DailyLearningRecord).filter_by(student_id=teacher.id).count() == 0

    def test_different_days_create_separate_records(self, db):
        """同学生不同天 -> 各一条。"""
        r1 = daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 16))
        r2 = daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        assert r1.id != r2.id
        assert r1.record_date != r2.record_date

    def test_different_students_same_day_isolated(self, db):
        """不同学生同一天 -> 各一条，互不干扰。"""
        from app.models.user import User
        from app.utils.security import hash_password

        other = User(username="other_student", password_hash=hash_password("x"), role="student", display_name="另一学生")
        db.add(other)
        db.flush()
        r1 = daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        r2 = daily_learning_record_service.get_or_create(db, student_id=other.id, record_date=date(2026, 7, 17))
        assert r1.id != r2.id
        assert r1.student_id == 2
        assert r2.student_id == other.id


class TestFactsSnapshotSkeleton:
    """空记录 facts_snapshot 符合 spec 3.2 骨架。"""

    def test_empty_facts_snapshot_structure(self, db):
        """新建空记录的 facts_snapshot 含 spec 3.2 必备字段且为空。"""
        record = daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        snap = record.facts_snapshot
        assert snap is not None
        assert snap["student_id"] == 2
        assert snap["record_date"] == "2026-07-17"
        assert snap["evidence"] == []
        assert snap["pending_tasks"] == []
        assert snap["has_verified_evidence"] is False
        # timezone 是审计快照，来自服务端 settings.WECHAT_TIMEZONE
        assert "timezone" in snap


class TestReadQueries:
    """只读查询。"""

    def test_get_by_date_returns_record(self, db):
        """get_by_date 命中 -> 返回记录。"""
        daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        record = daily_learning_record_service.get_by_date(db, student_id=2, record_date=date(2026, 7, 17))
        assert record is not None
        assert record.record_date == date(2026, 7, 17)

    def test_get_by_date_missing_returns_none(self, db):
        """get_by_date 未命中 -> None。"""
        record = daily_learning_record_service.get_by_date(db, student_id=2, record_date=date(2026, 7, 17))
        assert record is None

    def test_list_by_range_returns_only_in_range(self, db):
        """list_by_range 只返回范围内的记录，按日期升序。"""
        daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 15))
        daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 16))
        daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 18))
        records = daily_learning_record_service.list_by_range(
            db, student_id=2, start_date=date(2026, 7, 16), end_date=date(2026, 7, 17)
        )
        dates = [r.record_date for r in records]
        assert dates == [date(2026, 7, 16), date(2026, 7, 17)]

    def test_list_by_range_empty(self, db):
        """范围内无记录 -> 空列表。"""
        records = daily_learning_record_service.list_by_range(
            db, student_id=2, start_date=date(2026, 7, 10), end_date=date(2026, 7, 12)
        )
        assert records == []

    def test_list_by_range_isolates_students(self, db):
        """list_by_range 只返回指定学生的记录。"""
        from app.models.user import User
        from app.utils.security import hash_password

        other = User(username="other_student2", password_hash=hash_password("x"), role="student", display_name="另一学生")
        db.add(other)
        db.flush()
        daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        daily_learning_record_service.get_or_create(db, student_id=other.id, record_date=date(2026, 7, 17))
        records = daily_learning_record_service.list_by_range(
            db, student_id=2, start_date=date(2026, 7, 17), end_date=date(2026, 7, 17)
        )
        assert len(records) == 1
        assert records[0].student_id == 2
