import importlib.util
import json
from pathlib import Path


def _load_script_module():
    path = Path(__file__).parents[2] / "scripts" / "evaluate_photo_markdown_samples.py"
    spec = importlib.util.spec_from_file_location("evaluate_photo_markdown_samples", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summarize_samples_scores_student_answer_and_uncertain_review():
    module = _load_script_module()
    samples = [
        {
            "label_status": "human_reviewed",
            "recognized_markdown": "1. 计算 2+3。\n学生作答：5\n## 学生作答核对\n- 第1题：学生作答已识别为 5",
            "manual_questions": [
                {"no": "1", "student_answer": "5", "answer_unclear": False},
            ],
        },
        {
            "label_status": "human_reviewed",
            "recognized_markdown": "2. 计算 8-3。\n学生作答：[?]\n## 学生作答核对\n- 第2题：学生作答需要确认",
            "manual_questions": [
                {"no": "2", "student_answer": "5", "answer_unclear": True},
            ],
        },
        {
            "label_status": "human_reviewed",
            "recognized_markdown": "3. 选择正确读数。\n学生作答：B",
            "manual_questions": [
                {"no": "3", "student_answer": "C", "answer_unclear": False},
            ],
        },
    ]

    summary = module.summarize_samples(samples)

    assert summary["total_samples"] == 3
    assert summary["manual_question_count"] == 3
    assert summary["recognized_answer_count"] == 3
    assert summary["student_answer_exact_match_count"] == 1
    assert summary["student_answer_exact_match_rate"] == 0.3333
    assert summary["manual_unclear_count"] == 1
    assert summary["recognized_unclear_count"] == 1
    assert summary["unclear_recall_rate"] == 1


def test_jsonl_roundtrip_keeps_chinese(tmp_path):
    module = _load_script_module()
    path = tmp_path / "photo-samples.jsonl"
    rows = [
        {
            "photo_path": "/tmp/wechat.jpg",
            "recognized_markdown": "学生作答：不确定",
            "manual_questions": [{"no": "1", "student_answer": "A", "answer_unclear": True}],
        }
    ]

    module.write_jsonl(path, rows)
    loaded = module.load_jsonl(path)

    assert loaded == rows
    assert "学生作答" in path.read_text(encoding="utf-8")


def test_extract_student_answers_keeps_exercise_heading_and_sub_question_no():
    module = _load_script_module()
    markdown = """
### 【学以致用1】
(1) 刻度尺的分度值为 __cm，长度是 __cm。
学生作答：分度值 0.1cm，长度 2.35cm。

(2) 秒表显示的时间是 __min __s。
学生作答：1 min 39.5 s。

### 【学以致用2】
使用受潮后的木尺测量物体长度。
学生作答：偏大、误差、不能。
"""

    answers = module.extract_student_answers(markdown)

    assert answers == {
        "学以致用1(1)": "分度值0.1cm，长度2.35cm",
        "学以致用1(2)": "1min39.5s",
        "学以致用2": "偏大、误差、不能",
    }


def test_summarize_samples_matches_composite_manual_question_no():
    module = _load_script_module()
    samples = [
        {
            "label_status": "human_reviewed",
            "recognized_markdown": """
### 【学以致用1】
(1) 刻度尺读数。
学生作答：2.35cm。
""",
            "manual_questions": [
                {"no": "学以致用1(1)", "student_answer": "2.35cm", "answer_unclear": False},
            ],
        }
    ]

    summary = module.summarize_samples(samples)

    assert summary["recognized_answer_count"] == 1
    assert summary["student_answer_exact_match_count"] == 1
    assert summary["student_answer_exact_match_rate"] == 1


def test_summarize_samples_counts_label_review_status():
    module = _load_script_module()
    samples = [
        {"label_status": "vision_assisted_pending_human_review", "recognized_markdown": "", "manual_questions": []},
        {"label_status": "human_reviewed", "recognized_markdown": "", "manual_questions": []},
    ]

    summary = module.summarize_samples(samples)

    assert summary["by_label_status"] == {"vision_assisted_pending_human_review": 1, "human_reviewed": 1}
    assert summary["human_reviewed_samples"] == 1
    assert summary["pending_human_review_samples"] == 1


def test_summarize_samples_only_scores_human_reviewed_by_default():
    module = _load_script_module()
    samples = [
        {
            "label_status": "vision_assisted_pending_human_review",
            "photo_path": "/tmp/pending.jpg",
            "recognized_markdown": "1. 选择题。\n学生作答：A",
            "manual_questions": [{"no": "1", "student_answer": "A", "answer_unclear": False}],
        },
        {
            "label_status": "human_reviewed",
            "photo_path": "/tmp/reviewed.jpg",
            "recognized_markdown": "1. 选择题。\n学生作答：B",
            "manual_questions": [{"no": "1", "student_answer": "B", "answer_unclear": False}],
        },
    ]

    summary = module.summarize_samples(samples)

    assert summary["total_samples"] == 2
    assert summary["evaluated_samples"] == 1
    assert summary["skipped_pending_samples"] == 1
    assert summary["manual_question_count"] == 1
    assert summary["student_answer_exact_match_rate"] == 1
    assert summary["by_photo"] == [
        {
            "photo_path": "/tmp/reviewed.jpg",
            "label_status": "human_reviewed",
            "manual_question_count": 1,
            "recognized_answer_count": 1,
            "student_answer_exact_match_count": 1,
            "recognized_unclear_count": 0,
            "answer_risk_count": 0,
            "missing_answer_count": 0,
        }
    ]


def test_summarize_samples_reports_wrong_guess_and_missing_answer_details():
    module = _load_script_module()
    samples = [
        {
            "label_status": "human_reviewed",
            "photo_path": "/tmp/wrong.jpg",
            "recognized_markdown": "1. 选择题。\n学生作答：D\n2. 填空题。",
            "manual_questions": [
                {"no": "1", "student_answer": "B", "answer_unclear": False},
                {"no": "2", "student_answer": "不能", "answer_unclear": False},
            ],
        },
        {
            "label_status": "human_reviewed",
            "photo_path": "/tmp/unclear.jpg",
            "recognized_markdown": "1. 手写题。\n学生作答：C",
            "manual_questions": [{"no": "1", "student_answer": "", "answer_unclear": True}],
        },
    ]

    summary = module.summarize_samples(samples)

    assert summary["answer_risk_count"] == 2
    assert summary["missing_answer_count"] == 1
    assert summary["unclear_recall_rate"] == 0
    assert summary["failure_details"] == [
        {
            "photo_path": "/tmp/wrong.jpg",
            "no": "1",
            "type": "wrong_student_answer",
            "manual_answer": "B",
            "recognized_answer": "D",
        },
        {
            "photo_path": "/tmp/wrong.jpg",
            "no": "2",
            "type": "missing_student_answer",
            "manual_answer": "不能",
            "recognized_answer": "",
        },
        {
            "photo_path": "/tmp/unclear.jpg",
            "no": "1",
            "type": "unclear_answer_guessed",
            "manual_answer": "",
            "recognized_answer": "C",
        },
    ]
