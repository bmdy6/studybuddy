from app.core.grading import GradeResult, grade


class FakeQuestion:
    def __init__(self, score, answer_json, qtype="short_answer", options=None):
        self.score = score
        self.answer_json = answer_json
        self.type = qtype
        self.options = options


class FakeRule:
    def __init__(self, rule_type, matcher="exact", match_params=None):
        self.rule_type = rule_type
        self.matcher = matcher
        self.match_params = match_params or {}


def test_manual_needs_manual_flag():
    q = FakeQuestion(5, "I went to school.")
    r = FakeRule("manual")
    result = grade("any answer", q, r)
    assert result.needs_manual is True
    assert result.is_correct is None
    assert result.score == 0


def test_grade_exact_full_flow():
    q = FakeQuestion(2, "went")
    r = FakeRule("auto_exact", "exact", {"ignore_case": False, "strip_punct": True})
    result = grade("went", q, r)
    assert result.is_correct is True
    assert result.score == 2
    assert result.needs_manual is False


def test_grade_wrong_answer():
    q = FakeQuestion(2, "went")
    r = FakeRule("auto_exact", "exact", {"ignore_case": False, "strip_punct": True})
    result = grade("goed", q, r)
    assert result.is_correct is False
    assert result.score == 0
