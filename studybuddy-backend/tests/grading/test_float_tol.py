from app.core.grading import grade_float_tol


def test_float_within_eps():
    result = grade_float_tol("3.14", "3.1415", {"float_eps": 0.01})
    assert result.matched is True


def test_float_beyond_eps():
    result = grade_float_tol("3.0", "3.5", {"float_eps": 0.01})
    assert result.matched is False


def test_float_non_number():
    result = grade_float_tol("abc", "3.14", {"float_eps": 0.01})
    assert result.matched is False
