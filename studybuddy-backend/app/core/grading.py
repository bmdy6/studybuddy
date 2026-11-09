"""判分引擎：纯函数模块，无 DB/IO 依赖（约束 #7）。

匹配器（开闭原则，新增走新函数不改老代码）：
- exact：精确匹配，支持去空格/标点/忽略大小写
- levenshtein：编辑距离容错，支持别名
- float_tol：浮点数容差
- manual：标记待人工批改

grade() 是主入口，按 rule.matcher 分派到具体匹配器。
"""

import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.constants import DEFAULT_FLOAT_EPS, DEFAULT_LEVENSHTEIN_TOLERANCE


@dataclass
class MatchResult:
    matched: bool
    detail: str
    correctness: float = 1.0


@dataclass
class GradeResult:
    score: float
    is_correct: bool | None
    detail: str
    needs_manual: bool


class Question(Protocol):
    """协议类型：ORM 模型 Question 满足此结构。"""

    score: Any
    answer_json: Any


class GradingRule(Protocol):
    """协议类型：ORM 模型 GradingRule 满足此结构。"""

    rule_type: str
    matcher: str
    match_params: Any


def _strip_punctuation(s: str) -> str:
    return re.sub(r"[^\w\s]", "", s)


def grade_exact(student_answer: str, correct_answer: str, params: dict) -> MatchResult:
    a, b = student_answer, correct_answer
    if params.get("strip_whitespace", True):
        a, b = a.strip(), b.strip()
        a, b = re.sub(r"\s+", "", a), re.sub(r"\s+", "", b)
    if params.get("strip_punct", True):
        a, b = _strip_punctuation(a), _strip_punctuation(b)
    if params.get("ignore_case", False):
        a, b = a.lower(), b.lower()
    matched = a == b
    return MatchResult(matched, f"exact: '{a}' vs '{b}'")


def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row: list[int] = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def _normalize_gap_placeholders(value: str) -> str:
    """多空题单输入框允许省略题干中的占位符（... / … / ___）。"""
    value = re.sub(r"(?:\.{2,}|…+|_{2,})", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def grade_levenshtein(student_answer: str, correct_answer: str, params: dict) -> MatchResult:
    tolerance = params.get("tolerance", DEFAULT_LEVENSHTEIN_TOLERANCE)
    aliases: list[str] = params.get("accept_aliases", [])
    ignore_case = params.get("ignore_case", True)
    student_answer = _normalize_gap_placeholders(student_answer)
    candidates = [_normalize_gap_placeholders(candidate) for candidate in [correct_answer, *aliases]]
    if ignore_case:
        student_answer = student_answer.lower()
        candidates = [c.lower() for c in candidates]
    for candidate in candidates:
        dist = _levenshtein(student_answer, candidate)
        if dist <= tolerance:
            return MatchResult(True, f"levenshtein: dist={dist} <= {tolerance}")
    return MatchResult(False, f"levenshtein: min dist > {tolerance}")


def grade_float_tol(student_answer: str, correct_answer: str, params: dict) -> MatchResult:
    eps = params.get("float_eps", DEFAULT_FLOAT_EPS)
    try:
        a = float(student_answer.strip())
        b = float(correct_answer.strip())
    except ValueError:
        return MatchResult(False, f"float_tol: 非数字 '{student_answer}'")
    matched = abs(a - b) <= eps
    return MatchResult(matched, f"float_tol: |{a}-{b}|={abs(a - b)} vs eps={eps}")


def _normalize_choice_value(value: Any, option_count: int) -> str:
    """把单个选择题答案归一化为大写字母：0->A, "0"->A, "a"->A。超出范围原样返回。
    判分用：统一大写保留隐式大小写容错（exact 默认 ignore_case=False 仍能容错）。"""
    if value is None:
        return ""
    s = str(value).strip().upper()
    if re.fullmatch(r"\d+", s):
        idx = int(s)
        if 0 <= idx < option_count:
            return chr(ord("A") + idx)
    return s


def _display_choice_value(value: Any, option_count: int) -> str:
    """展示用：单个选择题答案 → 数字索引转字母（0->A）、单字母转大写（a->A）、
    选项文本内容（如 "went"）保持原样不改写大小写，避免结果页正确答案被误大写。"""
    if value is None:
        return ""
    s = str(value).strip()
    if re.fullmatch(r"\d+", s):
        idx = int(s)
        if 0 <= idx < option_count:
            return chr(ord("A") + idx)
        return s
    if len(s) == 1 and s.isalpha():
        return s.upper()
    return s


def _normalize_choice_display(answer: Any, option_count: int) -> str:
    """展示用：选择题答案（索引/字母/文本）→ 索引转字母、单字母转大写、文本保持原样。"""
    if isinstance(answer, list):
        letters = sorted(_display_choice_value(v, option_count) for v in answer if v is not None)
        return "".join(letters)
    return _display_choice_value(answer, option_count)


def _normalize_choice_answer(answer: Any, option_count: int) -> str:
    """归一化选择题答案（索引/字母/列表）为大写字母字符串，如 [0,2]->"AC", "A"->"A"。"""
    if isinstance(answer, list):
        letters = sorted(_normalize_choice_value(v, option_count) for v in answer if v is not None)
        return "".join(letters)
    return _normalize_choice_value(answer, option_count)


def grade(student_answer: str | None, question: Question, rule: GradingRule) -> GradeResult:
    if rule.rule_type == "manual":
        return GradeResult(0, None, "待人工批改", needs_manual=True)

    if student_answer is None or student_answer.strip() == "":
        return GradeResult(0, False, "未作答", needs_manual=False)

    correct = question.answer_json
    if question.type in ("single_choice", "multi_choice") and question.options:
        option_count = len(question.options)
        correct = _normalize_choice_answer(correct, option_count)
        student_answer = _normalize_choice_answer(student_answer, option_count)
    if isinstance(correct, list):
        correct = correct[0] if len(correct) == 1 else str(correct)
    correct = str(correct)

    matcher = rule.matcher
    params = rule.match_params or {}

    if matcher == "exact":
        result = grade_exact(student_answer, correct, params)
    elif matcher == "levenshtein":
        result = grade_levenshtein(student_answer, correct, params)
    elif matcher == "float_tol":
        result = grade_float_tol(student_answer, correct, params)
    else:
        return GradeResult(0, False, f"未知 matcher: {matcher}", needs_manual=False)

    if result.matched:
        return GradeResult(float(question.score) * result.correctness, True, result.detail, False)
    else:
        return GradeResult(0, False, result.detail, False)
