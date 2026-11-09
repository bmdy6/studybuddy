import importlib.util
import json
from pathlib import Path

from app.features.question_bank.schemas import SearchPaperSourcesRequest


def _load_script_module():
    path = Path(__file__).parents[2] / "scripts" / "evaluate_question_bank_review_samples.py"
    spec = importlib.util.spec_from_file_location("evaluate_question_bank_review_samples", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summarize_samples_counts_labeled_review_quality():
    module = _load_script_module()
    samples = [
        {"suggested_status": "confirmed", "manual_status": "confirmed"},
        {"suggested_status": "confirmed", "manual_status": "rejected"},
        {"suggested_status": "rejected", "manual_status": "confirmed"},
        {"suggested_status": "candidate", "manual_status": None},
    ]

    summary = module.summarize_samples(samples)

    assert summary["total_samples"] == 4
    assert summary["labeled_samples"] == 3
    assert summary["unlabeled_samples"] == 1
    assert summary["by_scenario"] == {"single": 4}
    assert summary["by_adapter"] == {"unknown": 4}
    assert summary["agreement_count"] == 1
    assert summary["agreement_rate"] == 0.3333
    assert summary["formal_ready_sampled_count"] == 2
    assert summary["formal_ready_false_positive_count"] == 1
    assert summary["formal_ready_false_positive_rate"] == 0.5
    assert summary["reject_sampled_count"] == 1
    assert summary["reject_false_negative_count"] == 1
    assert summary["reject_false_negative_rate"] == 1


def test_jsonl_roundtrip_keeps_chinese(tmp_path):
    module = _load_script_module()
    path = tmp_path / "samples.jsonl"
    rows = [{"title": "苏州工业园区期中试卷", "suggested_status": "confirmed", "manual_status": "confirmed"}]

    module.write_jsonl(path, rows)
    loaded = module.load_jsonl(path)

    assert loaded == rows
    assert "苏州工业园区期中试卷" in path.read_text(encoding="utf-8")


def test_load_scenarios_adds_default_id(tmp_path):
    module = _load_script_module()
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps([{"subject": "英语"}, {"scenario_id": "math_final", "subject": "数学"}], ensure_ascii=False), encoding="utf-8")

    scenarios = module.load_scenarios(path)

    assert scenarios == [{"subject": "英语", "scenario_id": "scenario_1"}, {"scenario_id": "math_final", "subject": "数学"}]


def test_batch_summary_counts_scenarios_and_adapters():
    module = _load_script_module()
    samples = [
        {"scenario_id": "grade8_math", "source_adapter": "yidian"},
        {"scenario_id": "grade8_math", "source_adapter": "official_pdf"},
        {"scenario_id": "grade7_english", "source_adapter": "yidian"},
    ]

    summary = module.summarize_samples(samples)

    assert summary["by_scenario"] == {"grade8_math": 2, "grade7_english": 1}
    assert summary["by_adapter"] == {"yidian": 2, "official_pdf": 1}


def test_collect_review_samples_marks_scenario(monkeypatch):
    import asyncio

    module = _load_script_module()
    req = SearchPaperSourcesRequest(
        city="苏州",
        district="苏州工业园区",
        school="示例学校",
        grade="七年级",
        semester="下册",
        subject="英语",
        exam_type="期末",
        limit=1,
    )

    async def _fake_search(_req, max_queries=None):
        assert max_queries == 3
        return ["query"], [{"title": "七下英语期末卷", "url": "https://example.com/en.html", "snippet": "答案", "source_adapter": "web_search"}]

    async def _fake_fetch(_paper):
        return {"ok": True, "text": "1. Choose the best answer. 答案 A"}

    class _Review:
        verdict = "完整卷"
        suggested_status = "confirmed"
        confidence = 0.8
        completeness = "complete"
        reasons = ["看到答案"]
        evidence = {"question_count": 1}

    monkeypatch.setattr(module.question_bank_service, "search_public_paper_candidates", _fake_search)
    monkeypatch.setattr(module.question_bank_service, "fetch_paper_source_preview", _fake_fetch)
    monkeypatch.setattr(module.question_bank_service, "review_paper_source_content", lambda _paper, _fetched: _Review())

    samples = asyncio.run(module.collect_review_samples(req, scenario_id="grade7_english_final", max_queries=3))

    assert len(samples) == 1
    assert samples[0]["scenario_id"] == "grade7_english_final"
    assert samples[0]["target"]["subject"] == "英语"
    assert samples[0]["source_adapter"] == "web_search"


def test_collect_review_samples_from_candidate_file(monkeypatch, tmp_path):
    import asyncio

    module = _load_script_module()
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            [
                {
                    "scenario_id": "manual_pdf",
                    "target": {"grade": "八年级", "semester": "上册", "subject": "英语", "exam_type": "期中"},
                    "title": "人工补充 PDF",
                    "url": "https://example.com/paper.pdf",
                    "snippet": "含答案",
                    "source_adapter": "public_pdf",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    async def _fake_fetch(paper):
        assert paper.source_url == "https://example.com/paper.pdf"
        return {"ok": True, "text": "1. Choose. A. Yes B. No 答案：A"}

    class _Review:
        verdict = "formal_ready"
        suggested_status = "confirmed"
        confidence = 90
        completeness = "likely_full"
        reasons = ["人工候选可访问且含答案"]
        evidence = {"question_count": 1}

    monkeypatch.setattr(module.question_bank_service, "fetch_paper_source_preview", _fake_fetch)
    monkeypatch.setattr(module.question_bank_service, "review_paper_source_content", lambda _paper, _fetched: _Review())

    samples = asyncio.run(module.collect_review_samples_from_candidates(path, module._default_args_for_tests()))

    assert samples[0]["scenario_id"] == "manual_pdf"
    assert samples[0]["source_adapter"] == "public_pdf"
    assert samples[0]["source_type"] == "public_pdf"
    assert samples[0]["suggested_status"] == "confirmed"
    assert samples[0]["target"]["subject"] == "英语"
