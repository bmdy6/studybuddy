"""验证选择题答案归一化：索引与字母 A/B/C/D 可确定性互转后判分。

关联 bug：[P0-紧急]试卷-AI自练卷答案协议错判.md（correct_answer 存成 [0]/[2]，
学生答 A/C，因未归一化导致明明答对却判 0 分）。
"""

from types import SimpleNamespace

from app.core.grading import grade


def _choice_question(answer_json, options=None, qtype="single_choice", score=5):
    return SimpleNamespace(
        type=qtype,
        options=options or ["选项A", "选项B", "选项C", "选项D"],
        answer_json=answer_json,
        score=score,
    )


def _exact_rule():
    return SimpleNamespace(
        rule_type="auto",
        matcher="exact",
        match_params={"ignore_case": True, "strip_punct": True, "strip_whitespace": True},
    )


def test_single_choice_index_0_vs_A():
    """correct_answer 存索引 [0]，学生答 A，应判对（bug 核心场景）。"""
    q = _choice_question([0])
    r = grade("A", q, _exact_rule())
    assert r.is_correct is True


def test_single_choice_index_2_vs_C():
    """correct_answer [2]，学生答 C，应判对。"""
    q = _choice_question([2])
    r = grade("C", q, _exact_rule())
    assert r.is_correct is True


def test_single_choice_letter_vs_letter():
    """correct_answer 存字母 A，学生答 A，应判对。"""
    q = _choice_question("A")
    r = grade("A", q, _exact_rule())
    assert r.is_correct is True


def test_single_choice_wrong_answer():
    """correct_answer [0]，学生答 B，应判错。"""
    q = _choice_question([0])
    r = grade("B", q, _exact_rule())
    assert r.is_correct is False


def test_multi_choice_index_vs_letters():
    """多选 correct [0,2]，学生答 AC，应判对。"""
    q = _choice_question([0, 2], qtype="multi_choice")
    r = grade("AC", q, _exact_rule())
    assert r.is_correct is True


def test_single_choice_lower_letter():
    """学生答小写 a，correct [0]，应判对（忽略大小写）。"""
    q = _choice_question([0])
    r = grade("a", q, _exact_rule())
    assert r.is_correct is True


def test_single_choice_text_answer_not_uppercased():
    """展示层：选项为文本内容（如 "went"）时归一化不改写大小写，正确答案展示保持原样（P1 修复：
    判分与展示解耦，展示不再把文本答案 upper 成 WENT）。"""
    from app.core.grading import _normalize_choice_display

    assert _normalize_choice_display("went", 4) == "went"
    assert _normalize_choice_display("Went", 4) == "Went"
    assert _normalize_choice_display("I went to school.", 4) == "I went to school."
    # 索引/字母展示归一化保持原行为
    assert _normalize_choice_display(2, 4) == "C"
    assert _normalize_choice_display([0, 2], 4) == "AC"
    assert _normalize_choice_display("a", 4) == "A"


def test_single_choice_text_answer_grade_still_correct():
    """判分层：选项为文本内容时判分仍正确（correct "went" vs 学生 "went" 判对、"goed" 判错）；
    且判分保留大小写容错（默认规则 ignore_case=False 时 "Went" 与 "went" 仍判对）。"""
    from app.core.grading import _normalize_choice_answer

    q = _choice_question("went", options=["go", "goes", "went", "gone"])
    assert grade("went", q, _exact_rule()).is_correct is True
    assert grade("goed", q, _exact_rule()).is_correct is False
    # 默认 case-sensitive 规则下，判分归一化仍统一大写 → 大小写差异不影响判分
    q2 = _choice_question("Went", options=["go", "goes", "went", "gone"])
    assert _normalize_choice_answer("went", 4) == _normalize_choice_answer("Went", 4) == "WENT"
