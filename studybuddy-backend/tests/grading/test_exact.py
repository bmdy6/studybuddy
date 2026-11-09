from app.core.grading import grade_exact


def test_exact_match_ignore_case():
    result = grade_exact("WENT", "went", {"ignore_case": True, "strip_punct": True})
    assert result.matched is True


def test_exact_match_strip_punct():
    result = grade_exact("went.", "went", {"strip_punct": True, "ignore_case": False})
    assert result.matched is True


def test_exact_mismatch():
    result = grade_exact("goed", "went", {"ignore_case": False, "strip_punct": True})
    assert result.matched is False
