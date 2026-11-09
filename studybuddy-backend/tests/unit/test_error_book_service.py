from app.models.answer import Answer
from app.models.error_book import ErrorBook
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.question import Question
from app.features.error_book.service import get_error_book_by_subject


def test_error_book_by_subject_returns_error_book_id(db):
    exam = Exam(title="错题复盘测试卷", subject="英语", created_by=1, status="published")
    db.add(exam)
    db.flush()
    question = Question(
        exam_id=exam.id,
        type="single_choice",
        stem="He ___ to school yesterday.",
        options=["go", "went"],
        answer_json={"answer": "went"},
        score=5,
        knowledge_tags=["一般过去时"],
    )
    db.add(question)
    db.flush()
    record = ExamRecord(exam_id=exam.id, student_id=2, status="graded")
    db.add(record)
    db.flush()
    db.add(Answer(exam_record_id=record.id, question_id=question.id, student_answer="go", is_correct=False))
    db.flush()
    error = ErrorBook(
        student_id=2,
        question_id=question.id,
        exam_record_id=record.id,
        knowledge_tags=["一般过去时"],
        error_count=2,
    )
    db.add(error)
    db.commit()

    groups = get_error_book_by_subject(db, 2)

    item = groups[0].type_groups[0].questions[0]
    assert item.error_id == error.id
    assert item.question_id == question.id
