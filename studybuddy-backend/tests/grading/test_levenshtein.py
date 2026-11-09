from app.core.grading import grade_levenshtein


def test_levenshtein_within_tolerance():
    result = grade_levenshtein("wentt", "went", {"tolerance": 2})
    assert result.matched is True


def test_levenshtein_placeholder_dots_do_not_make_correct_multi_blank_answer_wrong():
    result = grade_levenshtein("Did visit", "Did ... visit", {"tolerance": 2})
    assert result.matched is True


def test_levenshtein_beyond_tolerance():
    result = grade_levenshtein("running", "went", {"tolerance": 2})
    assert result.matched is False


def test_levenshtein_accept_alias():
    result = grade_levenshtein("goed", "went", {"tolerance": 1, "accept_aliases": ["goed"], "ignore_case": True})
    assert result.matched is True
