"""试卷候选评分、去重与分类（从 search_service 拆出，提升内聚）。

对搜索候选打分（学校/地区/科目/官方来源加权）、去重（URL/查询）、
分类（风险/可用性/来源类型），不含网络抓取与 HTML 解析。
"""

from __future__ import annotations

import hashlib
import re

from .parsers import _clean_text, _grade_for_yidianedu
from .schemas import SearchPaperSourcesRequest

_PAID_OR_UNCLEAR_DOMAINS = ("doc88.com", "book118.com", "baidu.com", "wenku", "zujuan", "21cnjy", "zxxk")
_OFFICIAL_EDU_DOMAINS = (
    ".edu.cn",
    ".gov.cn",
    "edu.sipac.gov.cn",
    "sipac.gov.cn",
    "sipedu.cn",
    "tdc.sipedu.cn",
    "suzhou.gov.cn",
    "jyj.suzhou.gov.cn",
    "jssjys.com",
)


def _is_relevant_candidate(item: dict[str, str], req: SearchPaperSourcesRequest) -> bool:
    text = f"{item.get('title', '')} {item.get('snippet', '')} {item.get('url', '')}".lower()
    grade_tokens = [req.grade, _grade_for_yidianedu(req.grade)]
    subject_hit = req.subject.lower() in text
    grade_hit = any(token and token.lower() in text for token in grade_tokens)
    paper_hit = any(token in text for token in ["试卷", "试题", "真题", "期末", "期中", "统考", "考试"])
    exam_hit = not req.exam_type or req.exam_type.lower() in text
    location_hit = any(token and token.lower() in text for token in [req.school, req.district, req.city])
    known_education_source = "yidianedu.com" in text
    return paper_hit and exam_hit and subject_hit and (grade_hit or location_hit or known_education_source)


def _looks_like_official_edu_source(text: str) -> bool:
    return any(domain in text for domain in _OFFICIAL_EDU_DOMAINS) or any(
        token in text for token in ["教育局", "教研室", "教师发展中心", "学校官网", "校园网"]
    )


def _score_candidate(item: dict[str, str], req: SearchPaperSourcesRequest) -> int:
    text = f"{item.get('title', '')} {item.get('snippet', '')} {item.get('url', '')}".lower()
    score = 0
    for token, points in [
        (req.school, 45),
        (req.district, 35),
        (req.city, 20),
        (req.province, 8),
        (req.grade, 16),
        (_grade_for_yidianedu(req.grade), 16),
        (req.subject, 18),
        (req.exam_type or "期末", 14),
        (req.semester, 10),
        (req.textbook_version, 8),
    ]:
        if token and token.lower() in text:
            score += points
    for token, points in [("含答案", 12), ("答案", 8), ("解析", 8), ("pdf", 6), ("yidianedu.com", 10)]:
        if token in text:
            score += points
    if _looks_like_official_edu_source(text):
        score += 16
    if item.get("source_adapter") in {"school_official", "education_bureau"}:
        score += 10
    if req.semester:
        wants_second_term = any(token in req.semester for token in ["下", "第二"])
        wants_first_term = any(token in req.semester for token in ["上", "第一"])
        if wants_second_term and any(token in text for token in ["上学期", "第一学期"]):
            score -= 18
        if wants_first_term and any(token in text for token in ["下学期", "第二学期"]):
            score -= 18
    if any(domain in text for domain in _PAID_OR_UNCLEAR_DOMAINS):
        score -= 12
    if "duckduckgo.com/?q=" in text:
        score -= 25
    return score


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode("utf-8")).hexdigest()


def _hash_question(stem: str, answer: str | None) -> str:
    normalized = re.sub(r"\s+", "", f"{stem}|{answer or ''}").lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _dedupe_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for query in queries:
        cleaned = _clean_text(query)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _adapter_from_query(query: str, item: dict[str, str]) -> str:
    text = f"{query} {item.get('title', '')} {item.get('snippet', '')} {item.get('url', '')}".lower()
    if "yidianedu.com" in text:
        return "yidianedu"
    if any(token in text for token in ["教育局", "教研", "教师发展中心"]):
        return "education_bureau"
    if "学校" in text or "官网" in text or "教务" in text:
        return "school_official"
    if _looks_like_official_edu_source(text):
        return "official_edu"
    if item.get("url", "").lower().endswith(".pdf") or "pdf" in text:
        return "public_pdf"
    return "web_search"


def _dedupe_candidates(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in candidates:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)
    return deduped


def _classify_candidate(title: str, url: str, snippet: str) -> tuple[str, str, str, int]:
    text = f"{title} {url} {snippet}".lower()
    risk = "medium"
    availability = "B"
    source_type = "web_paper"
    confidence = 55
    if _looks_like_official_edu_source(text):
        risk = "low"
        availability = "A"
        source_type = "district_paper"
        confidence = 72
    if any(token in text for token in ["学校官网", "校园网", "教务"]) and _looks_like_official_edu_source(text):
        source_type = "school_paper"
        confidence = 78
    if any(domain in text for domain in _PAID_OR_UNCLEAR_DOMAINS):
        risk = "high"
        availability = "C"
        source_type = "paid_or_unclear"
        confidence = 35
    if "答案" in title or "含答案" in title or "解析" in title or "answer" in text:
        confidence += 15
    if "pdf" in text:
        confidence += 10
    if "duckduckgo.com/?q=" in url:
        availability = "D"
        risk = "low"
        source_type = "search_result"
        confidence = 20
    return source_type, availability, risk, min(confidence, 95)
