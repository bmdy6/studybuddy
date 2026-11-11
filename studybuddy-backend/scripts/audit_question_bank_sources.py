"""审计本地化题库多来源候选命中率。

用法：
  PYTHONPATH=. .venv/bin/python scripts/audit_question_bank_sources.py \
    --city 苏州 --district 苏州工业园区 --school 示例学校 \
    --grade 八年级 --semester 上册 --subject 数学 --exam-type 期中 --limit 12

脚本只搜索和统计，不写数据库。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from typing import Any

from app.features.question_bank.schemas import SearchPaperSourcesRequest
from app.features.question_bank import service as question_bank_service


def summarize_candidates(candidates: list[dict[str, str]], req: SearchPaperSourcesRequest) -> dict[str, Any]:
    adapters: Counter[str] = Counter()
    availability: Counter[str] = Counter()
    risks: Counter[str] = Counter()
    source_types: Counter[str] = Counter()
    answer_signal_count = 0
    pdf_count = 0
    top: list[dict[str, Any]] = []

    for item in candidates:
        title = item.get("title", "")
        url = item.get("url", "")
        snippet = item.get("snippet", "")
        adapter = item.get("source_adapter") or question_bank_service._adapter_from_query(item.get("query", ""), item)
        source_type, level, risk, confidence = question_bank_service._classify_candidate(title, url, snippet)
        text = f"{title} {url} {snippet}".lower()
        adapters[adapter] += 1
        availability[level] += 1
        risks[risk] += 1
        source_types[source_type] += 1
        if any(token in text for token in ["答案", "解析", "answer"]):
            answer_signal_count += 1
        if "pdf" in text or url.lower().split("?", 1)[0].endswith(".pdf"):
            pdf_count += 1
        top.append(
            {
                "title": title,
                "url": url,
                "adapter": adapter,
                "availability_level": level,
                "risk_level": risk,
                "source_type": source_type,
                "score": question_bank_service._score_candidate(item, req),
                "confidence": confidence,
            }
        )

    top.sort(key=lambda item: item["score"], reverse=True)
    return {
        "total_candidates": len(candidates),
        "adapter_counts": dict(adapters),
        "availability_counts": dict(availability),
        "risk_counts": dict(risks),
        "source_type_counts": dict(source_types),
        "answer_signal_count": answer_signal_count,
        "pdf_count": pdf_count,
        "top_candidates": top[:8],
    }


async def audit_sources(req: SearchPaperSourcesRequest, discover_official_links: bool = False, max_queries: int | None = None) -> dict[str, Any]:
    queries, candidates = await question_bank_service.search_public_paper_candidates(req, max_queries=max_queries)
    summary = summarize_candidates(candidates, req)
    official_queries = question_bank_service.build_official_source_queries(req)
    official_site_seeds = question_bank_service.build_official_source_site_seeds(req)
    official_link_candidates = await question_bank_service.discover_official_source_links(req) if discover_official_links else []
    return {
        "request": req.model_dump(),
        "queries": queries,
        "official_site_seeds": official_site_seeds,
        "official_query_count": len(official_queries),
        "official_queries": official_queries,
        "official_link_candidates": official_link_candidates,
        "official_link_candidate_count": len(official_link_candidates),
        **summary,
    }


async def _main_async(args: argparse.Namespace) -> int:
    req = SearchPaperSourcesRequest(
        province=args.province,
        city=args.city,
        district=args.district,
        school=args.school,
        grade=args.grade,
        semester=args.semester,
        subject=args.subject,
        textbook_version=args.textbook_version,
        exam_type=args.exam_type,
        year=args.year,
        limit=args.limit,
    )
    result = await audit_sources(req, discover_official_links=args.discover_official_links, max_queries=args.max_queries)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="审计题库多来源候选命中率")
    parser.add_argument("--province", default="")
    parser.add_argument("--city", default="")
    parser.add_argument("--district", default="")
    parser.add_argument("--school", default="")
    parser.add_argument("--grade", default="八年级")
    parser.add_argument("--semester", default="上册")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--textbook-version", default=None)
    parser.add_argument("--exam-type", default="期中")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--discover-official-links", action="store_true", help="额外打开官方 seed 入口页，抽取疑似试卷链接")
    parser.add_argument("--max-queries", type=int, default=None, help="最多执行多少条搜索查询，用于真实 smoke 控制耗时")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
