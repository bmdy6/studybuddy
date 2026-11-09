"""试卷来源 HTML 解析与文本工具层（从 search_service 拆出，提升内聚）。

解析 DuckDuckGo / Bing / 一点升学的搜索结果 HTML，抽取标题、URL、摘要；
提供文本清洗、URL 解包、题目数量估算等纯函数工具，不含网络与评分逻辑。
"""

from __future__ import annotations

import base64
import html
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlparse

_YIDIANEDU_BASE = "https://www.yidianedu.com"


class _DuckDuckGoParser(HTMLParser):
    """提取 DuckDuckGo HTML 搜索结果。"""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_link = False
        self._in_snippet = False
        self._current_href = ""
        self._current_title: list[str] = []
        self._current_snippet: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        classes = attr.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._in_link = True
            self._current_href = attr.get("href", "")
            self._current_title = []
            self._current_snippet = []
        if tag in {"a", "div"} and "result__snippet" in classes:
            self._in_snippet = True

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._current_title.append(data)
        elif self._in_snippet:
            self._current_snippet.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            title = _clean_text("".join(self._current_title))
            url = _extract_duckduckgo_url(self._current_href)
            if title and url:
                self.results.append({"title": title, "url": url, "snippet": _clean_text("".join(self._current_snippet))})
            self._in_link = False
        if self._in_snippet and tag in {"a", "div"}:
            self._in_snippet = False


class _OfficialLinkParser(HTMLParser):
    """提取官方/学校页面里的链接文本和 URL。"""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr = {k: v or "" for k, v in attrs}
        href = attr.get("href", "")
        if href:
            self._href = urljoin(self.base_url, html.unescape(href))
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._href:
            return
        title = _clean_text("".join(self._text))
        if title:
            self.links.append({"title": title, "url": self._href})
        self._href = ""
        self._text = []


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _extract_duckduckgo_url(href: str) -> str:
    if not href:
        return ""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return unquote(query["uddg"][0])
    return href if parsed.scheme in {"http", "https"} else ""


def _extract_bing_url(href: str) -> str:
    """Bing 结果常用 /ck/a 包装真实 URL，u=a1<base64url>。"""
    parsed = urlparse(html.unescape(href or ""))
    if "bing.com" not in parsed.netloc:
        return href
    target = parse_qs(parsed.query).get("u", [""])[0]
    if target.startswith("a1"):
        encoded = target[2:]
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        try:
            return base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        except Exception:  # noqa: BLE001
            return href
    return href


def _strip_tags(value: str) -> str:
    return _clean_text(re.sub(r"<.*?>", "", value or "", flags=re.S))


def _looks_like_pdf(content_type: str, url: str, data: bytes) -> bool:
    return "pdf" in content_type.lower() or url.lower().split("?", 1)[0].endswith(".pdf") or data.startswith(b"%PDF")


def _extract_visible_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw_html)
    return _strip_tags(text)


def _estimate_question_count(text: str) -> tuple[int, str | None]:
    patterns = [
        r"(?:^|[\s。；;])([一二三四五六七八九十]+)[、.．]\s*",
        r"(?:^|[\s。；;])(\d{1,2})[、.．]\s*",
        r"(?:第\s*(\d{1,2})\s*题)",
    ]
    numbers: set[int] = set()
    chinese_map = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            token = match.group(1)
            if token.isdigit():
                number = int(token)
            elif token == "十":
                number = 10
            elif token.startswith("十") and len(token) == 2:
                number = 10 + chinese_map.get(token[1], 0)
            elif token.endswith("十") and len(token) == 2:
                number = chinese_map.get(token[0], 0) * 10
            elif "十" in token and len(token) == 3:
                number = chinese_map.get(token[0], 0) * 10 + chinese_map.get(token[2], 0)
            else:
                number = chinese_map.get(token, 0)
            if 1 <= number <= 80:
                numbers.add(number)
    if not numbers and "题号" in text:
        for match in re.finditer(r"(?<![A-Za-z])(?:^|\s)(\d{1,2})\s+(?=[A-Za-z\u4e00-\u9fff（(])", text):
            number = int(match.group(1))
            if 1 <= number <= 80:
                numbers.add(number)
    if not numbers:
        return 0, None
    return len(numbers), str(max(numbers))


def _parse_bing_results(raw_html: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for match in re.finditer(r'<li class="b_algo".*?</li>', raw_html, flags=re.S):
        block = match.group(0)
        link = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.S)
        if not link:
            continue
        snippet = re.search(r"<p[^>]*>(.*?)</p>", block, flags=re.S)
        title = _strip_tags(link.group(2))
        url = _extract_bing_url(link.group(1))
        if not title or not url:
            continue
        results.append({"title": title, "url": url, "snippet": _strip_tags(snippet.group(1)) if snippet else ""})
    return results


def _grade_for_yidianedu(grade: str) -> str:
    if "七" in grade or "初一" in grade:
        return "初一"
    if "八" in grade or "初二" in grade:
        return "初二"
    if "九" in grade or "初三" in grade:
        return "初三"
    return grade


def _type_id_for_yidianedu(exam_type: str | None) -> str:
    if exam_type and "期中" in exam_type:
        return "4"
    if exam_type and "月考" in exam_type:
        return "3"
    return "5"


def _parse_yidianedu_results(raw_html: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for match in re.finditer(r'<li class="page-professional-item.*?</li>', raw_html, flags=re.S):
        block = match.group(0)
        link = re.search(r'<a href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.S)
        if not link:
            continue
        meta = re.search(r'<p class="page-school-level[^"]*">(.*?)</p>', block, flags=re.S)
        title = _strip_tags(link.group(2))
        href = link.group(1)
        url = href if href.startswith("http") else f"{_YIDIANEDU_BASE}{href}"
        results.append({"title": title, "url": url, "snippet": _strip_tags(meta.group(1)) if meta else ""})
    return results
