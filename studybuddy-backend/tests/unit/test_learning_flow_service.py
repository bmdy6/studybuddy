from datetime import date, datetime, timedelta

from app.models.answer import Answer
from app.models.error_book import ErrorBook
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.p2 import StudyPlan, StudyPlanItem
from app.models.question import Question
from app.models.user import User
from app.features.learning.flow_service import get_learning_flow_entry, get_review_flow_entry


def _add_student(db, username: str) -> User:
    student = User(username=username, password_hash="test", role="student", display_name=username)
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _add_plan(
    db,
    *,
    student_id: int,
    title: str,
    planned_date: date,
    item_title: str,
    minutes: int = 20,
) -> StudyPlan:
    plan = StudyPlan(student_id=student_id, title=title, status="active", planned_date=planned_date, created_by=1)
    db.add(plan)
    db.flush()
    db.add(StudyPlanItem(plan_id=plan.id, title=item_title, minutes=minutes, status="todo", sort_order=1))
    db.commit()
    db.refresh(plan)
    return plan


def _add_error(
    db,
    *,
    student_id: int,
    stem: str,
    error_count: int,
    last_wrong_at: datetime,
    tag: str,
) -> ErrorBook:
    exam = Exam(title=f"{tag}测试卷", subject="数学", created_by=1, status="published")
    db.add(exam)
    db.flush()
    question = Question(
        exam_id=exam.id,
        type="single_choice",
        stem=stem,
        options=["A", "B"],
        answer_json={"answer": "B"},
        score=5,
        knowledge_tags=[tag],
    )
    db.add(question)
    db.flush()
    record = ExamRecord(exam_id=exam.id, student_id=student_id, status="graded")
    db.add(record)
    db.flush()
    db.add(Answer(exam_record_id=record.id, question_id=question.id, student_answer="A", is_correct=False))
    error = ErrorBook(
        student_id=student_id,
        question_id=question.id,
        exam_record_id=record.id,
        knowledge_tags=[tag],
        error_count=error_count,
        last_wrong_at=last_wrong_at,
    )
    db.add(error)
    db.commit()
    db.refresh(error)
    return error


def test_today_plan_is_the_first_learning_entry(db):
    student = _add_student(db, "flow_today")
    plan = _add_plan(
        db,
        student_id=student.id,
        title="今日函数复习",
        planned_date=date.today(),
        item_title="复习函数单调性",
        minutes=15,
    )
    _add_error(
        db,
        student_id=student.id,
        stem="函数题",
        error_count=5,
        last_wrong_at=datetime.now(),
        tag="函数",
    )

    entry = get_learning_flow_entry(db, student.id)

    assert entry.kind == "continue_plan"
    assert entry.source_type == "study_plan"
    assert entry.source_id == plan.id
    first_item = (
        db.query(StudyPlanItem)
        .filter(StudyPlanItem.plan_id == plan.id)
        .order_by(StudyPlanItem.sort_order, StudyPlanItem.id)
        .first()
    )
    assert entry.item_id == first_item.id
    assert entry.primary_label == "继续学习"
    assert "复习函数单调性" in entry.prompt
    assert "15 分钟" in entry.evidence


def test_future_and_stale_plans_are_ignored_without_mutating_them(db):
    student = _add_student(db, "flow_boundaries")
    future = _add_plan(
        db,
        student_id=student.id,
        title="未来计划",
        planned_date=date.today() + timedelta(days=1),
        item_title="以后再做",
    )
    stale = _add_plan(
        db,
        student_id=student.id,
        title="旧计划",
        planned_date=date.today() - timedelta(days=15),
        item_title="不再提醒",
    )

    entry = get_learning_flow_entry(db, student.id)

    assert entry.kind == "empty"
    db.refresh(future)
    db.refresh(stale)
    assert future.status == "active"
    assert stale.status == "active"


def test_overdue_plan_is_not_continued(db):
    student = _add_student(db, "flow_overdue")
    _add_plan(
        db,
        student_id=student.id,
        title="两天前的计划",
        planned_date=date.today() - timedelta(days=2),
        item_title="补做概率题",
    )

    entry = get_learning_flow_entry(db, student.id)

    # 产品规则：首页「继续学习」只展示今天的计划，逾期/历史计划不上首页。
    assert entry.kind == "empty"
    assert entry.prompt == ""


def test_no_today_plan_yields_empty_even_with_errors(db):
    student = _add_student(db, "flow_errors")
    _add_error(
        db,
        student_id=student.id,
        stem="最近但只错一次",
        error_count=1,
        last_wrong_at=datetime.now(),
        tag="概率",
    )
    _add_error(
        db,
        student_id=student.id,
        stem="反复出错的函数题",
        error_count=4,
        last_wrong_at=datetime.now() - timedelta(days=1),
        tag="函数",
    )

    entry = get_learning_flow_entry(db, student.id)

    # 产品规则：今天没有计划就直接空态，不再自动推错题（错题走首页分类入口）。
    assert entry.kind == "empty"
    assert entry.source_type is None
    assert entry.prompt == ""


def test_empty_entry_does_not_invent_a_recommendation(db):
    student = _add_student(db, "flow_empty")

    entry = get_learning_flow_entry(db, student.id)

    assert entry.kind == "empty"
    assert entry.source_type is None
    assert entry.source_id is None
    assert entry.prompt == ""
    assert entry.evidence == []


def test_specific_error_review_uses_owned_error_id_and_tag(db):
    student = _add_student(db, "flow_specific_error")
    error = _add_error(
        db,
        student_id=student.id,
        stem="一次函数图像题",
        error_count=2,
        last_wrong_at=datetime.now(),
        tag="一次函数",
    )

    entry = get_review_flow_entry(db, student.id, error_id=error.id)

    assert entry.kind == "review_error"
    assert entry.source_type == "error_book"
    assert entry.source_id == error.id
    assert f"错题 ID：{error.id}" in entry.prompt
    assert "知识点：一次函数" in entry.prompt
    assert "来源：错题本" in entry.prompt
    assert "不要直接标记为已完成或已掌握" in entry.prompt


def test_specific_error_review_rejects_another_students_error(db):
    owner = _add_student(db, "flow_error_owner")
    viewer = _add_student(db, "flow_error_viewer")
    error = _add_error(
        db,
        student_id=owner.id,
        stem="归属测试题",
        error_count=1,
        last_wrong_at=datetime.now(),
        tag="权限",
    )

    try:
        get_review_flow_entry(db, viewer.id, error_id=error.id)
    except ValueError as exc:
        assert str(exc) == "错题不存在"
    else:
        raise AssertionError("应拒绝读取其他学生的错题")


def test_knowledge_review_links_real_error_without_guessing_id(db):
    student = _add_student(db, "flow_knowledge")
    error = _add_error(
        db,
        student_id=student.id,
        stem="概率计算题",
        error_count=3,
        last_wrong_at=datetime.now(),
        tag="概率",
    )

    entry = get_review_flow_entry(db, student.id, knowledge_tag=" 概率 ")

    assert entry.kind == "review_knowledge"
    assert entry.source_type == "learning_map"
    assert entry.source_id == error.id
    assert f"关联错题 ID：{error.id}" in entry.prompt
    assert "知识点：概率" in entry.prompt
    assert "来源：知识地图" in entry.prompt


def test_knowledge_review_without_error_explicitly_has_no_error_id(db):
    student = _add_student(db, "flow_knowledge_empty")

    entry = get_review_flow_entry(db, student.id, knowledge_tag="立体几何")

    assert entry.kind == "review_knowledge"
    assert entry.source_id is None
    assert "当前没有关联错题" in entry.prompt
    assert "不要猜测或编造错题 ID" in entry.prompt
