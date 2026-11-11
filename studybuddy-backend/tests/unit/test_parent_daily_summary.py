from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.models.user import User
from app.models.teacher_student import TeacherStudent
from app.models.p2 import LearningFeedback, StudyPlan, StudyPlanItem
from app.models.note import Note
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.exam_assignment import ExamAssignment
from app.models.question import Question
from app.models.error_book import ErrorBook
from app.features.wechat.guardian import build_parent_daily_summary


def _family(db):
    guardian = User(username='daily_guardian', password_hash='synthetic', role='teacher')
    student = User(username='daily_student', display_name='日报同学', password_hash='synthetic', role='student')
    db.add_all([guardian, student]); db.flush()
    db.add(TeacherStudent(teacher_id=guardian.id, student_id=student.id)); db.flush()
    return guardian, student


def _exam(db, student, guardian, *, status='graded', score=Decimal('86')):
    exam = Exam(title='分数单元小测', subject='数学', created_by=guardian.id)
    db.add(exam); db.flush()
    record = ExamRecord(exam_id=exam.id, student_id=student.id, status=status, total_score=score, submitted_at=datetime.utcnow()-timedelta(days=1))
    db.add(record); db.flush()
    return exam, record


def test_daily_summary_includes_completed_duration_review_weakness_score_and_next_step(db):
    guardian, student = _family(db)
    now = datetime.utcnow()
    plan = StudyPlan(student_id=student.id, title='分数专项', created_by=student.id)
    db.add(plan); db.flush()
    for title in ['画图解释', '通分练习', '错题复盘']:
        db.add(StudyPlanItem(plan_id=plan.id, title=title, minutes=999, status='done', completed_at=now-timedelta(minutes=1)))
    db.add(StudyPlanItem(plan_id=plan.id, title='昨日已完成项目', status='done', completed_at=now-timedelta(days=2)))
    db.add(LearningFeedback(student_id=student.id, feedback_type='duration', content='学习了50分钟', created_at=now-timedelta(minutes=1)))
    db.add(Note(student_id=student.id, title='回顾', category='每日回顾', source='每日回顾', subject='数学', status='confirmed', content='## 需要督促的地方\n错题复盘：分母不能直接相加。'))
    exam, record = _exam(db, student, guardian)
    for tag in ['单位分数', '通分']:
        question = Question(exam_id=exam.id, type='math_answer', stem='分数相加', answer_json={}, score=Decimal('7'), knowledge_tags=[tag])
        db.add(question); db.flush()
        db.add(ErrorBook(student_id=student.id, question_id=question.id, exam_record_id=record.id, knowledge_tags=[tag], error_count=3))
    # A newer unrelated child's result must never appear in this guardian's reply.
    outsider = User(username='daily_outsider', role='student', password_hash='synthetic')
    db.add(outsider); db.flush()
    hidden_exam, _ = _exam(db, outsider, guardian)
    hidden_exam.title = '其他家庭私密试卷'
    db.flush()
    text = build_parent_daily_summary(db, guardian.id)
    for expected in ['画图解释', '通分练习', '错题复盘', '自报学习时长：50 分钟', '单位分数', '通分', '分母不能直接相加', '分数单元小测（86 分）', '明天建议：']:
        assert expected in text
    assert '999' not in text  # Planned time must not become actual learning duration.
    assert '昨日已完成项目' not in text
    assert '其他家庭私密试卷' not in text
    assert '。；' not in text


@pytest.mark.parametrize('status,score,expected', [('submitted', Decimal('86'), '待批改'), ('graded', None, '待批改'), ('graded', Decimal('0'), '0 分')])
def test_latest_exam_score_only_shown_when_graded(db, status, score, expected):
    guardian, student = _family(db)
    _exam(db, student, guardian, status=status, score=score)
    db.flush()
    text = build_parent_daily_summary(db, guardian.id)
    assert f'分数单元小测（{expected}）' in text


def test_daily_summary_empty_and_assignment_fallback(db):
    guardian, student = _family(db)
    text = build_parent_daily_summary(db, guardian.id)
    assert '今天还没有学习记录' in text
    assert '最近试卷：暂无记录' in text
    exam = Exam(title='待开始小测', subject='数学', created_by=guardian.id)
    db.add(exam); db.flush()
    db.add(ExamAssignment(exam_id=exam.id, student_id=student.id, assigned_by=guardian.id))
    db.flush()
    assert '待开始小测（assigned）' in build_parent_daily_summary(db, guardian.id)
    db.delete(db.query(TeacherStudent).filter_by(teacher_id=guardian.id).one()); db.flush()
    assert build_parent_daily_summary(db, guardian.id) == '当前没有已绑定学生'


@pytest.mark.parametrize('ending', ['。', '；', ';', '.', '！', '!', '？', '?', '。；  \n', ''])
def test_daily_summary_joins_suggestions_with_single_punctuation(db, monkeypatch, ending):
    from types import SimpleNamespace
    from app.features.wechat import guardian as guardian_service

    guardian, student = _family(db)
    summary = SimpleNamespace(
        student_name=student.display_name,
        reminders=[],
        weak_points=[
            SimpleNamespace(tag='单位分数', next_action=f'先复习 1.5 页，再做练习{ending}'),
            SimpleNamespace(tag='通分', next_action='回看例题，再解释为什么。'),
        ],
        support_items=[],
        recent_assignments=[],
    )
    monkeypatch.setattr(guardian_service.supervision_service, 'build_supervision_summary', lambda *_: summary)
    text = build_parent_daily_summary(db, guardian.id)

    suggestions = next(line for line in text.splitlines() if line.startswith('明天建议：'))
    assert suggestions == '明天建议：单位分数：先复习 1.5 页，再做练习；通分：回看例题，再解释为什么。'


def test_daily_summary_keeps_single_suggestion_as_a_sentence(db, monkeypatch):
    from types import SimpleNamespace
    from app.features.wechat import guardian as guardian_service

    guardian, student = _family(db)
    summary = SimpleNamespace(
        student_name=student.display_name,
        reminders=[],
        weak_points=[SimpleNamespace(tag='通分', next_action='先回看例题。')],
        support_items=[],
        recent_assignments=[],
    )
    monkeypatch.setattr(guardian_service.supervision_service, 'build_supervision_summary', lambda *_: summary)
    text = build_parent_daily_summary(db, guardian.id)
    assert text.splitlines()[-1] == '明天建议：通分：先回看例题。'
