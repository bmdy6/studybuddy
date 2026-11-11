"""采集并评估题库来源 AI 初审真实样本。

用法：
  PYTHONPATH=. .venv/bin/python scripts/evaluate_question_bank_review_samples.py \
    --city 苏州 --district 苏州工业园区 --school 示例学校 \
    --grade 八年级 --semester 上册 --subject 数学 --exam-type 期中 \
    --limit 8 --output /tmp/qb-review-samples.jsonl

  # 人工复核后，把 JSONL 每行补上 manual_status，再重新汇总
  PYTHONPATH=. .venv/bin/python scripts/evaluate_question_bank_review_samples.py \
    --input /tmp/qb-review-samples-labeled.jsonl

  # 批量采集默认场景：八上数学/英语 + 七下数学/英语
  PYTHONPATH=. .venv/bin/python scripts/evaluate_question_bank_review_samples.py \
    --batch-defaults --limit 4 --output /tmp/qb-review-samples-batch.jsonl

  # 评估人工补充的官网/PDF/已知卷页 URL，避免样本只来自搜索引擎
  PYTHONPATH=. .venv/bin/python scripts/evaluate_question_bank_review_samples.py \
    --candidate-file /tmp/qb-manual-candidates.json \
    --output /tmp/qb-manual-candidate-samples.jsonl

脚本只搜索、抓取预览、运行初审和汇总，不写数据库。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.models.question_bank import QuestionBankPaper
from app.features.question_bank.schemas import SearchPaperSourcesRequest
from app.features.question_bank import service as question_bank_service

MANUAL_STATUSES = {"confirmed", "rejected", "internal_style", "candidate"}
DEFAULT_BATCH_SCENARIOS: list[dict[str, Any]] = [
    {"scenario_id": "grade8_math_midterm", "grade": "八年级", "semester": "上册", "subject": "数学", "exam_type": "期中"},
    {"scenario_id": "grade8_english_midterm", "grade": "八年级", "semester": "上册", "subject": "英语", "exam_type": "期中"},
    {"scenario_id": "grade7_math_final", "grade": "七年级", "semester": "下册", "subject": "数学", "exam_type": "期末"},
    {"scenario_id": "grade7_english_final", "grade": "七年级", "semester": "下册", "subject": "英语", "exam_type": "期末"},
]


def _request_from_mapping(base: argparse.Namespace, values: dict[str, Any]) -> SearchPaperSourcesRequest:
    return SearchPaperSourcesRequest(
        province=values.get("province", base.province),
        city=values.get("city", base.city),
        district=values.get("district", base.district),
        school=values.get("school", base.school),
        grade=values.get("grade", base.grade),
        semester=values.get("semester", base.semester),
        subject=values.get("subject", base.subject),
        textbook_version=values.get("textbook_version", base.textbook_version),
        exam_type=values.get("exam_type", base.exam_type),
        year=values.get("year", base.year),
        limit=values.get("limit", base.limit),
    )


def load_scenarios(path: Path) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("scenario file must be a JSON array")
    scenarios: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"scenario #{index} must be an object")
        scenario = dict(row)
        scenario.setdefault("scenario_id", f"scenario_{index}")
        scenarios.append(scenario)
    return scenarios


def _paper_from_candidate(candidate: dict[str, str], req: SearchPaperSourcesRequest) -> QuestionBankPaper:
    title = candidate.get("title", "")
    url = candidate.get("url", "")
    snippet = candidate.get("snippet", "")
    source_type, level, risk, confidence = question_bank_service._classify_candidate(title, url, snippet)
    adapter = candidate.get("source_adapter")
    if candidate.get("source_type"):
        source_type = str(candidate["source_type"])
    elif adapter == "public_pdf":
        source_type = "public_pdf"
    return QuestionBankPaper(
        title=title[:300],
        source_url=url,
        source_url_hash=question_bank_service._hash_url(url),
        snippet=snippet,
        province=req.province,
        city=req.city,
        district=req.district,
        school=req.school,
        grade=req.grade,
        semester=req.semester,
        subject=req.subject,
        textbook_version=req.textbook_version,
        year=req.year,
        exam_type=req.exam_type,
        source_type=source_type,
        availability_level=level,
        risk_level=risk,
        status="candidate",
        confidence=confidence,
        raw_meta={"query": candidate.get("query"), "source_adapter": adapter},
    )


async def collect_review_samples(req: SearchPaperSourcesRequest, scenario_id: str | None = None, max_queries: int | None = None) -> list[dict[str, Any]]:
    _queries, candidates = await question_bank_service.search_public_paper_candidates(req, max_queries=max_queries)
    samples: list[dict[str, Any]] = []
    for candidate in candidates[: req.limit]:
        paper = _paper_from_candidate(candidate, req)
        fetched = await question_bank_service.fetch_paper_source_preview(paper)
        review = question_bank_service.review_paper_source_content(paper, fetched)
        samples.append(
            {
                "scenario_id": scenario_id,
                "target": {
                    "province": req.province,
                    "city": req.city,
                    "district": req.district,
                    "school": req.school,
                    "grade": req.grade,
                    "semester": req.semester,
                    "subject": req.subject,
                    "exam_type": req.exam_type,
                    "year": req.year,
                },
                "title": paper.title,
                "url": paper.source_url,
                "snippet": paper.snippet,
                "source_adapter": (paper.raw_meta or {}).get("source_adapter"),
                "source_type": paper.source_type,
                "availability_level": paper.availability_level,
                "risk_level": paper.risk_level,
                "ai_verdict": review.verdict,
                "suggested_status": review.suggested_status,
                "confidence": review.confidence,
                "completeness": review.completeness,
                "reasons": review.reasons,
                "evidence": review.evidence,
                "manual_status": None,
                "manual_note": "",
            }
        )
    return samples


async def collect_review_samples_batch(args: argparse.Namespace, scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for scenario in scenarios:
        req = _request_from_mapping(args, scenario)
        max_queries = scenario.get("max_queries_per_scenario", args.max_queries_per_scenario)
        samples.extend(await collect_review_samples(req, scenario_id=str(scenario["scenario_id"]), max_queries=max_queries))
    return samples


def load_candidate_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    rows = json.loads(text)
    if not isinstance(rows, list):
        raise ValueError("candidate file must be a JSON array or JSONL file")
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"candidate #{index} must be an object")
    return rows


def _candidate_request_from_row(base: argparse.Namespace, row: dict[str, Any]) -> SearchPaperSourcesRequest:
    target = row.get("target") if isinstance(row.get("target"), dict) else {}
    return _request_from_mapping(base, target)


async def collect_review_samples_from_candidates(path: Path, args: argparse.Namespace) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in load_candidate_rows(path):
        req = _candidate_request_from_row(args, row)
        candidate = {
            "title": str(row.get("title", "")),
            "url": str(row.get("url", "")),
            "snippet": str(row.get("snippet", "")),
            "query": str(row.get("query", "manual_candidate_file")),
            "source_adapter": str(row.get("source_adapter", "manual_source")),
            "source_type": str(row.get("source_type", "")),
        }
        paper = _paper_from_candidate(candidate, req)
        fetched = await question_bank_service.fetch_paper_source_preview(paper)
        review = question_bank_service.review_paper_source_content(paper, fetched)
        samples.append(
            {
                "scenario_id": row.get("scenario_id") or "manual_candidate",
                "target": {
                    "province": req.province,
                    "city": req.city,
                    "district": req.district,
                    "school": req.school,
                    "grade": req.grade,
                    "semester": req.semester,
                    "subject": req.subject,
                    "exam_type": req.exam_type,
                    "year": req.year,
                },
                "title": paper.title,
                "url": paper.source_url,
                "snippet": paper.snippet,
                "source_adapter": (paper.raw_meta or {}).get("source_adapter"),
                "source_type": paper.source_type,
                "availability_level": paper.availability_level,
                "risk_level": paper.risk_level,
                "ai_verdict": review.verdict,
                "suggested_status": review.suggested_status,
                "confidence": review.confidence,
                "completeness": review.completeness,
                "reasons": review.reasons,
                "evidence": review.evidence,
                "manual_status": row.get("manual_status"),
                "manual_note": row.get("manual_note", ""),
            }
        )
    return samples


def _default_args_for_tests() -> argparse.Namespace:
    return argparse.Namespace(
        province="江苏",
        city="苏州",
        district="苏州工业园区",
        school="示例学校",
        grade="八年级",
        semester="上册",
        subject="数学",
        textbook_version=None,
        exam_type="期中",
        year=None,
        limit=8,
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [row for row in samples if row.get("manual_status") in MANUAL_STATUSES and row.get("manual_status") != "candidate"]
    agreement_count = sum(1 for row in labeled if row.get("manual_status") == row.get("suggested_status"))
    formal_ready = [row for row in labeled if row.get("suggested_status") == "confirmed"]
    formal_ready_false_positive = [row for row in formal_ready if row.get("manual_status") in {"rejected", "internal_style"}]
    rejected = [row for row in labeled if row.get("suggested_status") == "rejected"]
    reject_false_negative = [row for row in rejected if row.get("manual_status") == "confirmed"]
    needs_label = [row for row in samples if row.get("manual_status") not in MANUAL_STATUSES]
    by_scenario: dict[str, int] = {}
    by_adapter: dict[str, int] = {}
    for row in samples:
        scenario_id = str(row.get("scenario_id") or "single")
        by_scenario[scenario_id] = by_scenario.get(scenario_id, 0) + 1
        adapter = str(row.get("source_adapter") or "unknown")
        by_adapter[adapter] = by_adapter.get(adapter, 0) + 1
    return {
        "total_samples": len(samples),
        "labeled_samples": len(labeled),
        "unlabeled_samples": len(needs_label),
        "by_scenario": by_scenario,
        "by_adapter": by_adapter,
        "agreement_count": agreement_count,
        "agreement_rate": round(agreement_count / len(labeled), 4) if labeled else None,
        "formal_ready_sampled_count": len(formal_ready),
        "formal_ready_false_positive_count": len(formal_ready_false_positive),
        "formal_ready_false_positive_rate": round(len(formal_ready_false_positive) / len(formal_ready), 4) if formal_ready else None,
        "reject_sampled_count": len(rejected),
        "reject_false_negative_count": len(reject_false_negative),
        "reject_false_negative_rate": round(len(reject_false_negative) / len(rejected), 4) if rejected else None,
    }


async def _main_async(args: argparse.Namespace) -> int:
    if args.input:
        samples = load_jsonl(Path(args.input))
    else:
        if args.candidate_file:
            samples = await collect_review_samples_from_candidates(Path(args.candidate_file), args)
        elif args.scenario_file:
            scenarios = load_scenarios(Path(args.scenario_file))
            samples = await collect_review_samples_batch(args, scenarios)
        elif args.batch_defaults:
            samples = await collect_review_samples_batch(args, DEFAULT_BATCH_SCENARIOS)
        else:
            req = _request_from_mapping(args, {})
            samples = await collect_review_samples(req, scenario_id="single", max_queries=args.max_queries_per_scenario)
        if args.output:
            write_jsonl(Path(args.output), samples)
    result = {"summary": summarize_samples(samples), "samples": samples[: args.preview]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="采集并评估题库来源 AI 初审真实样本")
    parser.add_argument("--input", default=None, help="读取已人工标注的 JSONL 样本并汇总")
    parser.add_argument("--output", default=None, help="采集模式下输出 JSONL 样本")
    parser.add_argument("--batch-defaults", action="store_true", help="批量采集默认场景：八上数学/英语、七下数学/英语")
    parser.add_argument("--scenario-file", default=None, help="读取 JSON 场景数组，批量采集多个搜索条件")
    parser.add_argument("--candidate-file", default=None, help="读取人工候选 URL 的 JSON/JSONL 文件，直接抓取初审，不走搜索")
    parser.add_argument("--max-queries-per-scenario", type=int, default=None, help="每个场景最多执行多少条搜索查询，用于真实 smoke 控制耗时")
    parser.add_argument("--province", default="")
    parser.add_argument("--city", default="")
    parser.add_argument("--district", default="")
    parser.add_argument("--school", default="")
    parser.add_argument("--grade", default="八年级")
    parser.add_argument("--semester", default="上册")
    parser.add_argument("--subject", default="数学")
    parser.add_argument("--textbook-version", default=None)
    parser.add_argument("--exam-type", default="期中")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--preview", type=int, default=5)
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
