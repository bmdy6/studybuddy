"""错题本与诊断聚合集成测试。

端到端：导入试卷 → 学生答错客观题 → 查错题本（按 tag 分组）→ 查诊断（weak/mastered）。
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.main import app
from app.models.answer import Answer
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.question import Question
from app.models.user import User
from app.utils.security import hash_password
from app.features.learning.diagnosis_service import get_diagnoses


@contextmanager
def _count_queries(db: Session) -> Iterator[Callable[[], int]]:
    """统计当前测试连接执行的 SQL 条数。"""
    count = 0
    connection = db.connection()

    def _increment(*_args: object) -> None:
        """记录一次 SQL 执行。"""
        nonlocal count
        count += 1

    event.listen(connection, "before_cursor_execute", _increment)
    try:
        yield lambda: count
    finally:
        event.remove(connection, "before_cursor_execute", _increment)


VALID_EXAM = {
    "schema_version": 1,
    "title": "U5 测验",
    "subject": "english",
    "feedback_mode": "after_submit",
    "shuffle_groups": False,
    "questions": [
        {
            "type": "single_choice",
            "stem": "He ___ to school.",
            "options": ["go", "goes", "went", "gone"],
            "answer": "went",
            "score": 2,
            "knowledge_tags": ["过去时", "动词"],
            "group_id": "grammar",
            "grading": {"rule_type": "auto_exact", "matcher": "exact", "match_params": {}},
        },
        {
            "type": "fill_blank",
            "stem": "She ___ (go) home.",
            "answer": "goes",
            "score": 2,
            "knowledge_tags": ["一般现在时"],
            "grading": {"rule_type": "auto_exact", "matcher": "exact", "match_params": {}},
        },
        {
            "type": "translation",
            "stem": "翻译：我去学校。",
            "answer": "I went to school.",
            "score": 5,
            "knowledge_tags": ["翻译"],
            "grading": {"rule_type": "manual"},
        },
    ],
}


def _teacher_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _student_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assign_exam_to_student(client: TestClient, exam_id: int, teacher_token: str, student_id: int = 2) -> None:
    r = client.post(
        f"/api/exam/{exam_id}/assignments",
        json={"student_ids": [student_id]},
        headers=_h(teacher_token),
    )
    assert r.status_code == 201, r.text


def _setup_and_submit_wrong(client: TestClient, db: Session) -> int:
    """导入、发布并分发试卷 → 学生 start → 答错第 1 题、答对第 2 题 → 返回 student_id。"""
    tt = _teacher_token(client)
    r = client.post("/api/exam/import", json=VALID_EXAM, headers=_h(tt))
    exam_id = r.json()["exam_id"]
    r = client.patch(f"/api/exam/{exam_id}/status", json={"status": "published"}, headers=_h(tt))
    assert r.status_code == 200, r.text
    _assign_exam_to_student(client, exam_id, tt)
    detail = client.get(f"/api/exam/{exam_id}", headers=_h(tt)).json()
    q_ids = [q["id"] for q in detail["questions"]]

    st = _student_token(client)
    r = client.post(f"/api/exam/{exam_id}/start", headers=_h(st))
    assert r.status_code == 201, r.text
    record_id = r.json()["exam_record_id"]

    # 门禁适配：模拟正常用时（60 秒前开始），避免被防敷衍门禁拦截
    from datetime import datetime, timedelta, timezone

    record = db.get(ExamRecord, record_id)
    record.started_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    db.commit()

    # 第 1 题答错（过去时/动词），第 2 题答对（一般现在时）
    client.post(
        f"/api/exam/{exam_id}/submit",
        json={
            "exam_record_id": record_id,
            "answers": [
                {"question_id": q_ids[0], "student_answer": "goed"},  # 错
                {"question_id": q_ids[1], "student_answer": "goes"},  # 对
            ],
        },
        headers=_h(st),
    )
    # student id = 2 (init_users)
    return 2


def test_error_book_grouped(client: TestClient, db: Session):
    """答错后错题本按 tag 分组，错误题出现在对应分组。"""
    _setup_and_submit_wrong(client, db)
    st = _student_token(client)

    r = client.get("/api/error-book", headers=_h(st))
    assert r.status_code == 200, r.text
    groups = r.json()
    tags = {g["tag"] for g in groups}
    assert "过去时" in tags
    assert "动词" in tags

    grammar_group = next(g for g in groups if g["tag"] == "过去时")
    assert grammar_group["error_count"] >= 1
    assert any(q["stem"] == "He ___ to school." for q in grammar_group["questions"])


def test_diagnosis_weak_points(client: TestClient, db: Session):
    """诊断接口返回 weak_points，且答错的 tag 出现在 weak。"""
    _setup_and_submit_wrong(client, db)
    tt = _teacher_token(client)

    r = client.get("/api/diagnosis/2?top_n=50", headers=_h(tt))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["student_id"] == 2
    assert "weak_points" in data
    assert "mastered_tags" in data
    assert "generated_at" in data

    weak_tags = {wp["tag"] for wp in data["weak_points"]}
    # 答错过去时，应在 weak
    assert "过去时" in weak_tags


def test_error_book_filter_by_tag(client: TestClient, db: Session):
    """按 tag 过滤错题本。"""
    _setup_and_submit_wrong(client, db)
    st = _student_token(client)

    r = client.get("/api/error-book?tag=%E8%BF%87%E5%8E%BB%E6%97%B6", headers=_h(st))
    assert r.status_code == 200, r.text
    groups = r.json()
    assert len(groups) == 1
    assert groups[0]["tag"] == "过去时"


def test_error_book_query_count_is_batched(client: TestClient, db: Session):
    """错题本查询批量预取题目和答案，避免按错题循环查库。"""
    _setup_and_submit_wrong(client, db)
    _setup_and_submit_wrong(client, db)
    st = _student_token(client)

    with _count_queries(db) as count:
        r = client.get("/api/error-book", headers=_h(st))

    assert r.status_code == 200, r.text
    assert count() <= 6


def test_error_book_by_subject(client: TestClient, db: Session):
    """错题本按学科→题型两级分组：学科取 exams.subject 原值，题型带中文标签。"""
    _setup_and_submit_wrong(client, db)
    st = _student_token(client)

    r = client.get("/api/error-book/by-subject", headers=_h(st))
    assert r.status_code == 200, r.text
    subjects = r.json()
    # VALID_EXAM subject=english，答错的题应归到 english 学科下
    eng = next(g for g in subjects if g["subject"] == "english")
    assert eng["total_count"] >= 1
    # single_choice 题型分组存在且带中文标签
    sc = next(tg for tg in eng["type_groups"] if tg["question_type"] == "single_choice")
    assert sc["type_label"] == "单选题"
    q = sc["questions"][0]
    assert q["stem"] == "He ___ to school."
    assert q["correct_answer"] == "went"  # _format_answer 去掉裸 JSON 包装
    assert "过去时" in q["knowledge_tags"]


def test_diagnosis_all_batched_matches_single(client: TestClient, db: Session):
    """批量诊断接口（老师查全部学生）结果与单查一致。"""
    _setup_and_submit_wrong(client, db)
    tt = _teacher_token(client)

    single = client.get("/api/diagnosis/2?top_n=50", headers=_h(tt)).json()
    batch = client.get("/api/diagnosis?top_n=50", headers=_h(tt)).json()
    assert isinstance(batch, list)
    assert any(d["student_id"] == 2 for d in batch)
    batch_for_2 = next(d for d in batch if d["student_id"] == 2)
    assert batch_for_2["weak_points"] == single["weak_points"]
    assert batch_for_2["mastered_tags"] == single["mastered_tags"]
    assert {wp["tag"] for wp in batch_for_2["weak_points"]} == {"过去时", "动词"}


def test_diagnosis_all_query_count_is_fixed(client: TestClient, db: Session):
    """批量诊断查询次数固定（不随学生数线性放大）。"""
    _setup_and_submit_wrong(client, db)
    tt = _teacher_token(client)

    with _count_queries(db) as count:
        r = client.get("/api/diagnosis?top_n=50", headers=_h(tt))

    assert r.status_code == 200, r.text
    # 学生列表 + 学生批拉 + answers 批拉 + exam_records 批拉 ≈ 固定几次，远小于单查 2×N
    assert count() <= 8


def test_get_diagnoses_batch_query_count_is_fixed(db: Session):
    """服务层批拉：多学生时查询次数固定，不随学生数线性放大（防 N+1 回归）。"""
    teacher = db.query(User).filter(User.username == "teacher").first()
    assert teacher is not None

    # 造 4 个学生（1 个已有 + 3 个新建），各配 1 道题 1 条作答
    students = [db.get(User, 2)]
    for i in range(3):
        s = User(
            username=f"n1_student_{i}",
            password_hash=hash_password("student123"),
            role="student",
            display_name=f"N1学生{i}",
        )
        db.add(s)
        db.flush()
        students.append(s)
    exam = db.query(Exam).first()
    if exam is None:
        exam = Exam(
            title="N1 测试卷",
            subject="math",
            feedback_mode="after_submit",
            status="published",
            created_by=teacher.id,
        )
        db.add(exam)
        db.flush()
    questions = []
    for i, s in enumerate(students):
        q = Question(
            exam_id=exam.id,
            type="single_choice",
            stem=f"N1 题目 {i}",
            options=["A", "B"],
            answer_json={"answer": "A"},
            score=2,
            knowledge_tags=[f"标签{i}"],
        )
        db.add(q)
        db.flush()
        questions.append(q)
        rec = ExamRecord(exam_id=exam.id, student_id=s.id, status="graded")
        db.add(rec)
        db.flush()
        db.add(Answer(exam_record_id=rec.id, question_id=q.id, student_answer="A", is_correct=1))
    db.commit()

    student_ids = [s.id for s in students]
    with _count_queries(db) as count:
        results = get_diagnoses(db, student_ids, top_n=50)

    assert len(results) == len(students)
    # 学生批拉(1) + answers/exam_records/questions join 批拉(1) ≈ 固定 2-3 次；旧实现 2×N 会 ≥10
    assert count() <= 6
    # 每个学生的标签独立：学生 i 只含 标签i
    for i, r in enumerate(results):
        assert r.student_name == (students[i].display_name or students[i].username)
        tags = [wp["tag"] for wp in r.weak_points] + r.mastered_tags
        assert f"标签{i}" in tags
        for j in range(len(students)):
            if j != i:
                assert f"标签{j}" not in tags
