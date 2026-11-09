from datetime import date, datetime, timedelta
from decimal import Decimal

from app.models.error_book import ErrorBook
from app.models.exam import Exam
from app.models.exam_assignment import ExamAssignment
from app.models.exam_record import ExamRecord
from app.models.note import Note
from app.models.p2 import StudyPlan, StudyPlanItem
from app.models.question import Question
from app.features.growth.supervision_service import build_supervision_summary, extract_support_section


def test_extract_support_section_from_daily_review_markdown():
    content = """## 昨日回顾（2026.7.6）

学了英语。

## 今日目标（2026.7.7）

- [ ] 复习一般过去时

## 需要督促的地方

下午开始前容易拖延，希望先提醒我打开书。
"""
    assert extract_support_section(content) == "下午开始前容易拖延，希望先提醒我打开书。"


def test_supervision_summary_uses_real_plan_review_error_and_assignment(db):
    exam = Exam(title="英语周练", subject="english", status="published", created_by=1)
    db.add(exam)
    db.flush()
    record = ExamRecord(exam_id=exam.id, student_id=2, status="graded")
    db.add(record)
    db.flush()
    question = Question(
        exam_id=exam.id,
        type="single_choice",
        stem="He ___ to school yesterday.",
        options=["go", "went"],
        answer_json="went",
        score=Decimal("2.00"),
        knowledge_tags=["一般过去时"],
    )
    db.add(question)
    db.flush()
    db.add(
        ErrorBook(
            student_id=2,
            question_id=question.id,
            exam_record_id=record.id,
            knowledge_tags=["一般过去时"],
            error_count=4,
        )
    )
    plan = StudyPlan(
        student_id=2,
        title="英语补漏",
        focus="一般过去时",
        status="active",
        planned_date=date.today(),
        created_by=1,
    )
    db.add(plan)
    db.flush()
    db.add(
        StudyPlanItem(
            plan_id=plan.id,
            title="做 2 道过去时错题",
            target="能说出错因",
            minutes=20,
            status="todo",
            related_tags=["一般过去时"],
            sort_order=1,
        )
    )
    db.add(
        Note(
            student_id=2,
            type="study_record",
            title="2026.7.7 每日回顾",
            subject="其他",
            category="每日回顾",
            content=(
                "## 昨日回顾（2026.7.6）\n\n背了单词。\n\n"
                "## 今日目标（2026.7.7）\n\n- [ ] 学英语\n\n"
                "## 需要督促的地方\n\n下午不要先刷视频。"
            ),
            knowledge_tags=["每日回顾"],
            source="每日回顾",
            status="confirmed",
        )
    )
    db.add(
        ExamAssignment(
            exam_id=exam.id,
            student_id=2,
            assigned_by=1,
            status="assigned",
            due_at=datetime.utcnow() + timedelta(days=2),
            note="周五前完成",
        )
    )
    db.commit()

    summary = build_supervision_summary(db, 2)

    assert summary.student_id == 2
    assert summary.reminders[0].title == "英语补漏"
    assert summary.support_items[0].content == "下午不要先刷视频。"
    assert summary.weak_points[0].tag == "一般过去时"
    assert summary.recent_assignments[0].exam_title == "英语周练"
    assert "一般过去时" in summary.weekly_report.highlights[0]
    assert summary.weekly_report.is_empty is False


def test_supervision_summary_empty_state_does_not_invent_data(db):
    summary = build_supervision_summary(db, 2)

    assert summary.reminders == []
    assert summary.support_items == []
    assert summary.weak_points == []
    assert summary.recent_assignments == []
    assert summary.weekly_report.is_empty is True
    assert "记录还不够" in summary.weekly_report.summary
