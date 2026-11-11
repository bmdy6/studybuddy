import asyncio

from sqlalchemy.orm import Session

from app.models.question_bank import QuestionBankPaper
from app.features.question_bank.schemas import CreatePaperSourceRequest, SearchPaperSourcesRequest
from app.features.question_bank import search_service, source_service, service as question_bank_service


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


def test_build_paper_search_queries_uses_school_and_district():
    req = SearchPaperSourcesRequest(
        province="江苏",
        city="苏州",
        district="苏州工业园区",
        school="示例学校",
        grade="七年级",
        semester="下册",
        subject="数学",
        exam_type="期末",
    )

    queries = question_bank_service.build_paper_search_queries(req)

    assert "示例学校" in queries[0]
    assert "七年级" in queries[0]
    assert "数学" in queries[0]
    assert any("教务" in q and "示例学校" in q for q in queries)
    assert any("苏州工业园区" in q and "统考" in q for q in queries)
    assert any("苏州工业园区" in q and "教育局" in q for q in queries)


def test_build_official_source_queries_targets_school_and_gov_sites():
    req = SearchPaperSourcesRequest(
        province="江苏",
        city="苏州",
        district="苏州工业园区",
        school="示例学校",
        grade="八年级",
        semester="上册",
        subject="英语",
        exam_type="期中",
    )

    queries = question_bank_service.build_official_source_queries(req)

    assert any("site:edu.cn" in q and "示例学校" in q for q in queries)
    assert any("site:sipac.gov.cn" in q and "苏州工业园区" in q for q in queries)
    assert any("site:edu.sipac.gov.cn" in q and "苏州工业园区" in q for q in queries)
    assert any("site:tdc.sipedu.cn" in q and "示例学校" in q for q in queries)
    assert any("site:jyj.suzhou.gov.cn" in q for q in queries)
    assert any("教师发展中心" in q for q in queries)
    assert len(queries) == len(set(queries))


def test_estimate_question_count_supports_answer_table_format():
    text = "题号 答案 考点 1 air 核心词汇 U3 2 building 建筑词汇 U1 3 C 单项选择 U5"

    count, last_no = question_bank_service._estimate_question_count(text)

    assert count == 3
    assert last_no == "3"


def test_build_official_source_site_seeds_for_suzhou_industrial_park():
    req = SearchPaperSourcesRequest(
        province="江苏",
        city="苏州",
        district="苏州工业园区",
        school="示例学校",
        grade="八年级",
        semester="上册",
        subject="数学",
        exam_type="期中",
    )

    seeds = question_bank_service.build_official_source_site_seeds(req)
    domains = {seed["domain"] for seed in seeds}

    assert "edu.sipac.gov.cn" in domains
    assert "tdc.sipedu.cn" in domains
    assert "jyj.suzhou.gov.cn" in domains
    assert any(seed.get("url") == "https://www.sipac.gov.cn/" for seed in seeds)
    assert any(seed.get("url") == "http://www.suzhou.gov.cn/" for seed in seeds)
    assert any(seed.get("url") == "https://tdc.sipedu.cn/gsgg/tzgg" for seed in seeds)
    assert any(seed.get("url") == "https://tdc.sipedu.cn/jxyj" for seed in seeds)
    assert any(seed.get("url") == "https://tdc.sipedu.cn/jydd" for seed in seeds)
    assert any(seed["domain"] == "tdc.sipedu.cn" and "url" not in seed for seed in seeds)


def test_discover_official_source_links_prefers_column_seed_url(monkeypatch):
    requested_urls = []

    class _Response:
        def __init__(self, url: str) -> None:
            self.url = url
            self.text = '<a href="/files/math8-midterm.pdf">八年级数学期中调研试卷 PDF</a>'

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **_kwargs):
            requested_urls.append(url)
            return _Response(url)

    monkeypatch.setattr(
        search_service,
        "build_official_source_site_seeds",
        lambda _req: [
            {
                "name": "苏州工业园区教师发展中心-通知公告",
                "domain": "tdc.sipedu.cn",
                "source_adapter": "education_bureau",
                "url": "https://tdc.sipedu.cn/gsgg/tzgg",
            }
        ],
    )
    monkeypatch.setattr(search_service.httpx, "AsyncClient", lambda *a, **kw: _Client())
    req = SearchPaperSourcesRequest(city="苏州", district="苏州工业园区", grade="八年级", semester="上册", subject="数学", exam_type="期中", limit=5)

    candidates = asyncio.run(question_bank_service.discover_official_source_links(req, max_links_per_seed=1))

    assert requested_urls == ["https://tdc.sipedu.cn/gsgg/tzgg"]
    assert candidates[0]["query"] == "official-seed:https://tdc.sipedu.cn/gsgg/tzgg"
    assert candidates[0]["url"] == "https://tdc.sipedu.cn/files/math8-midterm.pdf"


def test_discover_official_source_links_filters_same_domain_and_paper_keywords(monkeypatch):
    class _Response:
        url = "https://edu.sipac.gov.cn/"
        text = """
        <a href="/notice/math8-midterm.pdf">八年级数学期中调研试卷 PDF</a>
        <a href="https://example.com/math8.pdf">八年级数学期中试卷 外站</a>
        <a href="/news/lunch.html">食堂菜单</a>
        """

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *_args, **_kwargs):
            return _Response()

    monkeypatch.setattr(search_service.httpx, "AsyncClient", lambda *a, **kw: _Client())
    req = SearchPaperSourcesRequest(city="苏州", district="苏州工业园区", grade="八年级", semester="上册", subject="数学", exam_type="期中", limit=5)

    candidates = asyncio.run(question_bank_service.discover_official_source_links(req, max_links_per_seed=1))

    assert candidates
    assert candidates[0]["title"] == "八年级数学期中调研试卷 PDF"
    assert candidates[0]["url"].startswith("https://edu.sipac.gov.cn/")
    assert candidates[0]["source_adapter"] == "education_bureau"


def test_save_paper_candidates_dedupes_by_url_and_marks_paid_sources(db: Session):
    req = SearchPaperSourcesRequest(city="苏州", district="苏州工业园区", grade="七年级", subject="英语", exam_type="期末")
    candidates = [
        {
            "title": "苏州工业园区七年级英语期末试卷含答案",
            "url": "https://example.com/paper/1.pdf",
            "snippet": "含答案解析",
            "query": "q1",
        },
        {
            "title": "组卷网 苏州工业园区七年级英语期末试卷",
            "url": "https://zujuan.example.com/paper/2",
            "snippet": "需要登录下载",
            "query": "q2",
        },
        {
            "title": "重复 URL",
            "url": "https://example.com/paper/1.pdf",
            "snippet": "",
            "query": "q3",
        },
    ]

    papers = question_bank_service.save_paper_candidates(db, req, candidates, created_by=1)

    assert len(papers) == 3  # 返回包含命中的 existing，库内唯一是 2 条
    rows = (
        db.query(QuestionBankPaper)
        .filter(QuestionBankPaper.source_url.in_(["https://example.com/paper/1.pdf", "https://zujuan.example.com/paper/2"]))
        .all()
    )
    assert len(rows) == 2
    paid = next(r for r in rows if "组卷网" in r.title)
    assert paid.availability_level == "C"
    assert paid.status == "internal_style"
    assert paid.risk_level == "high"


def test_save_paper_candidates_classifies_official_sources(db: Session):
    req = SearchPaperSourcesRequest(city="苏州", district="苏州工业园区", grade="八年级", subject="数学", exam_type="期中")
    candidates = [
        {
            "title": "苏州工业园区教育局八年级数学期中统考试卷",
            "url": "https://sipac.gov.cn/edu/math8-mid.pdf",
            "snippet": "公开资料",
            "query": "苏州工业园区 教育局 八年级 数学 期中 试卷",
            "source_adapter": "education_bureau",
        },
        {
            "title": "示例学校官网八年级数学期中练习",
            "url": "https://www.example.edu.cn/jiaowu/math8-mid.pdf",
            "snippet": "学校官网 教务",
            "query": "示例学校 教务 八年级 数学 期中",
            "source_adapter": "school_official",
        },
    ]

    papers = question_bank_service.save_paper_candidates(db, req, candidates, created_by=1)

    assert papers[0].availability_level == "A"
    assert papers[0].risk_level == "low"
    assert papers[0].source_type == "district_paper"
    assert papers[0].raw_meta["source_adapter"] == "education_bureau"
    assert question_bank_service.to_item(papers[0]).source_adapter == "education_bureau"
    assert papers[1].source_type == "school_paper"
    assert papers[1].confidence >= papers[0].confidence


def test_create_manual_paper_source_dedupes_and_marks_official(db: Session):
    req = CreatePaperSourceRequest(
        title="示例学校官网八年级数学期中练习",
        source_url="https://www.example.edu.cn/jiaowu/math8-mid.pdf",
        snippet="学校官网 教务",
        city="苏州",
        district="苏州工业园区",
        school="示例学校",
        grade="八年级",
        semester="上册",
        subject="数学",
        exam_type="期中",
        source_adapter="school_official",
    )

    created = question_bank_service.create_manual_paper_source(db, req, created_by=1)
    updated = question_bank_service.create_manual_paper_source(
        db,
        req.model_copy(update={"title": "示例学校官网八年级数学期中卷"}),
        created_by=1,
    )

    assert created.id == updated.id
    assert updated.source_type == "school_paper"
    assert updated.availability_level == "A"
    assert updated.risk_level == "low"
    assert updated.raw_meta["manual_entry"] is True
    assert updated.raw_meta["source_adapter"] == "school_official"


def _paper_with_review(url: str, verdict: str, suggested_status: str, status: str) -> QuestionBankPaper:
    return QuestionBankPaper(
        title=f"{verdict}-{url}",
        source_url=url,
        source_url_hash=question_bank_service._hash_url(url),
        source_type="web_paper",
        availability_level="B",
        risk_level="medium",
        status=status,
        confidence=70,
        raw_meta={
            "review": {
                "verdict": verdict,
                "confidence": 80,
                "completeness": "likely_full",
                "suggested_status": suggested_status,
                "evidence": {},
                "reasons": [],
                "checked_at": "2026-07-03 10:00:00",
            }
        },
    )


def test_get_review_metrics_compares_ai_review_with_manual_status(db: Session):
    db.query(QuestionBankPaper).delete()
    db.add_all(
        [
            _paper_with_review("https://example.com/ready-ok.pdf", "formal_ready", "confirmed", "confirmed"),
            _paper_with_review("https://example.com/ready-bad.pdf", "formal_ready", "confirmed", "rejected"),
            _paper_with_review("https://example.com/reject-bad.pdf", "reject", "rejected", "confirmed"),
            _paper_with_review("https://example.com/manual.pdf", "needs_manual", "candidate", "candidate"),
        ]
    )
    db.commit()

    metrics = question_bank_service.get_review_metrics(db)

    assert metrics.total_reviewed == 4
    assert metrics.sampled_count == 3
    assert metrics.agreement_count == 1
    assert metrics.agreement_rate == 0.3333
    assert metrics.formal_ready_sampled_count == 2
    assert metrics.formal_ready_false_positive_count == 1
    assert metrics.formal_ready_false_positive_rate == 0.5
    assert metrics.reject_sampled_count == 1
    assert metrics.reject_false_negative_count == 1
    assert metrics.auto_approve_allowed is False


def test_get_review_metrics_allows_auto_approve_after_quality_gate(db: Session):
    db.query(QuestionBankPaper).delete()
    papers = [
        _paper_with_review(f"https://example.com/ready-ok-{idx}.pdf", "formal_ready", "confirmed", "confirmed")
        for idx in range(20)
    ]
    db.add_all(papers)
    db.commit()

    metrics = question_bank_service.get_review_metrics(db)

    assert metrics.sampled_count == 20
    assert metrics.formal_ready_sampled_count == 20
    assert metrics.formal_ready_false_positive_rate == 0
    assert metrics.auto_approve_allowed is True


def test_review_paper_source_auto_confirms_when_quality_gate_passes(db: Session, monkeypatch):
    db.query(QuestionBankPaper).delete()
    db.add_all(
        [
            _paper_with_review(f"https://example.com/ready-history-{idx}.pdf", "formal_ready", "confirmed", "confirmed")
            for idx in range(20)
        ]
    )
    paper = QuestionBankPaper(
        title="苏州工业园区八年级数学期中试卷含答案",
        source_url="https://example.com/new-ready.pdf",
        source_url_hash="new-ready",
        grade="八年级",
        subject="数学",
        exam_type="期中",
        source_type="web_paper",
        availability_level="B",
        risk_level="low",
        status="candidate",
        confidence=82,
    )
    db.add(paper)
    db.commit()

    async def _fake_fetch(_paper):
        return {
            "ok": True,
            "status_code": 200,
            "final_url": paper.source_url,
            "content_type": "application/pdf",
            "is_pdf": True,
            "content_length": 80000,
            "text": "1. 选择题 A. 1 B. 2 答案：B",
        }

    monkeypatch.setattr(source_service, "fetch_paper_source_preview", _fake_fetch)

    reviewed = asyncio.run(question_bank_service.review_paper_source(db, paper.id))

    assert reviewed.status == "confirmed"
    assert reviewed.raw_meta["auto_approval"]["applied"] is True


def test_review_paper_source_keeps_candidate_when_quality_gate_fails(db: Session, monkeypatch):
    db.query(QuestionBankPaper).delete()
    paper = QuestionBankPaper(
        title="苏州工业园区八年级数学期中试卷含答案",
        source_url="https://example.com/new-ready-gated.pdf",
        source_url_hash="new-ready-gated",
        grade="八年级",
        subject="数学",
        exam_type="期中",
        source_type="web_paper",
        availability_level="B",
        risk_level="low",
        status="candidate",
        confidence=82,
    )
    db.add(paper)
    db.commit()

    async def _fake_fetch(_paper):
        return {
            "ok": True,
            "status_code": 200,
            "final_url": paper.source_url,
            "content_type": "application/pdf",
            "is_pdf": True,
            "content_length": 80000,
            "text": "1. 选择题 A. 1 B. 2 答案：B",
        }

    monkeypatch.setattr(source_service, "fetch_paper_source_preview", _fake_fetch)

    reviewed = asyncio.run(question_bank_service.review_paper_source(db, paper.id))

    assert reviewed.status == "candidate"
    assert reviewed.raw_meta["auto_approval"]["applied"] is False
    assert "样本量不足" in reviewed.raw_meta["auto_approval"]["reason"]


def test_get_paper_source_preview_uses_uploaded_text(db: Session):
    paper = QuestionBankPaper(
        title="上传诊断卷",
        source_url="upload://question-bank/test.pdf",
        source_url_hash="uploaded-preview",
        grade="八年级",
        subject="英语",
        source_type="web_paper",
        availability_level="B",
        risk_level="low",
        status="candidate",
        raw_meta={
            "uploaded_file": {
                "filename": "test.pdf",
                "content_type": "application/pdf",
                "extracted_text": "1. He ___ to school. A. go B. went Answer: B",
            }
        },
    )
    db.add(paper)
    db.commit()

    preview = asyncio.run(question_bank_service.get_paper_source_full_preview(db, paper.id))

    assert preview.status == "available"
    assert preview.content_kind == "uploaded_text"
    assert "He ___ to school" in preview.text
    assert preview.can_parse is True


def test_get_paper_source_preview_marks_login_required(db: Session, monkeypatch):
    paper = QuestionBankPaper(
        title="一点升学试卷",
        source_url="https://www.yidianedu.com/xuexiao/paper/1596/1/0",
        source_url_hash="yidian-preview",
        grade="七年级",
        subject="数学",
        source_type="web_paper",
        availability_level="B",
        risk_level="medium",
        status="candidate",
    )
    db.add(paper)
    db.commit()

    async def _fake_fetch(_paper):
        return {
            "ok": True,
            "status_code": 200,
            "final_url": "https://www.yidianedu.com/index/smslogin?url=/xuexiao/paper/1596/1/0",
            "content_type": "text/html; charset=UTF-8",
            "is_pdf": False,
            "content_length": 7000,
            "text": "用户登录 手机验证码 登录",
        }

    monkeypatch.setattr(source_service, "fetch_paper_source_preview", _fake_fetch)

    preview = asyncio.run(question_bank_service.get_paper_source_full_preview(db, paper.id))

    assert preview.status == "login_required"
    assert preview.can_parse is False
    assert "需要登录" in preview.message


def test_get_paper_source_preview_extracts_direct_pdf(db: Session, monkeypatch):
    paper = QuestionBankPaper(
        title="公开 PDF",
        source_url="https://example.com/math.pdf",
        source_url_hash="pdf-preview",
        grade="八年级",
        subject="数学",
        source_type="web_paper",
        availability_level="B",
        risk_level="low",
        status="candidate",
    )
    db.add(paper)
    db.commit()

    async def _fake_fetch(_paper):
        return {
            "ok": True,
            "status_code": 200,
            "final_url": paper.source_url,
            "content_type": "application/pdf",
            "is_pdf": True,
            "content_length": len(_TEXT_PDF),
            "content_bytes": _TEXT_PDF,
            "text": "",
        }

    monkeypatch.setattr(source_service, "fetch_paper_source_preview", _fake_fetch)

    preview = asyncio.run(question_bank_service.get_paper_source_full_preview(db, paper.id))

    assert preview.status == "available"
    assert preview.content_kind == "pdf_text"
    assert "Calculate 2 plus 3" in preview.text


def test_search_public_paper_candidates_falls_back_to_search_urls(monkeypatch):
    class _FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr(search_service.httpx, "AsyncClient", lambda *a, **kw: _FailingClient())
    req = SearchPaperSourcesRequest(city="苏州", district="苏州工业园区", grade="七年级", subject="数学", limit=2)

    queries, candidates = asyncio.run(question_bank_service.search_public_paper_candidates(req))

    assert queries
    assert len(candidates) == 2
    assert all(c["url"].startswith("https://duckduckgo.com/?q=") for c in candidates)


def test_search_public_paper_candidates_can_limit_queries(monkeypatch):
    class _FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr(search_service.httpx, "AsyncClient", lambda *a, **kw: _FailingClient())
    req = SearchPaperSourcesRequest(city="苏州", district="苏州工业园区", grade="八年级", semester="上册", subject="英语", exam_type="期中", limit=5)

    queries, candidates = asyncio.run(question_bank_service.search_public_paper_candidates(req, max_queries=2))

    assert len(queries) == 2
    assert len(candidates) == 2


def test_yidianedu_search_treats_per_page_as_page_number(monkeypatch):
    requested_pages = []

    class _Response:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    class _Client:
        async def get(self, url, params=None):
            requested_pages.append(params["per_page"])
            if params["per_page"] == "1":
                return _Response(
                    """
                    <ul class="page-professional-list">
                      <li class="page-professional-item">
                        <a href="/xuexiao/paper/732/1/0">星港学校2021-2022学年第二学期七年级数学期末考试试卷（含答案）</a>
                        <p class="page-school-level">苏州 初一 数学 期末</p>
                      </li>
                    </ul>
                    """
                )
            return _Response('<ul class="page-professional-list"></ul>')

    req = SearchPaperSourcesRequest(grade="七年级", subject="数学", exam_type="期末", limit=8)

    results = asyncio.run(question_bank_service._search_yidianedu(_Client(), req))

    assert requested_pages[:2] == ["1", "2"]
    assert results[0]["title"].startswith("星港学校")
    assert results[0]["url"] == "https://www.yidianedu.com/xuexiao/paper/732/1/0"
    assert results[0]["source_adapter"] == "yidianedu"


def test_adapter_from_query_marks_education_bureau_and_public_pdf():
    bureau = question_bank_service._adapter_from_query(
        "苏州工业园区 教育局 八年级 数学 期中 试卷",
        {"title": "期中统考试卷", "url": "https://sipac.gov.cn/edu/math8.pdf", "snippet": ""},
    )
    public_pdf = question_bank_service._adapter_from_query(
        "八年级 数学 期中 真题 PDF",
        {"title": "数学期中真题", "url": "https://example.com/math8.pdf", "snippet": ""},
    )

    assert bureau == "education_bureau"
    assert public_pdf == "public_pdf"


def test_candidate_score_prefers_local_answered_paper():
    req = SearchPaperSourcesRequest(
        province="江苏",
        city="苏州",
        district="苏州工业园区",
        school="示例学校",
        grade="七年级",
        semester="下册",
        subject="数学",
        exam_type="期末",
    )
    local = {"title": "苏州工业园区七年级下册数学期末试卷含答案", "url": "https://example.com/a", "snippet": ""}
    generic = {"title": "七年级数学期末试卷", "url": "https://example.com/b", "snippet": ""}

    assert question_bank_service._score_candidate(local, req) > question_bank_service._score_candidate(generic, req)


def test_relevance_rejects_wrong_exam_type():
    req = SearchPaperSourcesRequest(grade="七年级", subject="数学", exam_type="期末")
    item = {
        "title": "苏州工业园区七年级下学期数学期中试卷（含答案）",
        "url": "https://www.yidianedu.com/xuexiao/paper/1/1/0",
        "snippet": "年级：初一 科目：数学",
    }

    assert question_bank_service._is_relevant_candidate(item, req) is False


def test_review_pdf_with_answer_signal_is_formal_ready(db: Session):
    paper = QuestionBankPaper(
        title="苏州工业园区八年级数学期中试卷含答案",
        source_url="https://example.com/math8.pdf",
        source_url_hash="review-ready",
        grade="八年级",
        subject="数学",
        exam_type="期中",
        source_type="web_paper",
        availability_level="B",
        risk_level="low",
        status="candidate",
        confidence=82,
    )
    db.add(paper)
    db.commit()

    review = question_bank_service.review_paper_source_content(
        paper,
        {
            "ok": True,
            "status_code": 200,
            "final_url": paper.source_url,
            "content_type": "application/pdf",
            "is_pdf": True,
            "content_length": 50000,
            "text": "PDF文件 含答案",
        },
    )

    assert review.verdict == "formal_ready"
    assert review.completeness == "likely_full"
    assert review.suggested_status == "confirmed"


def test_review_preview_page_needs_manual():
    paper = QuestionBankPaper(
        title="七年级数学期末试卷",
        source_url="https://example.com/preview",
        source_url_hash="review-preview",
        grade="七年级",
        subject="数学",
        exam_type="期末",
        source_type="web_paper",
        availability_level="B",
        risk_level="medium",
        status="candidate",
        confidence=60,
    )
    review = question_bank_service.review_paper_source_content(
        paper,
        {
            "ok": True,
            "status_code": 200,
            "final_url": paper.source_url,
            "content_type": "text/html",
            "is_pdf": False,
            "content_length": 6000,
            "text": "1. 选择题 2. 填空题 3. 解答题 预览部分内容，阅读全文需下载后查看",
        },
    )

    assert review.verdict == "needs_manual"
    assert review.completeness == "preview_only"


def test_parse_questions_from_text_extracts_answer():
    text = "1. He ___ to school yesterday. A. go B. went 答案：B 2. 计算 2+3。答案：5"

    drafts = question_bank_service._parse_questions_from_text(text)

    assert len(drafts) == 2
    assert drafts[0]["question_no"] == "1"
    assert drafts[0]["answer"] == "B"
    assert drafts[0]["question_type"] == "single_choice"


def test_parse_questions_from_text_keeps_all_choice_options():
    text = "1. How did Lisa's family go to the lake? A. By bus. B. By car. C. By bike. D. On foot."

    drafts = question_bank_service._parse_questions_from_text(text)

    assert drafts[0]["options"] == ["By bus.", "By car.", "By bike.", "On foot."]


def test_parse_questions_from_text_trims_section_titles_and_tail_notes():
    text = (
        "1. There will be a meeting tomorrow. 五、阅读理解（每题 2 分，共 10 分）"
        " Last Sunday, Lisa went to a lake. "
        "2. Look! The panda ______ bamboo. 做完后请拍照，每页都要拍清楚。不会的题也要拍进去。"
    )

    drafts = question_bank_service._parse_questions_from_text(text)

    assert drafts[0]["stem"] == "There will be a meeting tomorrow."
    assert drafts[1]["stem"] == "Look! The panda ______ bamboo."


def test_parse_confirmed_paper_auto_approves_answered_items(db: Session):
    paper = QuestionBankPaper(
        title="已确认八年级数学试卷",
        source_url="upload://question-bank/answered",
        source_url_hash="answered",
        grade="八年级",
        subject="数学",
        semester="上册",
        source_type="web_paper",
        availability_level="B",
        risk_level="low",
        status="confirmed",
        confidence=90,
        raw_meta={
            "uploaded_file": {
                "extracted_text": "1. 计算 1+1。答案：2 2. 计算 2+3。答案：5",
            }
        },
    )
    db.add(paper)
    db.commit()

    result = asyncio.run(question_bank_service.parse_paper_source_to_items(db, paper.id))

    assert result.parsed_count == 2
    assert {item.status for item in result.items} == {"approved"}


def test_parse_candidate_or_unanswered_paper_keeps_items_pending(db: Session):
    paper = QuestionBankPaper(
        title="无答案学生练习卷",
        source_url="upload://question-bank/unanswered",
        source_url_hash="unanswered",
        grade="八年级",
        subject="英语",
        semester="上册",
        source_type="web_paper",
        availability_level="B",
        risk_level="low",
        status="confirmed",
        confidence=90,
        raw_meta={
            "uploaded_file": {
                "extracted_text": "1. There ______ a book on the desk. 2. I ______ to school yesterday.",
            }
        },
    )
    db.add(paper)
    db.commit()

    result = asyncio.run(question_bank_service.parse_paper_source_to_items(db, paper.id))

    assert result.parsed_count == 2
    assert {item.status for item in result.items} == {"pending"}
    assert "缺少答案" in " ".join(result.warnings)


def test_extract_pdf_text_reads_text_pdf():
    text = question_bank_service._extract_pdf_text(_TEXT_PDF)

    assert "He ___ to school" in text
    assert "Answer: B" in text


def test_render_pdf_pages_to_png():
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "1. Calculate 2+3. Answer: 5")
    pdf_bytes = doc.tobytes()
    doc.close()

    images = question_bank_service._render_pdf_pages_to_png(pdf_bytes)

    assert len(images) == 1
    assert images[0].startswith(b"\x89PNG")
