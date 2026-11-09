"""P0 显示协议修复测试：结果页正确答案归一化（数字索引 -> 字母）。"""

from app.features.exams.grading_service import _display_answer


class _FakeQ:
    def __init__(self, qtype, answer_json, options):
        self.type = qtype
        self.answer_json = answer_json
        self.options = options


def test_display_answer_normalizes_choice_index():
    """选择题 answer_json 数字索引 -> 字母（[2] -> C）。"""
    assert _display_answer(_FakeQ("single_choice", [2], ["A", "B", "C", "D"])) == "C"


def test_display_answer_normalizes_choice_letter():
    """选择题 answer_json 已是字母 -> 原样大写。"""
    assert _display_answer(_FakeQ("single_choice", "c", ["A", "B", "C", "D"])) == "C"


def test_display_answer_plain_non_choice():
    """非选择题（填空/数学）答案原样。"""
    assert _display_answer(_FakeQ("fill_blank", "7/12", None)) == "7/12"
