from fastapi.testclient import TestClient

_TEXT_PDF = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj
4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
5 0 obj << /Length 96 >> stream
BT /F1 12 Tf 72 720 Td (1. He ___ to school. A. go B. went Answer: B 2. Calculate 2 plus 3. Answer: 5) Tj ET
endstream endobj
xref
0 6
0000000000 65535 f\x20
0000000009 00000 n\x20
0000000058 00000 n\x20
0000000115 00000 n\x20
0000000241 00000 n\x20
0000000311 00000 n\x20
trailer << /Root 1 0 R /Size 6 >>
startxref
456
%%EOF"""


def _teacher_token(client: TestClient) -> str:
    return client.post("/auth/login", json={"username": "teacher", "password": "teacher123"}).json()["access_token"]


def _student_token(client: TestClient) -> str:
    return client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]


def test_search_paper_sources_requires_teacher(client: TestClient):
    token = _student_token(client)
    r = client.post(
        "/api/question-bank/paper-sources/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"city": "苏州", "district": "苏州工业园区", "grade": "七年级", "subject": "数学"},
    )

    assert r.status_code == 403


def test_search_paper_sources_saves_candidates(client: TestClient, monkeypatch):
    from app.features.question_bank import search_service, source_service, upload_service, service as question_bank_service

    async def _fake_search(req):
        return ["苏州工业园区 七年级 数学 期末 试卷 答案"], [
            {
                "title": "苏州工业园区七年级数学期末试卷含答案",
                "url": "https://example.com/sip/math7.pdf",
                "snippet": "含答案",
                "query": "q",
            }
        ]

    monkeypatch.setattr(search_service, "search_public_paper_candidates", _fake_search)
    token = _teacher_token(client)

    r = client.post(
        "/api/question-bank/paper-sources/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"city": "苏州", "district": "苏州工业园区", "grade": "七年级", "subject": "数学", "exam_type": "期末"},
    )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["saved_count"] == 1
    assert data["candidates"][0]["title"] == "苏州工业园区七年级数学期末试卷含答案"
    assert data["candidates"][0]["availability_level"] == "B"


def test_create_paper_source_saves_manual_official_candidate(client: TestClient):
    token = _teacher_token(client)

    resp = client.post(
        "/api/question-bank/paper-sources",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "至和实验学校官网八年级数学期中练习",
            "source_url": "https://www.example.edu.cn/jiaowu/math8-mid.pdf",
            "snippet": "学校官网 教务",
            "city": "苏州",
            "district": "苏州工业园区",
            "school": "示例学校",
            "grade": "八年级",
            "semester": "上册",
            "subject": "数学",
            "exam_type": "期中",
            "source_adapter": "school_official",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "candidate"
    assert data["availability_level"] == "A"
    assert data["risk_level"] == "low"
    assert data["source_type"] == "school_paper"
    assert data["source_adapter"] == "school_official"


def test_create_paper_source_requires_teacher(client: TestClient):
    token = _student_token(client)

    resp = client.post(
        "/api/question-bank/paper-sources",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "学生不能录入",
            "source_url": "https://example.com/student.pdf",
            "grade": "八年级",
            "subject": "数学",
        },
    )

    assert resp.status_code == 403


def test_validate_uploaded_paper_file_extracts_text_evidence(client: TestClient):
    token = _teacher_token(client)
    text = (
        "1. 计算 1+1。答案：2 "
        "2. 计算 2+2。答案：4 "
        "3. 计算 3+3。答案：6 "
        "4. 计算 4+4。答案：8 "
        "5. 计算 5+5。答案：10 "
        "6. 计算 6+6。答案：12"
    )

    resp = client.post(
        "/api/question-bank/paper-sources/validate-upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("math8.txt", text.encode("utf-8"), "text/plain")},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["filename"] == "math8.txt"
    assert data["source_type"] == "uploaded_text"
    assert data["question_count_estimate"] == 6
    assert data["last_question_no"] == "6"
    assert data["has_answer_signal"] is True
    assert data["can_parse_text"] is True
    assert data["suggested_status"] == "confirmed"


def test_validate_uploaded_pdf_file_uses_text_extraction(client: TestClient):
    token = _teacher_token(client)

    resp = client.post(
        "/api/question-bank/paper-sources/validate-upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("english8.pdf", _TEXT_PDF, "application/pdf")},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source_type"] == "uploaded_pdf"
    assert data["question_count_estimate"] >= 2
    assert data["has_answer_signal"] is True
    assert data["can_parse_text"] is True


def test_validate_uploaded_paper_file_requires_teacher(client: TestClient):
    token = _student_token(client)

    resp = client.post(
        "/api/question-bank/paper-sources/validate-upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("student.txt", b"1. test", "text/plain")},
    )

    assert resp.status_code == 403


def test_upload_paper_source_creates_candidate_and_can_parse_items(client: TestClient):
    token = _teacher_token(client)
    text = (
        "1. He ___ to school yesterday. A. go B. went 答案：B "
        "2. She ___ reading now. A. is B. are 答案：A "
        "3. 计算 3+4。答案：7 "
        "4. 选择正确单词。A. cat B. cats 答案：A "
        "5. We ___ friends. A. is B. are 答案：B "
        "6. I can ___ fast. A. run B. runs 答案：A"
    )

    upload_resp = client.post(
        "/api/question-bank/paper-sources/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "title": "人工上传八年级英语练习",
            "city": "苏州",
            "district": "苏州工业园区",
            "school": "示例学校",
            "grade": "八年级",
            "semester": "上册",
            "subject": "英语",
            "exam_type": "期中",
        },
        files={"file": ("english8.txt", text.encode("utf-8"), "text/plain")},
    )

    assert upload_resp.status_code == 200, upload_resp.text
    uploaded = upload_resp.json()
    paper = uploaded["paper"]
    assert paper["source_adapter"] == "manual_upload"
    assert paper["status"] == "confirmed"
    assert paper["review"]["evidence"]["manual_upload"] is True
    assert uploaded["validation"]["question_count_estimate"] == 6

    parse_resp = client.post(
        f"/api/question-bank/paper-sources/{paper['id']}/parse",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert parse_resp.status_code == 200, parse_resp.text
    parsed = parse_resp.json()
    assert parsed["parsed_count"] == 6
    assert parsed["saved_count"] == 6
    assert parsed["items"][0]["status"] == "approved"
    assert parsed["warnings"] == ["已使用人工上传文件的文本校验结果进入解析队列"]


def test_upload_paper_source_requires_teacher(client: TestClient):
    token = _student_token(client)

    resp = client.post(
        "/api/question-bank/paper-sources/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={"grade": "八年级", "subject": "英语"},
        files={"file": ("student.txt", b"1. test", "text/plain")},
    )

    assert resp.status_code == 403


def test_list_and_update_paper_sources_requires_teacher(client: TestClient):
    token = _student_token(client)

    list_resp = client.get(
        "/api/question-bank/paper-sources",
        headers={"Authorization": f"Bearer {token}"},
    )
    update_resp = client.patch(
        "/api/question-bank/paper-sources/1",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "confirmed"},
    )

    assert list_resp.status_code == 403
    assert update_resp.status_code == 403


def test_list_and_update_paper_sources(client: TestClient, monkeypatch):
    from app.features.question_bank import search_service, source_service, upload_service, service as question_bank_service

    async def _fake_search(req):
        return ["苏州工业园区 八年级 数学 期中 试卷 答案"], [
            {
                "title": "苏州工业园区八年级上册数学期中试卷含答案",
                "url": "https://example.com/sip/math8-mid.pdf",
                "snippet": "含答案",
                "query": "q",
            }
        ]

    monkeypatch.setattr(search_service, "search_public_paper_candidates", _fake_search)
    token = _teacher_token(client)

    search_resp = client.post(
        "/api/question-bank/paper-sources/search",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "city": "苏州",
            "district": "苏州工业园区",
            "grade": "八年级",
            "semester": "上册",
            "subject": "数学",
            "exam_type": "期中",
        },
    )
    paper_id = search_resp.json()["candidates"][0]["id"]

    list_resp = client.get(
        "/api/question-bank/paper-sources",
        headers={"Authorization": f"Bearer {token}"},
        params={"grade": "八年级", "semester": "上册", "subject": "数学"},
    )
    update_resp = client.patch(
        f"/api/question-bank/paper-sources/{paper_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "confirmed"},
    )

    assert list_resp.status_code == 200, list_resp.text
    assert list_resp.json()[0]["title"] == "苏州工业园区八年级上册数学期中试卷含答案"
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["status"] == "confirmed"


def test_review_paper_source_writes_review(client: TestClient, monkeypatch):
    from app.features.question_bank import search_service, source_service, upload_service, service as question_bank_service

    async def _fake_search(req):
        return ["苏州工业园区 八年级 数学 期中 试卷 答案"], [
            {
                "title": "苏州工业园区八年级上册数学期中试卷含答案",
                "url": "https://example.com/review-math8.pdf",
                "snippet": "含答案",
                "query": "q",
            }
        ]

    async def _fake_fetch(paper):
        return {
            "ok": True,
            "status_code": 200,
            "final_url": paper.source_url,
            "content_type": "application/pdf",
            "is_pdf": True,
            "content_length": 80000,
            "text": "PDF文件 含答案",
        }

    monkeypatch.setattr(search_service, "search_public_paper_candidates", _fake_search)
    monkeypatch.setattr(source_service, "fetch_paper_source_preview", _fake_fetch)
    token = _teacher_token(client)
    search_resp = client.post(
        "/api/question-bank/paper-sources/search",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "city": "苏州",
            "district": "苏州工业园区",
            "grade": "八年级",
            "semester": "上册",
            "subject": "数学",
            "exam_type": "期中",
        },
    )
    paper_id = search_resp.json()["candidates"][0]["id"]

    review_resp = client.post(
        f"/api/question-bank/paper-sources/{paper_id}/review",
        headers={"Authorization": f"Bearer {token}"},
        json={"use_ai": False},
    )

    assert review_resp.status_code == 200, review_resp.text
    data = review_resp.json()
    assert data["review"]["verdict"] == "formal_ready"
    assert data["review"]["evidence"]["is_pdf"] is True


def test_review_paper_source_requires_teacher(client: TestClient):
    token = _student_token(client)

    review_resp = client.post(
        "/api/question-bank/paper-sources/1/review",
        headers={"Authorization": f"Bearer {token}"},
        json={"use_ai": False},
    )

    assert review_resp.status_code == 403


def test_get_paper_source_full_preview_uses_uploaded_text(client: TestClient):
    token = _teacher_token(client)
    text = "1. 计算 1+1。答案：2 2. 计算 2+2。答案：4"

    upload_resp = client.post(
        "/api/question-bank/paper-sources/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "title": "人工上传八年级数学练习",
            "city": "苏州",
            "district": "苏州工业园区",
            "school": "示例学校",
            "grade": "八年级",
            "semester": "上册",
            "subject": "数学",
            "exam_type": "期中",
        },
        files={"file": ("math8.txt", text.encode("utf-8"), "text/plain")},
    )
    paper_id = upload_resp.json()["paper"]["id"]

    preview_resp = client.get(
        f"/api/question-bank/paper-sources/{paper_id}/full-preview",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert preview_resp.status_code == 200, preview_resp.text
    data = preview_resp.json()
    assert data["status"] == "available"
    assert data["content_kind"] == "uploaded_text"
    assert data["text"] == text


def test_get_paper_source_full_preview_marks_login_required(client: TestClient, monkeypatch):
    from app.features.question_bank import search_service, source_service, upload_service, service as question_bank_service

    async def _fake_search(req):
        return ["一点升学 八年级 数学"], [
            {
                "title": "一点升学八年级数学期中试卷",
                "url": "https://www.yidianedu.com/xuexiao/paper/1596/1/0",
                "snippet": "需要登录下载",
                "query": "q",
            }
        ]

    async def _fake_fetch(paper):
        return {
            "ok": True,
            "status_code": 200,
            "final_url": "https://www.yidianedu.com/index/smslogin?url=/xuexiao/paper/1596/1/0",
            "content_type": "text/html",
            "is_pdf": False,
            "content_length": 8000,
            "text": "短信登录 手机验证码 会员下载",
        }

    monkeypatch.setattr(search_service, "search_public_paper_candidates", _fake_search)
    monkeypatch.setattr(source_service, "fetch_paper_source_preview", _fake_fetch)
    token = _teacher_token(client)
    search_resp = client.post(
        "/api/question-bank/paper-sources/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"city": "苏州", "grade": "八年级", "subject": "数学", "exam_type": "期中"},
    )
    paper_id = search_resp.json()["candidates"][0]["id"]

    preview_resp = client.get(
        f"/api/question-bank/paper-sources/{paper_id}/full-preview",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert preview_resp.status_code == 200, preview_resp.text
    data = preview_resp.json()
    assert data["status"] == "login_required"
    assert data["content_kind"] == "blocked_page"
    assert "需要登录" in data["message"]


def test_get_paper_source_full_preview_requires_teacher(client: TestClient):
    token = _student_token(client)

    preview_resp = client.get(
        "/api/question-bank/paper-sources/1/full-preview",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert preview_resp.status_code == 403


def test_parse_paper_source_saves_pending_items(client: TestClient, monkeypatch):
    from app.features.question_bank import search_service, source_service, upload_service, service as question_bank_service

    async def _fake_search(req):
        return ["苏州工业园区 八年级 英语 期中 试卷 答案"], [
            {
                "title": "苏州工业园区八年级上册英语期中试卷含答案",
                "url": "https://example.com/review-english8.html",
                "snippet": "含答案",
                "query": "q",
            }
        ]

    async def _fake_fetch(paper):
        return {
            "ok": True,
            "status_code": 200,
            "final_url": paper.source_url,
            "content_type": "text/html",
            "is_pdf": False,
            "content_length": 12000,
            "text": "1. He ___ to school yesterday. A. go B. went 答案：B 2. 计算 2+3。答案：5",
        }

    monkeypatch.setattr(search_service, "search_public_paper_candidates", _fake_search)
    monkeypatch.setattr(source_service, "fetch_paper_source_preview", _fake_fetch)
    token = _teacher_token(client)
    search_resp = client.post(
        "/api/question-bank/paper-sources/search",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "city": "苏州",
            "district": "苏州工业园区",
            "grade": "八年级",
            "semester": "上册",
            "subject": "英语",
            "exam_type": "期中",
        },
    )
    paper_id = search_resp.json()["candidates"][0]["id"]

    parse_resp = client.post(
        f"/api/question-bank/paper-sources/{paper_id}/parse",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert parse_resp.status_code == 200, parse_resp.text
    data = parse_resp.json()
    assert data["parsed_count"] == 2
    assert data["saved_count"] == 2
    assert data["items"][0]["status"] == "pending"


def test_parse_paper_source_enriches_duplicate_item_options(client: TestClient, db, monkeypatch):
    from app.models.question_bank import QuestionBankItem
    from app.features.question_bank import search_service, source_service, upload_service, service as question_bank_service

    stem = "How did the regression-test family go to the lake? A. By bus. B. By car. C. By bike. D. On foot."

    async def _fake_search(req):
        return ["苏州工业园区 八年级 英语 期中 试卷 答案"], [
            {
                "title": "苏州工业园区八年级上册英语阅读理解",
                "url": "https://example.com/review-english8-options.html",
                "snippet": "含答案",
                "query": "q",
            }
        ]

    async def _fake_fetch(paper):
        return {
            "ok": True,
            "status_code": 200,
            "final_url": paper.source_url,
            "content_type": "text/html",
            "is_pdf": False,
            "content_length": 12000,
            "text": f"1. {stem}",
        }

    monkeypatch.setattr(search_service, "search_public_paper_candidates", _fake_search)
    monkeypatch.setattr(source_service, "fetch_paper_source_preview", _fake_fetch)
    stale_item = QuestionBankItem(
        subject="英语",
        grade="八年级",
        semester="上册",
        question_type="single_choice",
        stem=stem,
        options=["On foot."],
        status="pending",
        duplicate_key=question_bank_service._hash_question(stem, None),
    )
    db.add(stale_item)
    db.commit()

    token = _teacher_token(client)
    search_resp = client.post(
        "/api/question-bank/paper-sources/search",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "city": "苏州",
            "district": "苏州工业园区",
            "grade": "八年级",
            "semester": "上册",
            "subject": "英语",
            "exam_type": "期中",
        },
    )
    paper_id = search_resp.json()["candidates"][0]["id"]

    parse_resp = client.post(
        f"/api/question-bank/paper-sources/{paper_id}/parse",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert parse_resp.status_code == 200, parse_resp.text
    db.refresh(stale_item)
    assert stale_item.options == ["By bus.", "By car.", "By bike.", "On foot."]


def test_parse_pdf_paper_source_saves_pending_items(client: TestClient, monkeypatch):
    from app.features.question_bank import search_service, source_service, upload_service, service as question_bank_service

    async def _fake_search(req):
        return ["苏州工业园区 八年级 英语 期中 PDF"], [
            {
                "title": "苏州工业园区八年级上册英语期中试卷PDF含答案",
                "url": "https://example.com/review-english8.pdf",
                "snippet": "含答案",
                "query": "q",
            }
        ]

    async def _fake_fetch(paper):
        return {
            "ok": True,
            "status_code": 200,
            "final_url": paper.source_url,
            "content_type": "application/pdf",
            "is_pdf": True,
            "content_length": len(_TEXT_PDF),
            "content_bytes": _TEXT_PDF,
            "text": "PDF文件 含答案",
        }

    monkeypatch.setattr(search_service, "search_public_paper_candidates", _fake_search)
    monkeypatch.setattr(source_service, "fetch_paper_source_preview", _fake_fetch)
    token = _teacher_token(client)
    search_resp = client.post(
        "/api/question-bank/paper-sources/search",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "city": "苏州",
            "district": "苏州工业园区",
            "grade": "八年级",
            "semester": "上册",
            "subject": "英语",
            "exam_type": "期中",
        },
    )
    paper_id = search_resp.json()["candidates"][0]["id"]

    parse_resp = client.post(
        f"/api/question-bank/paper-sources/{paper_id}/parse",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert parse_resp.status_code == 200, parse_resp.text
    data = parse_resp.json()
    assert data["parsed_count"] == 2
    assert data["saved_count"] == 2
    assert data["warnings"] == []


def test_parse_scanned_pdf_paper_source_uses_vision_fallback(client: TestClient, monkeypatch):
    from app.features.question_bank import search_service, source_service, upload_service, service as question_bank_service

    async def _fake_search(req):
        return ["苏州工业园区 八年级 数学 期中 扫描PDF"], [
            {
                "title": "苏州工业园区八年级上册数学期中扫描卷含答案",
                "url": "https://example.com/scanned-math8.pdf",
                "snippet": "扫描版 含答案",
                "query": "q",
            }
        ]

    async def _fake_fetch(paper):
        return {
            "ok": True,
            "status_code": 200,
            "final_url": paper.source_url,
            "content_type": "application/pdf",
            "is_pdf": True,
            "content_length": 128,
            "content_bytes": b"%PDF-scanned",
            "text": "PDF文件 含答案",
        }

    async def _fake_vision_ocr(data):
        return "1. 计算 2+3。答案：5"

    monkeypatch.setattr(search_service, "search_public_paper_candidates", _fake_search)
    monkeypatch.setattr(source_service, "fetch_paper_source_preview", _fake_fetch)
    monkeypatch.setattr(upload_service, "_extract_pdf_text", lambda data: "")
    monkeypatch.setattr(upload_service, "_extract_scanned_pdf_text_with_vision", _fake_vision_ocr)
    token = _teacher_token(client)
    search_resp = client.post(
        "/api/question-bank/paper-sources/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"city": "苏州", "grade": "八年级", "semester": "上册", "subject": "数学", "exam_type": "期中"},
    )
    paper_id = search_resp.json()["candidates"][0]["id"]

    parse_resp = client.post(
        f"/api/question-bank/paper-sources/{paper_id}/parse",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert parse_resp.status_code == 200, parse_resp.text
    data = parse_resp.json()
    assert data["parsed_count"] == 1
    assert data["saved_count"] == 1
    assert data["items"][0]["status"] == "pending"
    assert data["warnings"] == ["PDF 未抽取到文本，已使用视觉/OCR 兜底解析，结果仍需人工审核"]


def test_list_and_review_question_bank_items(client: TestClient, monkeypatch):
    from app.features.question_bank import search_service, source_service, upload_service, service as question_bank_service

    async def _fake_search(req):
        return ["苏州工业园区 八年级 英语 期中"], [
            {
                "title": "苏州工业园区八年级上册英语期中试卷",
                "url": "https://example.com/review-items.html",
                "snippet": "含答案",
                "query": "q",
            }
        ]

    async def _fake_fetch(paper):
        return {
            "ok": True,
            "status_code": 200,
            "final_url": paper.source_url,
            "content_type": "text/html",
            "is_pdf": False,
            "content_length": 12000,
            "text": "1. He ___ to school yesterday. A. go B. went 答案：B",
        }

    monkeypatch.setattr(search_service, "search_public_paper_candidates", _fake_search)
    monkeypatch.setattr(source_service, "fetch_paper_source_preview", _fake_fetch)
    token = _teacher_token(client)
    search_resp = client.post(
        "/api/question-bank/paper-sources/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"city": "苏州", "grade": "八年级", "semester": "上册", "subject": "英语", "exam_type": "期中"},
    )
    paper_id = search_resp.json()["candidates"][0]["id"]
    client.post(f"/api/question-bank/paper-sources/{paper_id}/parse", headers={"Authorization": f"Bearer {token}"})

    list_resp = client.get("/api/question-bank/items", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.status_code == 200, list_resp.text
    item_id = list_resp.json()[0]["id"]

    update_resp = client.patch(
        f"/api/question-bank/items/{item_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "approved"},
    )

    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["status"] == "approved"


def test_question_bank_items_requires_teacher(client: TestClient):
    token = _student_token(client)

    list_resp = client.get("/api/question-bank/items", headers={"Authorization": f"Bearer {token}"})
    update_resp = client.patch(
        "/api/question-bank/items/1",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "approved"},
    )

    assert list_resp.status_code == 403
    assert update_resp.status_code == 403


def test_review_metrics_requires_teacher(client: TestClient):
    token = _student_token(client)

    resp = client.get("/api/question-bank/review-metrics", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 403


def test_get_review_metrics(client: TestClient, db):
    from app.models.question_bank import QuestionBankPaper
    from app.features.question_bank import search_service, source_service, upload_service, service as question_bank_service

    db.query(QuestionBankPaper).delete()
    db.add_all(
        [
            QuestionBankPaper(
                title="可入库且人工确认",
                source_url="https://example.com/metric-ready-ok.pdf",
                source_url_hash=question_bank_service._hash_url("https://example.com/metric-ready-ok.pdf"),
                source_type="web_paper",
                availability_level="B",
                risk_level="medium",
                status="confirmed",
                confidence=80,
                raw_meta={
                    "review": {
                        "verdict": "formal_ready",
                        "confidence": 88,
                        "completeness": "likely_full",
                        "suggested_status": "confirmed",
                        "evidence": {},
                        "reasons": [],
                        "checked_at": "2026-07-03 10:00:00",
                    }
                },
            ),
            QuestionBankPaper(
                title="可入库但人工拒绝",
                source_url="https://example.com/metric-ready-bad.pdf",
                source_url_hash=question_bank_service._hash_url("https://example.com/metric-ready-bad.pdf"),
                source_type="web_paper",
                availability_level="B",
                risk_level="medium",
                status="rejected",
                confidence=80,
                raw_meta={
                    "review": {
                        "verdict": "formal_ready",
                        "confidence": 85,
                        "completeness": "likely_full",
                        "suggested_status": "confirmed",
                        "evidence": {},
                        "reasons": [],
                        "checked_at": "2026-07-03 10:00:00",
                    }
                },
            ),
        ]
    )
    db.commit()
    token = _teacher_token(client)

    resp = client.get("/api/question-bank/review-metrics", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_reviewed"] == 2
    assert data["sampled_count"] == 2
    assert data["formal_ready_false_positive_count"] == 1
    assert data["auto_approve_allowed"] is False
