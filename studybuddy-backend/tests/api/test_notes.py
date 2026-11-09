"""笔记模块集成测试。

覆盖：
- CRUD 接口 + 权限（student 可读写自己的，parent 只读）
- 盲区聚合接口可达性
- 关联错题接口可达性
- note_service 核心逻辑：get_related_errors 按 tag 匹配、get_blind_spots 聚合
"""

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.features.agent import agent_loop
from app.models.error_book import ErrorBook
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.note import Note
from app.models.question import Question
from app.features.note import service as note_service


def _seed_error_book(db, student_id: int = 2, tag: str | None = None) -> str:
    """为测试显式造一条错题盲区，不依赖开发库历史数据。"""
    tag = tag or f"测试盲区-{uuid4().hex[:8]}"
    exam = Exam(title=f"笔记关联测试-{uuid4().hex[:8]}", subject="english", created_by=1, status="published")
    db.add(exam)
    db.flush()
    question = Question(
        exam_id=exam.id,
        type="fill_blank",
        stem=f"{tag} 相关错题",
        answer_json={"answer": "A"},
        score=1,
        knowledge_tags=[tag],
    )
    db.add(question)
    db.flush()
    record = ExamRecord(exam_id=exam.id, student_id=student_id, status="graded")
    db.add(record)
    db.flush()
    db.add(
        ErrorBook(
            student_id=student_id,
            question_id=question.id,
            exam_record_id=record.id,
            knowledge_tags=[tag],
            error_count=2,
        )
    )
    db.commit()
    return tag


def _first_blind_spot_tag(db) -> str:
    _seed_error_book(db)
    blind_spots = note_service.get_blind_spots(db, 2)
    assert blind_spots, "student_id=2 应至少有一个测试错题盲区"
    return blind_spots[0].tag


def _teacher_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _student_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestNoteCRUDAPI:
    """笔记 CRUD 接口 + 权限。"""

    def test_student_create_note(self, client):
        """student 创建自己的笔记 → 201，默认 draft。

        student_id 必填（schema 校验），student 传自己的 id；后端 role 校验会
        把非 teacher 的 student_id 强制落回自己，防越权。
        """
        token = _student_token(client)
        r = client.post(
            "/api/notes",
            json={
                "student_id": 2,
                "title": "过去时学习记录",
                "subject": "english",
                "category": "语法",
                "content": "我学到了...",
                "knowledge_tags": ["过去时", "动词"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["title"] == "过去时学习记录"
        assert body["status"] == "draft"
        assert body["category"] == "语法"
        assert body["knowledge_tags"] == ["过去时", "动词"]

    def test_student_create_confirmed_daily_review_note(self, client):
        """student 手写每日回顾可以直接保存为 confirmed。"""
        token = _student_token(client)
        r = client.post(
            "/api/notes",
            json={
                "student_id": 2,
                "title": "2026.7.4 每日回顾",
                "subject": "其他",
                "category": "每日回顾",
                "content": "## 2026.7.4 总结\n\n今天背了单词。\n\n## 2026.7.5 目标\n\n明天继续英语。",
                "knowledge_tags": ["每日回顾", "目标"],
                "source": "每日回顾",
                "status": "confirmed",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["title"] == "2026.7.4 每日回顾"
        assert body["category"] == "每日回顾"
        assert body["status"] == "confirmed"

    def test_student_list_own_notes(self, client):
        """student 列笔记只看自己的。"""
        token = _student_token(client)
        client.post("/api/notes", json={"student_id": 2, "title": "n1", "subject": "english"}, headers={"Authorization": f"Bearer {token}"})
        r = client.get("/api/notes", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_parent_list_student_notes(self, client):
        """parent 指定 student_id 看弟弟笔记。"""
        token = _teacher_token(client)
        r = client.get("/api/notes?student_id=2", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_parent_cannot_create_for_other(self, client):
        """parent 可以给指定 student 建（agent 场景），student 不能给别人建。"""
        # student 传 student_id=999 应被忽略，落到自己 id
        token = _student_token(client)
        r = client.post(
            "/api/notes",
            json={
                "student_id": 999,
                "title": "越权测试",
                "subject": "english",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 201
        assert r.json()["student_id"] == 2  # 落回自己，不是 999

    def test_parent_cannot_update(self, client):
        """parent 只读，PATCH → 403。"""
        stu_token = _student_token(client)
        nid = client.post(
            "/api/notes", json={"student_id": 2, "title": "t", "subject": "english"}, headers={"Authorization": f"Bearer {stu_token}"}
        ).json()["id"]
        parent_token = _teacher_token(client)
        r = client.patch(f"/api/notes/{nid}", json={"title": "改了"}, headers={"Authorization": f"Bearer {parent_token}"})
        assert r.status_code == 403

    def test_parent_cannot_delete(self, client):
        """parent 只读，DELETE → 403。"""
        stu_token = _student_token(client)
        nid = client.post(
            "/api/notes", json={"student_id": 2, "title": "t", "subject": "english"}, headers={"Authorization": f"Bearer {stu_token}"}
        ).json()["id"]
        parent_token = _teacher_token(client)
        r = client.delete(f"/api/notes/{nid}", headers={"Authorization": f"Bearer {parent_token}"})
        assert r.status_code == 403

    def test_student_update_and_confirm(self, client):
        """student 改笔记 + 确认（draft→confirmed）。"""
        token = _student_token(client)
        nid = client.post(
            "/api/notes", json={"student_id": 2, "title": "草稿", "subject": "english"}, headers={"Authorization": f"Bearer {token}"}
        ).json()["id"]
        r = client.patch(f"/api/notes/{nid}", json={"status": "confirmed", "content": "确认内容"}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"
        assert r.json()["content"] == "确认内容"

    def test_get_note_not_found(self, client):
        token = _student_token(client)
        r = client.get("/api/notes/99999", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404

    def test_student_delete_own(self, client):
        """student 删自己的笔记 → 204。"""
        token = _student_token(client)
        nid = client.post(
            "/api/notes", json={"student_id": 2, "title": "待删", "subject": "english"}, headers={"Authorization": f"Bearer {token}"}
        ).json()["id"]
        r = client.delete(f"/api/notes/{nid}", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 204
        assert client.get(f"/api/notes/{nid}", headers={"Authorization": f"Bearer {token}"}).status_code == 404


class TestBlindSpotsAPI:
    """盲区聚合接口。"""

    def test_blind_spots_returns_list(self, client, db):
        """parent 查 student_id=2 盲区 → list。"""
        seeded_tag = _seed_error_book(db)
        token = _teacher_token(client)
        r = client.get("/api/notes/blind-spots?student_id=2", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        tags = [b["tag"] for b in data]
        assert seeded_tag in tags

    def test_blind_spots_sorted_by_error_count(self, client):
        """盲区按 error_count 倒序。"""
        token = _teacher_token(client)
        data = client.get("/api/notes/blind-spots?student_id=2", headers={"Authorization": f"Bearer {token}"}).json()
        counts = [b["error_count"] for b in data]
        assert counts == sorted(counts, reverse=True)

    def test_blind_spots_has_note_count(self, client):
        """盲区项含 note_count 字段（关联笔记数）。"""
        token = _teacher_token(client)
        data = client.get("/api/notes/blind-spots?student_id=2", headers={"Authorization": f"Bearer {token}"}).json()
        for b in data:
            assert "note_count" in b
            assert isinstance(b["note_count"], int)


class TestRelatedErrorsAPI:
    """关联错题接口。"""

    def test_related_errors_for_tagged_note(self, client, db):
        """笔记带真实盲区 tag → 关联错题接口返回匹配的错题。"""
        tag = _seed_error_book(db)
        token = _student_token(client)
        nid = client.post(
            "/api/notes",
            json={
                "student_id": 2,
                "title": f"{tag}笔记",
                "subject": "english",
                "knowledge_tags": [tag],
            },
            headers={"Authorization": f"Bearer {token}"},
        ).json()["id"]
        r = client.get(f"/api/notes/{nid}/related-errors", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "stem" in data[0]
        assert "error_count" in data[0]

    def test_related_errors_empty_for_no_tag(self, client):
        """笔记无 tag → 关联错题返回空。"""
        token = _student_token(client)
        nid = client.post(
            "/api/notes",
            json={
                "student_id": 2,
                "title": "无标签笔记",
                "subject": "english",
            },
            headers={"Authorization": f"Bearer {token}"},
        ).json()["id"]
        r = client.get(f"/api/notes/{nid}/related-errors", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == []

    def test_related_errors_not_found(self, client):
        token = _student_token(client)
        r = client.get("/api/notes/99999/related-errors", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404


class TestNoteServiceLogic:
    """note_service 核心逻辑（直接调 service，用 db fixture 造数据）。

    复用开发库 student_id=2 的 ErrorBook 种子（只读），造 Note 测匹配逻辑。
    """

    def test_get_related_errors_matches_by_tag(self, db):
        """笔记 tag 与错题 tag 有交集 → 返回关联错题。"""
        tag = _first_blind_spot_tag(db)
        note = Note(
            student_id=2,
            type="study_record",
            title=tag,
            subject="english",
            content="",
            knowledge_tags=[tag],
            source="其他",
            status="draft",
        )
        db.add(note)
        db.flush()  # 拿 id，不 commit（事务回滚兜底）
        related = note_service.get_related_errors(db, note)
        assert len(related) > 0
        # 每条都有 error_id / question_id / stem
        for r in related:
            assert "error_id" in r and "question_id" in r and "stem" in r

    def test_get_related_errors_dedup_question(self, db):
        """同一 question 多条错题记录 → 去重只返一次。"""
        note = Note(
            student_id=2,
            type="study_record",
            title="动词",
            subject="english",
            content="",
            knowledge_tags=["动词"],
            source="其他",
            status="draft",
        )
        db.add(note)
        db.flush()
        related = note_service.get_related_errors(db, note)
        qids = [r["question_id"] for r in related]
        assert len(qids) == len(set(qids)), "关联错题未按 question_id 去重"

    def test_get_related_errors_respects_limit(self, db):
        """limit 参数限制返回条数。"""
        note = Note(
            student_id=2,
            type="study_record",
            title="过去时",
            subject="english",
            content="",
            knowledge_tags=["过去时"],
            source="其他",
            status="draft",
        )
        db.add(note)
        db.flush()
        related = note_service.get_related_errors(db, note, limit=1)
        assert len(related) <= 1

    def test_get_blind_spots_filters_min_errors(self, db):
        """min_errors 阈值过滤：调高阈值，盲区数应不增。"""
        low = note_service.get_blind_spots(db, 2, min_errors=1)
        high = note_service.get_blind_spots(db, 2, min_errors=5)
        assert len(high) <= len(low)
        for b in high:
            assert b.error_count >= 5

    def test_get_blind_spots_note_count_links_notes(self, db):
        """盲区的 note_count 反映该 tag 有多少笔记。"""
        # 造一篇带「过去时」的笔记，note_count 应 +1
        before = note_service.get_blind_spots(db, 2)
        before_map = {b.tag: b.note_count for b in before}
        db.add(
            Note(
                student_id=2,
                type="study_record",
                title="t",
                subject="english",
                content="",
                knowledge_tags=["过去时"],
                source="其他",
                status="draft",
            )
        )
        db.flush()
        after = note_service.get_blind_spots(db, 2)
        after_map = {b.tag: b.note_count for b in after}
        if "过去时" in before_map:
            assert after_map["过去时"] == before_map["过去时"] + 1

    def test_create_note_defaults(self, db):
        """create_note 默认值：type=study_record、status=draft、空字段兜底。"""
        item = note_service.create_note(
            db,
            {
                "student_id": 2,
                "title": "默认值测试",
            },
        )
        assert item.type == "study_record"
        assert item.status == "draft"
        assert item.subject == "其他"
        assert item.knowledge_tags == []
        assert item.source_ref == []

    def test_create_note_persists_source_ref(self, db):
        """create_note 透传 source_ref（错题id列表），用于笔记关联错题闭环。

        agent 讲错题时调 save_note 带 source_ref=[错题id]，落库后笔记详情页
        可据此展示关联错题。这是错题导入→讲解→笔记关联闭环的关键字段。
        """
        item = note_service.create_note(
            db,
            {
                "student_id": 2,
                "title": "过去时笔记",
                "source": "错题讲解",
                "source_ref": [101, 102],
            },
        )
        assert item.source_ref == [101, 102]
        # 回读确认落库
        fresh = note_service.get_note(db, item.id)
        assert fresh.source_ref == [101, 102]
        assert fresh.source == "错题讲解"


class TestSaveNoteHandler:
    """save_note agent 工具 handler：验证 agent 调用时 source_ref 透传落库。

    这是错题导入→讲解→笔记关联闭环的 agent 链路（之前 handler 未透传 source_ref，
    导致 agent 讲错题记的笔记无法关联错题，闭环断裂）。
    """

    def test_handler_passes_source_ref_to_note(self, db):
        """agent 带 source_ref 调 save_note → 笔记落库 source_ref 不为空。"""
        result = asyncio.run(
            agent_loop._handle_save_note(
                {
                    "student_id": 2,
                    "title": "过去时讲解笔记",
                    "subject": "english",
                    "category": "语法",
                    "content": "## 我学到了\n过去时...",
                    "knowledge_tags": ["过去时"],
                    "source": "错题讲解",
                    "source_ref": [201, 202],  # 关联的错题id
                },
                role="teacher",
                db=db,
                teacher_id=1,
            )
        )
        assert result["saved"] is True
        # 回读笔记，source_ref 应已落库
        note = note_service.get_note(db, result["id"])
        assert note.source_ref == [201, 202]
        assert note.source == "错题讲解"

    def test_handler_defaults_source_ref_empty(self, db):
        """agent 不带 source_ref 调 save_note（如视频学习来源）→ source_ref 默认空。"""
        result = asyncio.run(
            agent_loop._handle_save_note(
                {
                    "student_id": 2,
                    "title": "视频学习笔记",
                    "subject": "english",
                    "content": "看视频学到...",
                    "source": "视频学习",
                },
                role="teacher",
                db=db,
                teacher_id=1,
            )
        )
        assert result["saved"] is True
        note = note_service.get_note(db, result["id"])
        assert note.source_ref == []

    def test_student_handler_uses_own_id(self, db):
        """student 角色调 save_note → student_id 落回自己（teacher_id 参数即学生id）。"""
        result = asyncio.run(
            agent_loop._handle_save_note(
                {"student_id": 999, "title": "我的笔记", "content": "x"},  # 传别人的 id
                role="student",
                db=db,
                teacher_id=2,  # student 时 teacher_id 实为本人 id
            )
        )
        note = note_service.get_note(db, result["id"])
        assert note.student_id == 2  # 落回自己，不是 999

    def test_handler_returns_draft_note_for_review(self, db):
        """save_note 落草稿并返回完整草案字段，供对话里草案卡渲染。

        确认前是 draft（待确认），不进 agent 记忆和每日记录；学生在对话点确认后才转 confirmed。
        """
        result = asyncio.run(
            agent_loop._handle_save_note(
                {
                    "student_id": 2,
                    "title": "一般过去时",
                    "subject": "english",
                    "category": "语法",
                    "content": "## 我学到了\n一般过去时表示过去发生的动作...",
                    "knowledge_tags": ["过去时", "不规则动词"],
                    "source": "素材整理",
                },
                role="teacher",
                db=db,
                teacher_id=1,
            )
        )
        # 草案卡渲染需要的字段全部返回
        assert result["saved"] is True
        assert result["id"]
        assert result["title"] == "一般过去时"
        assert result["subject"] == "english"
        assert result["category"] == "语法"
        assert result["content"] == "## 我学到了\n一般过去时表示过去发生的动作..."
        assert result["knowledge_tags"] == ["过去时", "不规则动词"]
        assert result["status"] == "draft"  # 待确认
        # 回读确认落库为 draft（未确认）
        note = note_service.get_note(db, result["id"])
        assert note.status == "draft"

    def test_handler_category_defaults_when_missing(self, db):
        """agent 没传 category -> 兜底"未分类"，不落空（笔记列表不出现空分类）。"""
        result = asyncio.run(
            agent_loop._handle_save_note(
                {
                    "student_id": 2,
                    "title": "无分类笔记",
                    "subject": "english",
                    "content": "内容...",
                },
                role="teacher",
                db=db,
                teacher_id=1,
            )
        )
        assert result["category"] == "未分类"
        note = note_service.get_note(db, result["id"])
        assert note.category == "未分类"


class TestQueryNotesHandler:
    """query_notes 只返回 confirmed 真实笔记，draft（待确认）不进 AI 查询/记忆。"""

    def test_query_notes_excludes_draft(self, db):
        note_service.create_note(
            db,
            {
                "student_id": 2,
                "title": "已确认笔记",
                "subject": "english",
                "content": "一般过去时",
                "status": "confirmed",
            },
        )
        note_service.create_note(
            db,
            {
                "student_id": 2,
                "title": "待确认草稿",
                "subject": "english",
                "content": "草稿内容",
                "status": "draft",
            },
        )
        result = asyncio.run(
            agent_loop._handle_query_notes({"student_id": 2}, role="teacher", db=db, teacher_id=1)
        )
        titles = [n["title"] for n in result["notes"]]
        assert "已确认笔记" in titles
        assert "待确认草稿" not in titles


class TestConfirmAllDraftNotes:
    """历史 draft 笔记一次性转 confirmed（以前没对话确认环节，存量 draft 实为已认可）。"""

    def test_confirm_all_draft_notes_migrates_only_drafts(self, db):
        # 测试库可能已有历史 draft/confirmed（开发数据），用相对数断言，不假设干净库
        draft_before = db.query(Note).filter(Note.status == "draft").count()
        a = note_service.create_note(
            db,
            {"student_id": 2, "title": "历史草稿A", "subject": "english", "content": "c", "status": "draft"},
        )
        b = note_service.create_note(
            db,
            {"student_id": 2, "title": "历史草稿B", "subject": "english", "content": "c", "status": "draft"},
        )
        note_service.create_note(
            db,
            {"student_id": 2, "title": "已确认", "subject": "english", "content": "c", "status": "confirmed"},
        )

        count = note_service.confirm_all_draft_notes(db)

        assert count == draft_before + 2  # 含本测试造的 2 条 draft
        assert db.query(Note).filter(Note.status == "draft").count() == 0  # 全部转 confirmed
        assert note_service.get_note(db, a.id).status == "confirmed"
        assert note_service.get_note(db, b.id).status == "confirmed"
