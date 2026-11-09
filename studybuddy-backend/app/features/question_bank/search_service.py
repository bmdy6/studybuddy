"""试卷来源搜索编排层。

协调多源搜索（一点升学 / Bing / DuckDuckGo / 官方站点），
构建查询、触发抓取、汇总候选。HTML 解析见 parsers，评分去重见 scoring。
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus, urlparse

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.question_bank import QuestionBankPaper
from .parsers import (
    _DuckDuckGoParser,
    _OfficialLinkParser,
    _YIDIANEDU_BASE,
    _clean_text,
    _grade_for_yidianedu,
    _parse_bing_results,
    _parse_yidianedu_results,
    _type_id_for_yidianedu,
)
from .scoring import (
    _adapter_from_query,
    _classify_candidate,
    _dedupe_candidates,
    _dedupe_queries,
    _hash_url,
    _is_relevant_candidate,
    _score_candidate,
)
from .schemas import SearchPaperSourcesRequest

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

async def _search_yidianedu(client: httpx.AsyncClient, req: SearchPaperSourcesRequest) -> list[dict[str, str]]:
    base_params = {
        "grade": _grade_for_yidianedu(req.grade),
        "subject": req.subject,
        "type_id": _type_id_for_yidianedu(req.exam_type),
    }
    results: list[dict[str, str]] = []
    # 一点升学的 per_page 实际表现更接近页码，不是 page size。
    for page in range(1, 9):
        params = {**base_params, "per_page": str(page)}
        resp = await client.get(f"{_YIDIANEDU_BASE}/index/paperlist", params=params)
        resp.raise_for_status()
        page_results = _parse_yidianedu_results(resp.text)
        if not page_results and page > 1:
            continue
        results.extend(page_results)
    for item in results:
        item["query"] = f"一点升学 {base_params['grade']} {req.subject} {req.exam_type or '期末'}"
        item["source_adapter"] = "yidianedu"
    return results


def build_paper_search_queries(req: SearchPaperSourcesRequest) -> list[str]:
    location = " ".join(x for x in [req.province, req.city, req.district, req.school] if x)
    base = " ".join(x for x in [location, req.grade, req.semester, req.subject] if x)
    exam_type = req.exam_type or "期末"
    queries = [
        f"{base} {exam_type} 试卷 答案",
        f"{base} {exam_type} 真题 PDF",
    ]
    if req.school:
        queries.extend(
            [
                f"{req.school} {req.grade} {req.subject} {exam_type} 试卷",
                f"{req.school} 教务 {req.grade} {req.subject} {exam_type}",
            ]
        )
    if req.district:
        district_base = " ".join(x for x in [req.city, req.district, req.grade, req.semester, req.subject] if x)
        queries.append(f"{district_base} 统考 试卷 答案")
        queries.append(f"{req.district} 教育局 {req.grade} {req.subject} {exam_type} 试卷")
        queries.append(f"{req.district} 教研 {req.grade} {req.subject} {exam_type} 试卷")
    if req.textbook_version:
        queries.append(f"{req.textbook_version} {req.grade} {req.semester or ''} {req.subject} {exam_type} 试卷")
    return _dedupe_queries([_clean_text(q) for q in queries if _clean_text(q)])


def _school_query_aliases(school: str | None) -> list[str]:
    if not school:
        return []
    aliases = [school]
    short = school
    for token in ["苏州工业园区", "苏州市", "实验学校", "学校"]:
        short = short.replace(token, "")
    short = short.strip()
    if short and short != school:
        aliases.append(short)
    return aliases


def build_official_source_site_seeds(req: SearchPaperSourcesRequest) -> list[dict[str, str]]:
    seeds: list[dict[str, str]] = []
    for key in [req.district, req.city]:
        for seed in settings.config.question_bank.official_source_site_seeds.get(key or "", ()):
            item = {
                "name": seed.name,
                "domain": seed.domain,
                "source_adapter": seed.source_adapter,
            }
            if seed.url:
                item["url"] = seed.url
            seeds.append(item)
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for seed in seeds:
        dedupe_key = seed.get("url") or seed["domain"]
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(seed)
    return deduped


def _same_or_child_domain(url: str, domain: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    domain = domain.lower()
    return netloc == domain or netloc.endswith("." + domain)


def _looks_like_paper_link(item: dict[str, str], req: SearchPaperSourcesRequest) -> bool:
    text = f"{item.get('title', '')} {item.get('url', '')} {item.get('snippet', '')}".lower()
    paper_hit = any(token in text for token in ["试卷", "试题", "真题", "练习", "调研", "考试", "质量监测", "pdf"])
    subject_hit = req.subject.lower() in text
    grade_hit = req.grade.lower() in text or _grade_for_yidianedu(req.grade).lower() in text
    exam_hit = not req.exam_type or req.exam_type.lower() in text
    return paper_hit and (subject_hit or grade_hit or exam_hit)


def _candidate_from_official_link(seed: dict[str, str], link: dict[str, str], req: SearchPaperSourcesRequest) -> dict[str, str]:
    return {
        "title": _clean_text(link.get("title", "")),
        "url": link.get("url", ""),
        "snippet": _clean_text(f"{seed.get('name', '')} {req.district or req.city or ''} 官方站点链接"),
        "query": f"official-seed:{seed.get('url') or seed.get('domain', '')}",
        "source_adapter": seed.get("source_adapter", "official_edu"),
    }


async def discover_official_source_links(req: SearchPaperSourcesRequest, max_links_per_seed: int = 8) -> list[dict[str, str]]:
    """从官方/学校 seed 入口页抽取疑似试卷链接，作为搜索引擎不稳定时的补源候选。"""
    seeds = build_official_source_site_seeds(req)
    candidates: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=settings.config.question_bank.search_timeout_seconds, headers={"User-Agent": _USER_AGENT}, follow_redirects=True) as client:
        for seed in seeds:
            seed_url = seed.get("url") or f"https://{seed['domain']}/"
            try:
                resp = await client.get(seed_url)
                resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                logger.warning("官方来源 seed 抓取失败：url=%s error=%s", seed_url, exc)
                continue
            parser = _OfficialLinkParser(str(resp.url))
            parser.feed(resp.text)
            matched = 0
            for link in parser.links:
                if not _same_or_child_domain(link.get("url", ""), seed["domain"]):
                    continue
                item = _candidate_from_official_link(seed, link, req)
                if _looks_like_paper_link(item, req):
                    candidates.append(item)
                    matched += 1
                if matched >= max_links_per_seed:
                    break
    deduped = _dedupe_candidates(candidates)
    deduped.sort(key=lambda item: _score_candidate(item, req), reverse=True)
    return deduped[: req.limit]


def build_official_source_queries(req: SearchPaperSourcesRequest) -> list[str]:
    """更偏官方/学校入口的查询，不替代通用搜索，用于扩源审计和补漏。"""
    exam_type = req.exam_type or "期末"
    core = " ".join(x for x in [req.grade, req.semester, req.subject, exam_type] if x)
    queries: list[str] = []
    if req.school:
        school_aliases = _school_query_aliases(req.school)
        queries.extend(
            [
                f'site:edu.cn "{req.school}" {core} 试卷',
                f'"{req.school}" 教务 {core}',
                f'"{req.school}" {core} PDF',
            ]
        )
        for seed in build_official_source_site_seeds(req):
            for alias in school_aliases:
                queries.append(f'site:{seed["domain"]} "{alias}" {core}')
    if req.district:
        queries.extend(
            [
                f'site:sipac.gov.cn "{req.district}" {core} 试卷',
                f'site:sipac.gov.cn "{req.district}" {core} 教研',
                f'site:edu.sipac.gov.cn "{req.district}" {core} 试卷',
                f'site:tdc.sipedu.cn "{req.district}" {core} 教研',
                f'"{req.district}" 教育局 {core} 试卷 PDF',
                f'"{req.district}" 教师发展中心 {core} 试卷',
            ]
        )
    if req.city:
        queries.extend(
            [
                f'site:jyj.suzhou.gov.cn "{req.city}" {core} 试卷',
                f'site:suzhou.gov.cn "{req.city}" {core} 学业质量调研',
            ]
        )
    queries.extend(
        [
            f'site:gov.cn "{req.district or req.city or req.province or ""}" {core} 试卷',
            f'site:edu.cn "{req.district or req.city or req.province or ""}" {core} 试卷',
        ]
    )
    return _dedupe_queries([_clean_text(q) for q in queries if _clean_text(q)])


async def search_public_paper_candidates(req: SearchPaperSourcesRequest, max_queries: int | None = None) -> tuple[list[str], list[dict[str, str]]]:
    """搜索公开网页候选。失败时返回搜索 URL 兜底候选。"""
    queries = _dedupe_queries([*build_paper_search_queries(req), *build_official_source_queries(req)])
    if max_queries is not None:
        queries = queries[: max(1, max_queries)]
    candidates: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=settings.config.question_bank.search_timeout_seconds, headers={"User-Agent": _USER_AGENT}, follow_redirects=True) as client:
        try:
            for item in await _search_yidianedu(client, req):
                if _is_relevant_candidate(item, req):
                    candidates.append(item)
        except Exception as exc:  # noqa: BLE001
            logger.warning("一点升学试卷候选搜索失败：error=%s", exc)

        for query in queries:
            try:
                resp = await client.get("https://www.bing.com/search", params={"q": query})
                resp.raise_for_status()
                for item in _parse_bing_results(resp.text):
                    item["query"] = query
                    item["source_adapter"] = _adapter_from_query(query, item)
                    if _is_relevant_candidate(item, req):
                        candidates.append(item)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Bing 试卷候选搜索失败：query=%s error=%s", query, exc)
            try:
                resp = await client.get("https://duckduckgo.com/html/", params={"q": query})
                resp.raise_for_status()
                parser = _DuckDuckGoParser()
                parser.feed(resp.text)
                for item in parser.results:
                    item["query"] = query
                    item["source_adapter"] = _adapter_from_query(query, item)
                    candidates.append(item)
            except Exception as exc:  # noqa: BLE001
                logger.warning("试卷候选搜索失败：query=%s error=%s", query, exc)

    if not candidates:
        candidates = [
            {
                "title": f"搜索候选：{query}",
                "url": f"https://duckduckgo.com/?q={quote_plus(query)}",
                "snippet": "搜索引擎不可用或暂无解析结果，可人工打开继续查找。",
                "query": query,
                "source_adapter": "manual_search",
            }
            for query in queries
        ]
    deduped = _dedupe_candidates(candidates)
    deduped.sort(key=lambda item: _score_candidate(item, req), reverse=True)
    return queries, deduped[: req.limit]


def save_paper_candidates(
    db: Session, req: SearchPaperSourcesRequest, candidates: list[dict[str, str]], created_by: int | None
) -> list[QuestionBankPaper]:
    saved: list[QuestionBankPaper] = []
    for item in candidates:
        title = _clean_text(item.get("title", ""))[:300]
        url = item.get("url", "").strip()
        snippet = _clean_text(item.get("snippet", ""))
        if not title or not url:
            continue
        source_type, availability, risk, confidence = _classify_candidate(title, url, snippet)
        url_hash = _hash_url(url)
        existing = db.query(QuestionBankPaper).filter(QuestionBankPaper.source_url_hash == url_hash).first()
        if existing:
            saved.append(existing)
            continue
        paper = QuestionBankPaper(
            title=title,
            source_url=url,
            source_url_hash=url_hash,
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
            availability_level=availability,
            risk_level=risk,
            status="internal_style" if availability == "C" else "candidate",
            confidence=confidence,
            created_by=created_by,
            raw_meta={"query": item.get("query", ""), "source_adapter": item.get("source_adapter", "unknown")},
        )
        db.add(paper)
        db.flush()
        saved.append(paper)
    db.commit()
    return saved
