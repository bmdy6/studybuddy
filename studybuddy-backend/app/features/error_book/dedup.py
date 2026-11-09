"""错题去重口径。

错题本展示和历史清理都按同一套指纹归并，避免同一道题因为来自不同试卷/导入批次而重复展示。
"""

import re
from typing import Any


_SPACE_RE = re.compile(r"\s+")
_IMPORT_PREFIX_RE = re.compile(r"^第\s*([0-9一二三四五六七八九十百]+)\s*题[（(]错题导入[）)]作答[:：]\s*", re.IGNORECASE)


def normalize_question_stem(stem: str) -> str:
    """把题干规范成稳定文本，用于错题去重。"""
    text = (stem or "").strip().lower()
    text = text.replace("（", "(").replace("）", ")").replace("：", ":")
    text = _IMPORT_PREFIX_RE.sub("导入作答:", text)
    return _SPACE_RE.sub(" ", text)


def error_fingerprint(subject: str | None, question_type: str | None, stem: str, answer_json: Any = None) -> tuple[str, str, str, str]:
    """同一学生下的错题指纹：学科 + 题型 + 题干 + 答案摘要。"""
    answer_part = ""
    if answer_json is not None:
        answer_part = _SPACE_RE.sub(" ", str(answer_json).strip().lower())
    return ((subject or "未分类").strip().lower(), (question_type or "").strip().lower(), normalize_question_stem(stem), answer_part)
