"""考试批次服务单测。"""

from sqlalchemy.orm import Session

from app.models.error_book import ErrorBook
from app.models.exam import Exam
from app.models.exam_batch import ExamBatch
from app.models.exam_record import ExamRecord
from app.models.question import Question
from app.features.exams.schemas.exam_batch import ParsedQuestion
from app.features.exams import batch_service as exam_batch_service
from app.features.error_book.service import get_error_book_by_subject
from app.features.error_book.dedup import normalize_question_stem


def test_parse_questions_from_top_level_array():
    """模型直接返回顶层 JSON 数组时能解析题目。"""
    raw = '```json\n[{"no":"43","answer":"C","score":null},{"no":"44","answer":"B","score":null}]\n```'

    questions = exam_batch_service._parse_questions_from_model_text(raw)

    assert [q.no for q in questions] == ["43", "44"]
    assert questions[0].answer == "C"


def test_parse_questions_from_reasoning_fragments():
    """模型把 JSON 草稿放进 reasoning 文本时能抽取单题片段。"""
    raw = (
        '先分析，结构是{"questions":[{"no":"题号","answer":"作答","score":"分数或null"}]}。'
        '最终应为 {"no":"43","answer":"C","score":null}, {"no":"44","answer":"B","score":null}'
    )

    questions = exam_batch_service._parse_questions_from_model_text(raw)

    assert [q.no for q in questions] == ["43", "44"]


def test_grade_and_save_errors_reuses_import_question(db: Session):
    """重复判同一错题导入批次时复用虚拟试卷和题目。"""
    batch = ExamBatch(
        student_id=2,
        subject="english",
        exam_name="重复判分测试",
        exam_date="2026-07-02",
        photo_material_ids=[],
        status="parsed",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    parsed = [ParsedQuestion(no="1", answer="A", score=None)]
    first = exam_batch_service.grade_and_save_errors(db, batch, parsed)
    second = exam_batch_service.grade_and_save_errors(db, batch, parsed)

    assert first["wrong_count"] == 1
    assert second["wrong_count"] == 1

    exam_title = "错题导入-重复判分测试-2026-07-02"
    exams = db.query(Exam).filter(Exam.title == exam_title).all()
    assert len(exams) == 1

    questions = db.query(Question).filter(Question.exam_id == exams[0].id).all()
    assert len(questions) == 1

    error = db.query(ErrorBook).filter(ErrorBook.student_id == 2, ErrorBook.question_id == questions[0].id).one()
    assert error.error_count == 2


def test_error_book_by_subject_deduplicates_same_stem(db: Session):
    """同一道题来自不同试卷时，错题本只展示一张卡并累加次数。"""
    exam_a = Exam(title="去重测试 A", subject="english", created_by=1, status="published")
    exam_b = Exam(title="去重测试 B", subject="english", created_by=1, status="published")
    db.add_all([exam_a, exam_b])
    db.flush()

    q1 = Question(
        exam_id=exam_a.id,
        type="fill_blank",
        stem="Unique dedupe stem 20260702 ___",
        answer_json={"answer": "went"},
        score=2,
        knowledge_tags=["过去时"],
    )
    q2 = Question(
        exam_id=exam_b.id,
        type="fill_blank",
        stem="Unique   dedupe stem 20260702 ___",
        answer_json={"answer": "went"},
        score=2,
        knowledge_tags=["过去时"],
    )
    db.add_all([q1, q2])
    db.flush()

    r1 = ExamRecord(exam_id=exam_a.id, student_id=2, status="graded")
    r2 = ExamRecord(exam_id=exam_b.id, student_id=2, status="graded")
    db.add_all([r1, r2])
    db.flush()

    db.add_all(
        [
            ErrorBook(student_id=2, question_id=q1.id, exam_record_id=r1.id, knowledge_tags=["过去时"], error_count=2),
            ErrorBook(student_id=2, question_id=q2.id, exam_record_id=r2.id, knowledge_tags=["过去时"], error_count=3),
        ]
    )
    db.commit()

    groups = get_error_book_by_subject(db, 2)
    english = next(g for g in groups if g.subject == "english")
    fill_blank = next(g for g in english.type_groups if g.question_type == "fill_blank")
    matches = [q for q in fill_blank.questions if normalize_question_stem(q.stem) == "unique dedupe stem 20260702 ___"]

    assert len(matches) == 1
    assert matches[0].error_count == 5
