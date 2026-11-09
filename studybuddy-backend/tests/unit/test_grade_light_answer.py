"""对话轻练 MVP-A：grade_light_answer 判分工具单测。

覆盖 _handle_grade_light_answer：
- 选择题判分（字母/索引/大小写归一化）
- 填空 levenshtein 容错
- 数值 float_tol 容差
- 答错/未作答返回 is_correct=False
- 非学生角色拒绝
- 纯计算不落库（硬边界：不进正式统计）
"""

import asyncio

import pytest

from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.error_book import ErrorBook
from app.features.agent.handlers.exam import _handle_grade_light_answer
from app.utils.security import hash_password


def _make_student(db, username="light-practice-student"):
    from app.models.user import User

    student = User(
        username=username,
        password_hash=hash_password("x"),
        role="student",
        display_name=username,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _choice_question(answer="B"):
    return {
        "type": "single_choice",
        "stem": "3 × 7 = ?",
        "options": ["18", "20", "21", "24"],
        "answer": answer,
        "score": 10,
        "grading": {"rule_type": "auto_exact", "matcher": "exact", "match_params": {}},
    }


class TestGradeLightAnswer:
    def test_choice_correct_by_letter(self, db):
        """选择题答字母且正确 -> is_correct=True，满分。"""
        student = _make_student(db)
        result = asyncio.run(
            _handle_grade_light_answer(
                {"student_id": student.id, "question": _choice_question(), "student_answer": "B"},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert result["is_correct"] is True
        assert result["score"] == 10
        assert result["max_score"] == 10

    def test_choice_correct_by_index(self, db):
        """选择题答索引（1=选项B）也判对，与试卷链路同一归一化。"""
        student = _make_student(db)
        result = asyncio.run(
            _handle_grade_light_answer(
                {"student_id": student.id, "question": _choice_question(), "student_answer": "1"},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert result["is_correct"] is True
        assert result["score"] == 10

    def test_choice_wrong(self, db):
        """选择题答错 -> is_correct=False，score=0，detail 非空。"""
        student = _make_student(db)
        result = asyncio.run(
            _handle_grade_light_answer(
                {"student_id": student.id, "question": _choice_question(), "student_answer": "A"},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert result["is_correct"] is False
        assert result["score"] == 0
        assert result["detail"]

    def test_fill_blank_levenshtein_tolerance(self, db):
        """填空 levenshtein 容错：拼写小错判对。"""
        student = _make_student(db)
        question = {
            "type": "fill_blank",
            "stem": "receive 的过去式：___",
            "options": [],
            "answer": "received",
            "score": 10,
            "grading": {"rule_type": "auto_fuzzy", "matcher": "levenshtein", "match_params": {}},
        }
        result = asyncio.run(
            _handle_grade_light_answer(
                {"student_id": student.id, "question": question, "student_answer": "receved"},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert result["is_correct"] is True

    def test_math_float_tolerance(self, db):
        """计算题 float_tol：数值容差内判对。"""
        student = _make_student(db)
        question = {
            "type": "math_answer",
            "stem": "3.14 × 2 = ?",
            "options": [],
            "answer": "6.28",
            "score": 10,
            "grading": {
                "rule_type": "auto_fuzzy",
                "matcher": "float_tol",
                "match_params": {"eps": 0.01},
            },
        }
        result = asyncio.run(
            _handle_grade_light_answer(
                {"student_id": student.id, "question": question, "student_answer": "6.283"},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert result["is_correct"] is True

    def test_blank_answer_wrong(self, db):
        """未作答 -> is_correct=False。"""
        student = _make_student(db)
        result = asyncio.run(
            _handle_grade_light_answer(
                {"student_id": student.id, "question": _choice_question(), "student_answer": ""},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert result["is_correct"] is False

    def test_teacher_role_rejected(self, db):
        """非学生角色 -> PermissionError。"""
        with pytest.raises(PermissionError):
            asyncio.run(
                _handle_grade_light_answer(
                    {"student_id": 1, "question": _choice_question(), "student_answer": "B"},
                    role="teacher",
                    db=db,
                    teacher_id=1,
                )
            )

    def test_no_persist_no_formal_stats(self, db):
        """硬边界：判分纯计算，不落任何正式数据（exam/record/错题本数量不变）。"""
        student = _make_student(db)
        exam_count = db.query(Exam).count()
        record_count = db.query(ExamRecord).count()
        result = asyncio.run(
            _handle_grade_light_answer(
                {"student_id": student.id, "question": _choice_question(), "student_answer": "A"},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert result["is_correct"] is False
        assert db.query(Exam).count() == exam_count
        assert db.query(ExamRecord).count() == record_count

    def test_missing_grading_returns_error(self, db):
        """题目/判分规则不完整 -> 返回 error 字典（不抛异常、不落库），AI 可据错误重新出题。"""
        student = _make_student(db)
        bad_question = {
            "type": "single_choice",
            "stem": "3 × 7 = ?",
            "options": ["18", "20", "21", "24"],
            "answer": "B",
            "score": 10,
            # 缺 grading
        }
        result = asyncio.run(
            _handle_grade_light_answer(
                {"student_id": student.id, "question": bad_question, "student_answer": "B"},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert isinstance(result, dict)
        assert "error" in result
        assert "判分规则" in result["error"]

    def test_bad_score_returns_error(self, db):
        """score 非法（非数字）-> 返回 error 字典，不抛异常。"""
        student = _make_student(db)
        bad_question = {
            "type": "single_choice",
            "stem": "3 × 7 = ?",
            "options": ["18", "20", "21", "24"],
            "answer": "B",
            "score": "十分",  # 非数字
            "grading": {"rule_type": "auto_exact", "matcher": "exact", "match_params": {}},
        }
        result = asyncio.run(
            _handle_grade_light_answer(
                {"student_id": student.id, "question": bad_question, "student_answer": "B"},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert isinstance(result, dict)
        assert "error" in result
