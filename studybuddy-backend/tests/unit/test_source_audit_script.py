import importlib.util
from pathlib import Path

from app.features.question_bank.schemas import SearchPaperSourcesRequest


def _load_script_module():
    path = Path(__file__).parents[2] / "scripts" / "audit_question_bank_sources.py"
    spec = importlib.util.spec_from_file_location("audit_question_bank_sources", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summarize_candidates_counts_adapters_and_quality():
    module = _load_script_module()
    req = SearchPaperSourcesRequest(
        city="苏州",
        district="苏州工业园区",
        school="示例学校",
        grade="八年级",
        semester="上册",
        subject="数学",
        exam_type="期中",
        limit=8,
    )
    candidates = [
        {
            "title": "苏州工业园区教育局八年级数学期中统考试卷含答案",
            "url": "https://sipac.gov.cn/edu/math8-mid.pdf",
            "snippet": "公开 PDF 答案",
            "query": "苏州工业园区 教育局 八年级 数学 期中 试卷",
            "source_adapter": "education_bureau",
        },
        {
            "title": "八年级数学期中试卷",
            "url": "https://example.com/math8.html",
            "snippet": "普通网页",
            "query": "八年级 数学 期中 试卷",
            "source_adapter": "web_search",
        },
    ]

    summary = module.summarize_candidates(candidates, req)

    assert summary["total_candidates"] == 2
    assert summary["adapter_counts"] == {"education_bureau": 1, "web_search": 1}
    assert summary["availability_counts"]["A"] == 1
    assert summary["risk_counts"]["low"] == 1
    assert summary["answer_signal_count"] == 1
    assert summary["pdf_count"] == 1
    assert summary["top_candidates"][0]["adapter"] == "education_bureau"


def test_official_queries_are_in_audit_result(monkeypatch):
    import asyncio

    module = _load_script_module()
    req = SearchPaperSourcesRequest(
        city="苏州",
        district="苏州工业园区",
        school="示例学校",
        grade="八年级",
        semester="上册",
        subject="英语",
        exam_type="期中",
        limit=8,
    )

    async def _fake_search(_req, max_queries=None):
        assert max_queries is None
        return ["普通查询"], []

    monkeypatch.setattr(module.question_bank_service, "search_public_paper_candidates", _fake_search)

    result = asyncio.run(module.audit_sources(req))

    assert result["queries"] == ["普通查询"]
    assert any(seed["domain"] == "tdc.sipedu.cn" for seed in result["official_site_seeds"])
    assert result["official_query_count"] > 0
    assert any("site:sipac.gov.cn" in query for query in result["official_queries"])
    assert result["official_link_candidate_count"] == 0


def test_official_link_discovery_can_be_enabled(monkeypatch):
    import asyncio

    module = _load_script_module()
    req = SearchPaperSourcesRequest(
        city="苏州",
        district="苏州工业园区",
        school="示例学校",
        grade="八年级",
        semester="上册",
        subject="数学",
        exam_type="期中",
        limit=8,
    )

    async def _fake_search(_req, max_queries=None):
        assert max_queries == 2
        return ["普通查询"], []

    async def _fake_discover(_req):
        return [
            {
                "title": "苏州工业园区八年级数学期中调研试卷 PDF",
                "url": "https://edu.sipac.gov.cn/math8.pdf",
                "snippet": "官方站点链接",
                "source_adapter": "education_bureau",
            }
        ]

    monkeypatch.setattr(module.question_bank_service, "search_public_paper_candidates", _fake_search)
    monkeypatch.setattr(module.question_bank_service, "discover_official_source_links", _fake_discover)

    result = asyncio.run(module.audit_sources(req, discover_official_links=True, max_queries=2))

    assert result["official_link_candidate_count"] == 1
    assert result["official_link_candidates"][0]["source_adapter"] == "education_bureau"
