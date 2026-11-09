from datetime import datetime, timedelta
from decimal import Decimal

from app.models.error_book import ErrorBook
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.material import Material
from app.models.note import Note
from app.models.p2 import StudyPlan, StudyPlanItem
from app.models.question import Question
from app.features.learning.map_service import build_learning_map, summarize_learning_map_for_agent


def _exam_record(db):
    exam = Exam(title="学习地图测试卷", subject="英语", status="published", created_by=1)
    db.add(exam)
    db.flush()
    record = ExamRecord(exam_id=exam.id, student_id=2, status="graded")
    db.add(record)
    db.flush()
    return exam, record


def _question(db, exam_id: int, stem: str, tags: list[str]) -> Question:
    q = Question(
        exam_id=exam_id,
        type="single_choice",
        stem=stem,
        options=["A", "B"],
        answer_json="A",
        knowledge_tags=tags,
        score=Decimal("2.00"),
    )
    db.add(q)
    db.flush()
    return q


def test_learning_map_groups_errors_by_tag_and_marks_weak(db):
    exam, record = _exam_record(db)
    q1 = _question(db, exam.id, "一般过去时选择题", ["一般过去时"])
    q2 = _question(db, exam.id, "一般过去时填空题", ["一般过去时"])
    now = datetime.utcnow()
    db.add_all(
        [
            ErrorBook(
                student_id=2,
                question_id=q1.id,
                exam_record_id=record.id,
                knowledge_tags=["一般过去时"],
                error_count=2,
                last_wrong_at=now,
            ),
            ErrorBook(
                student_id=2,
                question_id=q2.id,
                exam_record_id=record.id,
                knowledge_tags=["一般过去时"],
                error_count=1,
                last_wrong_at=now,
            ),
        ]
    )
    db.commit()

    result = build_learning_map(db, 2)

    node = next(item for item in result.nodes if item.tag == "一般过去时")
    assert node.status == "weak"
    assert node.error_count == 3
    assert node.note_count == 0
    assert any(resource.type == "error" for resource in node.resources)
    assert "复盘" in " ".join(node.next_actions)


def test_learning_map_marks_reviewing_when_error_has_review_note(db):
    exam, record = _exam_record(db)
    q = _question(db, exam.id, "单位换算题", ["单位换算"])
    db.add(ErrorBook(student_id=2, question_id=q.id, exam_record_id=record.id, knowledge_tags=["单位换算"], error_count=2))
    db.add(
        Note(
            student_id=2,
            type="study_record",
            title="单位换算复盘",
            subject="物理",
            category="错题复盘",
            content="下次先统一单位。",
            knowledge_tags=["单位换算"],
            source="错题讲解",
            source_ref=[1],
            status="confirmed",
        )
    )
    db.commit()

    result = build_learning_map(db, 2)

    node = next(item for item in result.nodes if item.tag == "单位换算")
    assert node.status == "reviewing"
    assert node.note_count == 1
    assert any(resource.type == "note" and resource.title == "单位换算复盘" for resource in node.resources)


def test_learning_map_only_counts_confirmed_material_as_material_resource(db):
    db.add_all(
        [
            Material(
                name="已确认素材",
                type="image",
                source="student",
                uploaded_by=2,
                knowledge_tags=["机械秒表"],
                recognition_status="confirmed",
                confirmed_markdown="秒表读数方法",
            ),
            Material(
                name="未确认素材",
                type="image",
                source="student",
                uploaded_by=2,
                knowledge_tags=["机械秒表"],
                recognition_status="recognized",
                recognized_markdown="待确认",
            ),
        ]
    )
    db.commit()

    result = build_learning_map(db, 2)

    node = next(item for item in result.nodes if item.tag == "机械秒表")
    assert node.status == "unknown"
    assert node.material_count == 1
    assert [resource.title for resource in node.resources if resource.type == "material"] == ["已确认素材"]


def test_learning_map_marks_stable_for_completed_plan_without_recent_error(db):
    exam, record = _exam_record(db)
    old = datetime.utcnow() - timedelta(days=30)
    q = _question(db, exam.id, "阅读理解题", ["阅读理解"])
    db.add(ErrorBook(student_id=2, question_id=q.id, exam_record_id=record.id, knowledge_tags=["阅读理解"], error_count=1, last_wrong_at=old))
    plan = StudyPlan(student_id=2, title="阅读巩固", focus="阅读理解", status="completed", created_by=2)
    db.add(plan)
    db.flush()
    db.add(
        StudyPlanItem(
            plan_id=plan.id,
            title="完成阅读练习",
            target="做一篇阅读",
            minutes=20,
            status="done",
            related_tags=["阅读理解"],
            completed_at=datetime.utcnow(),
        )
    )
    db.commit()

    result = build_learning_map(db, 2)

    node = next(item for item in result.nodes if item.tag == "阅读理解")
    assert node.status == "stable"
    assert node.plan_item_count == 1


def test_summarize_learning_map_for_agent_uses_real_nodes_only(db):
    exam, record = _exam_record(db)
    q = _question(db, exam.id, "分数应用题", ["分数应用题"])
    db.add(ErrorBook(student_id=2, question_id=q.id, exam_record_id=record.id, knowledge_tags=["分数应用题"], error_count=3))
    db.commit()
    result = build_learning_map(db, 2)

    lines = summarize_learning_map_for_agent(result)

    assert lines
    assert "分数应用题" in lines[0]
    assert "需要优先补" in lines[0]
