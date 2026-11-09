"""拍题批改服务单测。"""

from sqlalchemy.orm import Session

from app.models.error_book import ErrorBook
from app.models.exam_batch import ExamBatch
from app.models.question import Question
from app.features.exams.photo_grading_service import (
    normalize_photo_grading_result,
    normalize_photo_markdown_result,
    save_confirmed_homework_errors,
)


def test_normalize_photo_grading_result_parses_question_feedback():
    raw = """
    {"subject":"物理","questions":[{"no":"1","stem":"刻度尺读数","student_answer":"2.6cm","correct_answer":"2.60cm","is_correct":false,"error_point":"少估读一位","knowledge_tags":["物理","刻度尺读数"],"explanation":"刻度尺要估读到分度值下一位。","confidence":"high","needs_review":false}]}
    """

    result = normalize_photo_grading_result(raw)

    assert result.subject == "物理"
    assert result.questions[0].no == "1"
    assert result.questions[0].stem == "刻度尺读数"
    assert result.questions[0].student_answer == "2.6cm"
    assert result.questions[0].correct_answer == "2.60cm"
    assert result.questions[0].is_correct is False
    assert result.questions[0].error_point == "少估读一位"
    assert result.questions[0].knowledge_tags == ["物理", "刻度尺读数"]
    assert result.questions[0].explanation == "刻度尺要估读到分度值下一位。"
    assert result.questions[0].confidence == "high"
    assert result.questions[0].needs_review is False


def test_normalize_photo_markdown_result_keeps_markdown_and_uncertain_points():
    raw = """
    ```markdown
    ### 知识点3 误差和错误

    【学以致用2】木尺受潮后测量物体长度。

    学生作答：偏大 / 误差 / 不能

    **识别置信度**：85%
    **需要人工确认的内容**：第三空是否为“不能”
    **适合作为哪类学习素材**：初中物理易错点
    ```
    """

    result = normalize_photo_markdown_result(raw)

    assert "误差和错误" in result.markdown
    assert "学生作答：偏大 / 误差 / 不能" in result.markdown
    assert result.confidence == "medium"
    assert result.uncertain_points == ["第三空是否为“不能”"]
    assert result.content_type == "初中物理易错点"
    assert result.raw_text == raw
    assert result.provider == "mimo"
    assert result.elapsed_ms == 0
    assert result.warnings == []


def test_normalize_photo_markdown_result_parses_approx_confidence_and_bullets():
    raw = """
    ### 机械秒表读数

    1. **识别置信度**：约85%（核心知识点清晰）。
    2. **需要人工确认的内容**：
       - 机械秒表读数：小表盘指针是否超过3.5min；
       - 刻度尺读数：右端刻度线是否对齐2.35cm。
    3. **适合作为哪类学习素材**：初中物理（测量章节）的习题讲解、错题集
    """

    result = normalize_photo_markdown_result(raw)

    assert result.confidence == "medium"
    assert result.uncertain_points == [
        "机械秒表读数：小表盘指针是否超过3.5min",
        "刻度尺读数：右端刻度线是否对齐2.35cm。",
    ]
    assert result.content_type == "初中物理（测量章节）的习题讲解"


def test_normalize_photo_markdown_result_does_not_treat_content_type_as_uncertain_point():
    raw = """
    ### 机械秒表读数

    **识别置信度**：低
    **需要人工确认的内容**：适合初中物理“机械秒表使用”与“误差与错误”的课堂练习或自主学习素材。
    **适合作为哪类学习素材**：适合初中物理“机械秒表使用”与“误差与错误”的课堂练习或自主学习素材。
    """

    result = normalize_photo_markdown_result(raw)

    assert result.confidence == "low"
    assert result.uncertain_points == []
    assert "初中物理" in result.content_type


def test_normalize_photo_markdown_result_adds_answer_review_section_for_unclear_answers():
    raw = """
    ### 学以致用 1

    (1) 刻度尺的分度值为 [?] cm，所测物体长度是 [?] cm。

    学生作答：[?]

    (2) 机械秒表显示的时间是 [?] min [?] s。

    学生作答：1 min 25.5 s

    **识别置信度**：中
    **适合作为哪类学习素材**：初中物理测量练习
    """

    result = normalize_photo_markdown_result(raw)

    assert "## 学生作答核对" in result.markdown
    assert "第1题：学生作答需要确认" in result.markdown
    assert "第1题：学生作答需要确认" in result.uncertain_points
    assert "第2题：学生作答已识别为 1 min 25.5 s" in result.markdown


def test_normalize_photo_grading_result_marks_missing_correct_answer_for_review():
    raw = '{"questions":[{"no":"2","student_answer":"A","confidence":"medium"}]}'

    result = normalize_photo_grading_result(raw)

    assert result.questions[0].correct_answer == ""
    assert result.questions[0].needs_review is True


def test_save_confirmed_homework_errors_reuses_question_and_increments_count(db: Session):
    batch = ExamBatch(
        student_id=2,
        subject="physics",
        exam_name="拍题批改测试",
        exam_date="2026-07-05",
        photo_material_ids=[],
        status="parsed",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    result = normalize_photo_grading_result(
        """
        {"questions":[{"no":"1","stem":"刻度尺读数","student_answer":"2.6cm","correct_answer":"2.60cm","is_correct":false,"error_point":"少估读一位","knowledge_tags":["物理","刻度尺读数"],"explanation":"刻度尺要估读到分度值下一位。","confidence":"high","needs_review":false}]}
        """
    )

    first = save_confirmed_homework_errors(db, batch, result.questions)
    second = save_confirmed_homework_errors(db, batch, result.questions)

    assert first["saved_count"] == 1
    assert second["saved_count"] == 1
    questions = db.query(Question).filter(Question.stem == "第1题：刻度尺读数").all()
    assert len(questions) == 1
    error = db.query(ErrorBook).filter(ErrorBook.student_id == 2, ErrorBook.question_id == questions[0].id).one()
    assert error.error_count == 2


def test_save_confirmed_homework_errors_uses_detected_subject_when_batch_is_auto(db: Session):
    """批次 subject 为 auto 时，错题入库应使用 AI 识别出的学科。"""
    batch = ExamBatch(
        student_id=2,
        subject="auto",
        exam_name="拍题批改测试",
        exam_date="2026-07-05",
        photo_material_ids=[],
        status="parsed",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    result = normalize_photo_grading_result(
        """
        {"subject":"物理","questions":[{"no":"1","stem":"刻度尺读数","student_answer":"2.6cm","correct_answer":"2.60cm","is_correct":false,"error_point":"少估读一位","knowledge_tags":["刻度尺读数"],"explanation":"刻度尺要估读到分度值下一位。","confidence":"high","needs_review":false}]}
        """
    )

    saved = save_confirmed_homework_errors(db, batch, result.questions, subject=result.subject)

    assert saved["saved_count"] == 1
    question = db.query(Question).filter(Question.stem == "第1题：刻度尺读数").one()
    assert question.knowledge_tags == ["物理", "刻度尺读数"]
