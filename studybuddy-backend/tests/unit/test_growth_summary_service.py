from datetime import datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.models.note import Note
from app.models.daily_learning_record import DailyLearningRecord
from app.models.notification import Notification
from app.models.p2 import LearningFeedback, StudyPlan, StudyPlanItem
from app.models.teacher_student import TeacherStudent
from app.models.user import User
from app.models.wechat import (
    WECHAT_CHANNEL_ILINK_BOT,
    WechatAccount,
    WechatGuardianStudentContext,
)
from app.features.growth import daily_record_service as daily_learning_record_service
from app.core import ai_service
from app.features.growth import facts, evidence, summary, guardian_today, dispatch
from app.utils.duration import parse_duration_minutes
from app.utils.security import hash_password


def _guardian_context(db, *, openid: str, push_time: str = "20:30"):
    account = WechatAccount(
        user_id=1,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid=openid,
        status="active",
        bound_at=datetime.utcnow(),
        last_interacted_at=datetime(2026, 7, 12, 11, 0),
    )
    db.add(account)
    db.flush()
    context = WechatGuardianStudentContext(
        account_id=account.id,
        student_id=2,
        push_time=push_time,
    )
    db.add(context)
    db.commit()
    return account, context


def _stub_daily_record_refresh(monkeypatch):
    async def refresh(db, student_id, record_date, *, now=None):
        return daily_learning_record_service.get_or_create(db, student_id, record_date)

    monkeypatch.setattr(daily_learning_record_service, "refresh", refresh)


def test_growth_evidence_uses_confirmed_titles_without_private_note_content(db) -> None:
    db.add(
        Note(
            student_id=2,
            type="study_record",
            title="函数错题复盘",
            subject="数学",
            category="函数",
            content="PRIVATE_NOTE_CONTENT_SENTINEL",
            knowledge_tags=["一次函数"],
            source="错题讲解",
            status="confirmed",
            created_at=datetime(2026, 7, 12, 8, 0),
        )
    )
    db.commit()

    growth_evidence = evidence.collect_growth_evidence(
        db,
        2,
        period="daily",
        now=datetime(2026, 7, 12, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    serialized = growth_evidence.model_dump_json()
    assert growth_evidence.has_evidence is True
    assert growth_evidence.confirmed_notes == [
        {
            "title": "函数错题复盘",
            "subject": "数学",
            "knowledge_tags": ["一次函数"],
        }
    ]
    assert "PRIVATE_NOTE_CONTENT_SENTINEL" not in serialized


def test_guardian_today_summary_reports_real_duration_content_and_pending_work(db) -> None:
    plan = StudyPlan(
        student_id=2,
        title="英语计划",
        status="active",
        planned_date=datetime(2026, 7, 12).date(),
    )
    db.add(plan)
    db.flush()
    db.add_all(
        [
            LearningFeedback(
                student_id=2,
                feedback_type="duration",
                content="数学复习了30分钟",
                created_at=datetime(2026, 7, 12, 8, 0),
            ),
            LearningFeedback(
                student_id=2,
                feedback_type="duration",
                content="英语学习0.5小时",
                created_at=datetime(2026, 7, 12, 9, 0),
            ),
            LearningFeedback(
                student_id=2,
                feedback_type="duration",
                content="完成学习计划任务「背 Unit 5 单词」，预计用时 20 分钟。",
                created_at=datetime(2026, 7, 12, 9, 30),
            ),
            StudyPlanItem(
                plan_id=plan.id,
                title="背 Unit 5 单词",
                minutes=20,
                status="done",
                completed_at=datetime(2026, 7, 12, 9, 30),
            ),
            StudyPlanItem(
                plan_id=plan.id,
                title="英语阅读练习",
                minutes=40,
                status="todo",
            ),
        ]
    )
    db.commit()

    result = guardian_today.build_guardian_today_learning_summary(
        db,
        2,
        now=datetime(2026, 7, 12, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result == (
        "今天学习 60 分钟。\n\n"
        "完成：\n"
        "- 英语计划：背 Unit 5 单词\n\n"
        "还有 1 项未完成：英语阅读练习。"
    )
    assert "80 分钟" not in result


def test_guardian_today_summary_is_direct_when_today_has_no_records(db) -> None:
    student = User(
        username="guardian_empty_today_student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="空记录学生",
    )
    db.add(student)
    db.commit()

    result = guardian_today.build_guardian_today_learning_summary(
        db,
        student.id,
        now=datetime(2026, 7, 12, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result == "今天还没有学习记录，学习时长也未记录。"


def test_guardian_today_summary_does_not_invent_duration_for_completed_content(db) -> None:
    student = User(
        username="guardian_no_duration_student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="无时长学生",
    )
    db.add(student)
    db.flush()
    plan = StudyPlan(student_id=student.id, title="数学计划", status="active")
    db.add(plan)
    db.flush()
    db.add(
        StudyPlanItem(
            plan_id=plan.id,
            title="复习一次函数",
            minutes=30,
            status="done",
            completed_at=datetime(2026, 7, 12, 9, 30),
        )
    )
    db.commit()

    result = guardian_today.build_guardian_today_learning_summary(
        db,
        student.id,
        now=datetime(2026, 7, 12, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result == "学习时长暂未记录。\n\n完成：\n- 数学计划：复习一次函数"
    assert "30 分钟" not in result


def test_duration_minutes_keeps_real_report_with_keyword预计() -> None:
    """学生真实上报但内容碰巧含'预计'二字时，时长不应被误丢。

    回归：旧实现用 `"预计" in content` 排除计划完成反馈，
    但"今天预计学了40分钟"这种真实上报也会被归零。
    """
    # 学生真实上报，含"预计"但确实是手动输入的时长
    assert parse_duration_minutes("今天预计学了40分钟") == 40
    # 混合单位 1小时20分钟 = 80 分钟
    assert parse_duration_minutes("学了1小时20分钟") == 80
    # 无单位纯数字不算时长
    assert parse_duration_minutes("学了30") == 0


def test_duration_minutes_excludes_plan_completion_auto_feedback() -> None:
    """计划完成自动生成的反馈文案（含预计分钟）不应算作真实时长。"""
    auto_content = "完成学习计划任务「背 Unit 5 单词」，预计用时 20 分钟。"
    assert parse_duration_minutes(auto_content) == 0


def test_guardian_positive_summary_from_daily_record_keeps_machine_evidence_separate() -> None:
    record = DailyLearningRecord(
        student_id=2,
        record_date=datetime(2026, 7, 12).date(),
        facts_snapshot={
            "evidence": [
                {"tier": "machine_extracted", "title": "英语单词表", "source_type": "material"},
            ],
            "pending_tasks": [{"item_title": "订正错题"}],
            "self_reported_duration_minutes": 0,
        },
        summary_text="AI 可能写了进步",
        summary_source="ai",
    )

    guardian_facts = facts.guardian_summary_facts_from_record(record)
    result = summary.deterministic_guardian_positive_summary(guardian_facts)

    assert "机器识别素材" in result
    assert "截至推送时间尚有 1 项未完成" in result
    assert "掌握" not in result
    assert "进步" not in result


def test_guardian_positive_summary_falls_back_when_llm_fails(monkeypatch) -> None:
    async def fail(**_kwargs):
        raise TimeoutError("slow")

    monkeypatch.setattr(ai_service, "call_llm", fail)
    result = summary.generate_guardian_positive_summary(
        {
            "evidence": [{"tier": "verified", "title": "函数错题复盘"}],
            "pending_tasks": [],
            "self_reported_duration_minutes": 0,
        }
    )

    assert "函数错题复盘" in result
    assert "值得肯定" in result


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (
            {
                "evidence": [{"tier": "verified", "title": "提交数学试卷"}],
                "pending_tasks": [],
            },
            "提交数学试卷",
        ),
        (
            {
                "evidence": [{"tier": "self_reported", "title": "完成背单词计划"}],
                "pending_tasks": [{"item_title": "英语阅读"}],
            },
            "截至推送时间尚有 1 项未完成",
        ),
        (
            {"evidence": [], "pending_tasks": [], "self_reported_duration_minutes": 0},
            "今天暂时没有新的学习记录",
        ),
    ],
)
def test_guardian_positive_fallback_covers_completed_partial_and_empty(facts, expected) -> None:
    result = summary.deterministic_guardian_positive_summary(facts)
    assert expected in result
    assert "掌握" not in result


def test_guardian_today_summary_with_duration_but_no_content(db) -> None:
    """有时长但无完成内容/笔记/错题/试卷时，应说明今天暂未记录具体学习内容。"""
    student = User(
        username="guardian_duration_only_student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="仅时长学生",
    )
    db.add(student)
    db.flush()
    db.add(
        LearningFeedback(
            student_id=student.id,
            feedback_type="duration",
            content="数学复习了45分钟",
            created_at=datetime(2026, 7, 12, 8, 0),
        )
    )
    db.commit()

    result = guardian_today.build_guardian_today_learning_summary(
        db,
        student.id,
        now=datetime(2026, 7, 12, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert "今天学习 45 分钟" in result
    assert "今天暂未记录具体学习内容" in result


def test_generate_growth_summary_passes_evidence_and_reasoning_frame(db, monkeypatch) -> None:
    growth_evidence = evidence.GrowthEvidence(
        student_id=2,
        student_name="测试学生",
        period="daily",
        period_start="2026-07-12T00:00:00+08:00",
        period_end="2026-07-12T20:30:00+08:00",
        confirmed_notes=[{"title": "函数错题复盘", "subject": "数学", "knowledge_tags": ["一次函数"]}],
    )
    captured = {}

    async def fake_call_llm_stream(*, messages, system, max_tokens):
        captured.update(messages=messages, system=system, max_tokens=max_tokens)

        async def chunks():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="今天完成了函数错题复盘。继续鼓励即可。",
                            reasoning_content=None,
                        )
                    )
                ]
            )

        return chunks()

    monkeypatch.setattr(ai_service, "call_llm_stream", fake_call_llm_stream)

    result = summary.generate_growth_summary(growth_evidence)

    assert result == "今天完成了函数错题复盘。继续鼓励即可。"
    prompt = captured["messages"][0]["content"]
    assert "函数错题复盘" in prompt
    assert "今天或本周真实发生了什么" in captured["system"]
    assert "家长现在最合适的行动是什么" in captured["system"]


def test_generate_growth_summary_never_exposes_reasoning_content(db, monkeypatch) -> None:
    growth_evidence = evidence.GrowthEvidence(
        student_id=2,
        student_name="测试学生",
        period="daily",
        period_start="2026-07-12T00:00:00+08:00",
        period_end="2026-07-12T20:30:00+08:00",
    )

    async def fake_call_llm_stream(**_kwargs):
        async def chunks():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            reasoning_content="PRIVATE_MODEL_REASONING_SENTINEL",
                        )
                    )
                ]
            )

        return chunks()

    monkeypatch.setattr(ai_service, "call_llm_stream", fake_call_llm_stream)

    with pytest.raises(RuntimeError, match="成长摘要生成失败"):
        summary.generate_growth_summary(growth_evidence)


def test_sunday_dispatch_replaces_daily_and_dedupes(db, monkeypatch) -> None:
    account, _context = _guardian_context(db, openid="growth-sunday@im.wechat")
    _stub_daily_record_refresh(monkeypatch)
    generated_periods = []
    sent = []

    def fake_generate(facts):
        generated_periods.append(facts["period"])
        return "本周真实成长总结"

    monkeypatch.setattr(summary, "generate_guardian_positive_summary", fake_generate)
    now = datetime(2026, 7, 12, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    first = dispatch.dispatch_due_growth_summaries(
        db,
        now=now,
        send_ilink=lambda bot, user, content: sent.append((bot, user, content)) or "success",
    )
    repeated = dispatch.dispatch_due_growth_summaries(
        db,
        now=now,
        send_ilink=lambda bot, user, content: sent.append((bot, user, content)) or "success",
    )

    notifications = db.query(Notification).filter(Notification.recipient_id == 1, Notification.student_id == 2).all()
    assert first == {"sent": 1, "paused": 0, "failed": 0}
    assert repeated == {"sent": 0, "paused": 0, "failed": 0}
    assert generated_periods == ["weekly"]
    assert len(notifications) == 1
    assert notifications[0].notification_type == "weekly_growth_summary"
    assert len(sent) == 1
    assert sent[0][0:2] == (account.provider_account_id, account.openid)
    assert "测试学生" in sent[0][2]
    assert "本周真实成长总结" in sent[0][2]


def test_multi_student_dispatch_generates_independently_and_sends_once(db, monkeypatch) -> None:
    account, _context = _guardian_context(db, openid="growth-multi@im.wechat")
    _stub_daily_record_refresh(monkeypatch)
    second = User(
        username="growth-second-student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="第二个学生",
    )
    db.add(second)
    db.flush()
    db.add(TeacherStudent(teacher_id=1, student_id=second.id))
    db.add(
        WechatGuardianStudentContext(
            account_id=account.id,
            student_id=second.id,
            push_time="20:30",
        )
    )
    db.commit()
    generated_students = []
    sent = []

    def fake_generate(facts):
        generated_students.append(facts["evidence"])
        return "真实摘要"

    monkeypatch.setattr(summary, "generate_guardian_positive_summary", fake_generate)

    result = dispatch.dispatch_due_growth_summaries(
        db,
        now=datetime(2026, 7, 11, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        send_ilink=lambda _bot, _user, content: sent.append(content) or "success",
    )

    assert result == {"sent": 1, "paused": 0, "failed": 0}
    assert len(generated_students) == 2
    assert len(sent) == 1
    assert "测试学生\n" in sent[0]
    assert "第二个学生\n" in sent[0]


def test_dispatch_rechecks_relationship_before_generation(db, monkeypatch) -> None:
    _account, _context = _guardian_context(db, openid="growth-unbound@im.wechat")
    db.query(TeacherStudent).filter(
        TeacherStudent.teacher_id == 1,
        TeacherStudent.student_id == 2,
    ).delete(synchronize_session=False)
    db.commit()
    generated = []

    monkeypatch.setattr(
        summary,
        "generate_guardian_positive_summary",
        lambda facts: generated.append(facts) or "不应生成",
    )

    result = dispatch.dispatch_due_growth_summaries(
        db,
        now=datetime(2026, 7, 11, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        send_ilink=lambda *_args: "success",
    )

    assert result == {"sent": 0, "paused": 0, "failed": 0}
    assert generated == []


def test_daily_record_refresh_failure_is_retryable_without_fake_summary(db, monkeypatch) -> None:
    account, _context = _guardian_context(db, openid="growth-generate-failure@im.wechat")
    attempts = []

    async def fail_refresh(_db, student_id, _record_date, *, now=None):
        attempts.append(student_id)
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(daily_learning_record_service, "refresh", fail_refresh)
    now = datetime(2026, 7, 11, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    first = dispatch.dispatch_due_growth_summaries(db, now=now, send_ilink=lambda *_args: "success")
    second = dispatch.dispatch_due_growth_summaries(db, now=now, send_ilink=lambda *_args: "success")

    db.refresh(account)
    assert first == {"sent": 0, "paused": 0, "failed": 1}
    assert second == {"sent": 0, "paused": 0, "failed": 1}
    assert attempts == [2, 2]
    assert account.last_reminder_claimed_minute is None
    assert db.query(Notification).filter(Notification.recipient_id == 1).count() == 0


def test_provider_failure_reuses_generated_summary_on_retry(db, monkeypatch) -> None:
    account, _context = _guardian_context(db, openid="growth-provider-retry@im.wechat")
    _stub_daily_record_refresh(monkeypatch)
    generated = []

    monkeypatch.setattr(
        summary,
        "generate_guardian_positive_summary",
        lambda facts: generated.append(facts["period"]) or "只生成一次的真实摘要",
    )
    statuses = iter(["failed", "success"])
    now = datetime(2026, 7, 11, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    first = dispatch.dispatch_due_growth_summaries(db, now=now, send_ilink=lambda *_args: next(statuses))
    second = dispatch.dispatch_due_growth_summaries(db, now=now, send_ilink=lambda *_args: next(statuses))

    db.refresh(account)
    assert first == {"sent": 0, "paused": 0, "failed": 1}
    assert second == {"sent": 1, "paused": 0, "failed": 0}
    assert generated == ["daily"]
    assert account.proactive_message_count == 1


def test_daily_dispatch_refreshes_and_reads_daily_record_facts(db, monkeypatch) -> None:
    account, _context = _guardian_context(db, openid="growth-daily-record@im.wechat")
    record = DailyLearningRecord(
        student_id=2,
        record_date=datetime(2026, 7, 11).date(),
        facts_snapshot={
            "evidence": [
                {
                    "source_type": "exam_record",
                    "source_id": 901,
                    "version": 1,
                    "tier": "verified",
                    "title": "数学单元测试",
                }
            ],
            "pending_tasks": [{"plan_title": "今日计划", "item_title": "订正错题"}],
            "self_reported_duration_minutes": 30,
            "has_verified_evidence": True,
        },
        summary_text="日报摘要不应直接当作事实",
        summary_source="ai",
        generation_status="ready",
    )
    db.add(record)
    db.commit()
    refreshed = []
    captured = []

    async def fake_refresh(_db, student_id, record_date, *, now=None):
        refreshed.append((student_id, record_date, now))
        return record

    monkeypatch.setattr(daily_learning_record_service, "refresh", fake_refresh)
    monkeypatch.setattr(
        evidence,
        "collect_growth_evidence",
        lambda *_args, **_kwargs: pytest.fail("推送不应再次散查原始证据"),
    )
    monkeypatch.setattr(
        summary,
        "generate_guardian_positive_summary",
        lambda facts: captured.append(facts) or "基于日报事实的家长摘要",
    )

    result = dispatch.dispatch_due_growth_summaries(
        db,
        now=datetime(2026, 7, 11, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        send_ilink=lambda _bot, _user, content: content and "success",
    )

    assert result == {"sent": 1, "paused": 0, "failed": 0}
    assert refreshed and refreshed[0][0:2] == (2, datetime(2026, 7, 11).date())
    assert captured[0]["period"] == "daily"
    assert captured[0]["evidence"][0]["title"] == "数学单元测试"
    assert captured[0]["pending_tasks"] == [{"plan_title": "今日计划", "item_title": "订正错题"}]
    assert account.proactive_message_count == 1


def test_weekly_dispatch_aggregates_stored_daily_records(db, monkeypatch) -> None:
    _account, _context = _guardian_context(db, openid="growth-weekly-record@im.wechat")
    db.add_all(
        [
            DailyLearningRecord(
                student_id=2,
                record_date=datetime(2026, 7, 6).date(),
                facts_snapshot={
                    "evidence": [{"source_type": "note", "source_id": 11, "version": 1, "tier": "verified", "title": "函数复盘"}],
                    "pending_tasks": [],
                    "self_reported_duration_minutes": 20,
                    "has_verified_evidence": True,
                },
                summary_text="周一摘要",
                summary_source="ai",
                generation_status="ready",
            ),
            DailyLearningRecord(
                student_id=2,
                record_date=datetime(2026, 7, 9).date(),
                facts_snapshot={
                    "evidence": [{"source_type": "material", "source_id": 12, "version": 1, "tier": "machine_extracted", "title": "英语单词表"}],
                    "pending_tasks": [{"plan_title": "本周计划", "item_title": "订正错题"}],
                    "self_reported_duration_minutes": 15,
                    "has_verified_evidence": False,
                },
                summary_text="周三摘要",
                summary_source="deterministic",
                generation_status="ready",
            ),
            DailyLearningRecord(
                student_id=2,
                record_date=datetime(2026, 7, 12).date(),
                facts_snapshot={"evidence": [], "pending_tasks": [], "self_reported_duration_minutes": 0, "has_verified_evidence": False},
                summary_text="今天暂时没有新的学习记录。",
                summary_source="deterministic",
                generation_status="ready",
            ),
        ]
    )
    db.commit()
    refreshed = []
    captured = []

    async def fake_refresh(_db, student_id, record_date, *, now=None):
        refreshed.append((student_id, record_date))
        return db.query(DailyLearningRecord).filter_by(student_id=student_id, record_date=record_date).one()

    monkeypatch.setattr(daily_learning_record_service, "refresh", fake_refresh)
    monkeypatch.setattr(
        summary,
        "generate_guardian_positive_summary",
        lambda facts: captured.append(facts) or "聚合本周日报的家长摘要",
    )

    result = dispatch.dispatch_due_growth_summaries(
        db,
        now=datetime(2026, 7, 12, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        send_ilink=lambda _bot, _user, content: content and "success",
    )

    assert result == {"sent": 1, "paused": 0, "failed": 0}
    assert refreshed == [(2, datetime(2026, 7, 12).date())]
    assert captured[0]["period"] == "weekly"
    assert {item["source_id"] for item in captured[0]["evidence"]} == {11, 12}
    assert captured[0]["self_reported_duration_minutes"] == 35
    assert captured[0]["pending_tasks"] == [{"plan_title": "本周计划", "item_title": "订正错题"}]


def test_multi_student_refresh_failure_retries_missing_child_without_duplicate_section(db, monkeypatch) -> None:
    account, _context = _guardian_context(db, openid="growth-partial-retry@im.wechat")
    second = User(
        username="growth-partial-second",
        password_hash=hash_password("student123"),
        role="student",
        display_name="第二个学生",
    )
    db.add(second)
    db.flush()
    db.add(TeacherStudent(teacher_id=1, student_id=second.id))
    db.add(WechatGuardianStudentContext(account_id=account.id, student_id=second.id, push_time="20:30"))
    db.commit()
    attempts: list[int] = []
    sent: list[str] = []
    competing: list[dict[str, int]] = []

    async def refresh(_db, student_id, record_date, *, now=None):
        attempts.append(student_id)
        if student_id == 2 and attempts.count(student_id) == 1:
            raise RuntimeError("temporary refresh failure")
        if student_id == second.id and len(competing) == 0:
            competing.append(
                dispatch.dispatch_due_growth_summaries(
                    db,
                    now=now,
                    send_ilink=lambda *_args: "success",
                )
            )
        return daily_learning_record_service.get_or_create(db, student_id, record_date)

    monkeypatch.setattr(daily_learning_record_service, "refresh", refresh)
    monkeypatch.setattr(summary, "generate_guardian_positive_summary", lambda _facts: "事实摘要")
    now = datetime(2026, 7, 11, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    first = dispatch.dispatch_due_growth_summaries(
        db,
        now=now,
        send_ilink=lambda _bot, _user, content: sent.append(content) or "success",
    )
    db.refresh(account)
    assert account.proactive_message_count == 1
    assert account.last_reminder_sent_at is None
    assert account.last_reminder_claimed_minute is None
    second_result = dispatch.dispatch_due_growth_summaries(
        db,
        now=now,
        send_ilink=lambda _bot, _user, content: sent.append(content) or "success",
    )
    db.refresh(account)

    assert first == {"sent": 1, "paused": 0, "failed": 1}
    assert second_result == {"sent": 1, "paused": 0, "failed": 0}
    assert competing == [{"sent": 0, "paused": 0, "failed": 0}]
    assert "第二个学生" in sent[0]
    assert "测试学生" not in sent[0]
    assert "测试学生" in sent[1]
    assert "第二个学生" not in sent[1]
    assert account.proactive_message_count == 2
    assert account.last_reminder_sent_at is not None


def _seed_today_plan_with_done_and_todo(db, student_id: int, *, record_date) -> None:
    """造一份今日学习数据：1 项完成计划 + 1 项未完成 + 时长反馈。"""
    plan = StudyPlan(
        student_id=student_id,
        title="英语计划",
        status="active",
        planned_date=record_date,
    )
    db.add(plan)
    db.flush()
    db.add_all(
        [
            LearningFeedback(
                student_id=student_id,
                feedback_type="duration",
                content="数学复习了30分钟",
                created_at=datetime.combine(record_date, time(8, 0)),
            ),
            StudyPlanItem(
                plan_id=plan.id,
                title="背 Unit 5 单词",
                minutes=20,
                status="done",
                completed_at=datetime.combine(record_date, time(9, 30)),
            ),
            StudyPlanItem(
                plan_id=plan.id,
                title="英语阅读练习",
                minutes=40,
                status="todo",
            ),
        ]
    )
    db.commit()


def test_guardian_today_query_reads_same_facts_as_push(db, monkeypatch) -> None:
    """主动查询与定时推送必须读同一份事实（aggregate_daily_facts），不能各自查证据。"""
    student = User(
        username="guardian_query_same_facts_student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="同事实学生",
    )
    db.add(student)
    db.commit()
    _seed_today_plan_with_done_and_todo(db, student.id, record_date=datetime(2026, 7, 12).date())

    # 监控 collect_growth_evidence：主动查询主路径不应直接查证据（走每日记录事实）
    collect_calls: list[int] = []
    real_collect = evidence.collect_growth_evidence

    def spy_collect(db, student_id, *, period, now):
        collect_calls.append(student_id)
        return real_collect(db, student_id, period=period, now=now)

    monkeypatch.setattr(evidence, "collect_growth_evidence", spy_collect)

    guardian_today.build_guardian_today_learning_summary(
        db,
        student.id,
        now=datetime(2026, 7, 12, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    # 主动查询主路径不应直接调 collect_growth_evidence（事实来自每日记录同源聚合）
    assert collect_calls == []


def test_guardian_today_query_prefers_persisted_daily_record_facts(db, monkeypatch) -> None:
    """已有当日记录时必须直接读记录的 facts_snapshot，不再现场聚合。"""
    student = User(
        username="guardian_query_prefers_record_student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="优先记录学生",
    )
    db.add(student)
    db.commit()

    # 预置一条当日记录（模拟定时 refresh 已写入），事实只含时长不含完成项
    record_date = datetime(2026, 7, 12).date()
    daily_learning_record_service.get_or_create(db, student.id, record_date)
    record = daily_learning_record_service.get_by_date(db, student_id=student.id, record_date=record_date)
    assert record is not None
    record.facts_snapshot = {
        "evidence": [],
        "pending_tasks": [],
        "self_reported_duration_minutes": 42,
    }
    db.commit()

    # 同时造一份完成项数据，确保主路径不去现场聚合拿到它
    plan = StudyPlan(student_id=student.id, title="数学计划", status="active", planned_date=record_date)
    db.add(plan)
    db.flush()
    db.add(StudyPlanItem(plan_id=plan.id, title="复习一次函数", minutes=30, status="done", completed_at=datetime(2026, 7, 12, 9, 30)))
    db.commit()

    aggregate_calls: list[int] = []
    real_aggregate = daily_learning_record_service.aggregate_daily_facts

    def spy_aggregate(db, student_id, record_date, *, now=None):
        aggregate_calls.append(student_id)
        return real_aggregate(db, student_id, record_date, now=now)

    monkeypatch.setattr(
        daily_learning_record_service, "aggregate_daily_facts", spy_aggregate
    )

    result = guardian_today.build_guardian_today_learning_summary(
        db,
        student.id,
        now=datetime(2026, 7, 12, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    # 已有记录时不现场聚合
    assert aggregate_calls == []
    # 读到的是记录里的时长（42），不是现场数据（0 或 30）
    assert "今天学习 42 分钟" in result
    assert "数学计划：复习一次函数" not in result


def test_guardian_today_query_falls_back_when_aggregate_fails(db, monkeypatch) -> None:
    """现场聚合失败时必须回退到直接查证据的确定性事实，不让单条家长消息失败。"""
    student = User(
        username="guardian_query_fallback_student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="兜底学生",
    )
    db.add(student)
    db.commit()
    _seed_today_plan_with_done_and_todo(db, student.id, record_date=datetime(2026, 7, 12).date())

    def fail_aggregate(*_args, **_kwargs):
        raise RuntimeError("aggregate_daily_facts 模拟失败")

    monkeypatch.setattr(
        daily_learning_record_service, "aggregate_daily_facts", fail_aggregate
    )

    result = guardian_today.build_guardian_today_learning_summary(
        db,
        student.id,
        now=datetime(2026, 7, 12, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    # 聚合失败仍要返回确定性事实，不能抛错
    assert "今天学习 30 分钟" in result
    assert "英语计划：背 Unit 5 单词" in result
    assert "还有 1 项未完成：英语阅读练习" in result


def test_guardian_today_query_no_invented_duration_from_pending_plan(db, monkeypatch) -> None:
    """无真实时长时不能把计划预计分钟冒充实际时长（PR-19 边界：与定时推送一致）。"""
    student = User(
        username="guardian_query_no_duration_student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="无时长学生",
    )
    db.add(student)
    db.commit()
    plan = StudyPlan(
        student_id=student.id,
        title="数学计划",
        status="active",
        planned_date=datetime(2026, 7, 12).date(),
    )
    db.add(plan)
    db.flush()
    db.add(
        StudyPlanItem(
            plan_id=plan.id,
            title="复习一次函数",
            minutes=30,
            status="done",
            completed_at=datetime(2026, 7, 12, 9, 30),
        )
    )
    db.commit()

    result = guardian_today.build_guardian_today_learning_summary(
        db,
        student.id,
        now=datetime(2026, 7, 12, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert "学习时长暂未记录" in result
    assert "30 分钟" not in result
    assert "数学计划：复习一次函数" in result
