"""评估拍题 Markdown 识别稿的真实样本质量。

用法：
  PYTHONPATH=. .venv/bin/python scripts/evaluate_photo_markdown_samples.py \
    --samples /tmp/photo-markdown-samples.jsonl

JSONL 每行建议格式：
  {
    "photo_path": "/path/to/wechat-image.jpg",
    "recognized_markdown": "1. ...\n学生作答：A",
    "manual_questions": [
      {"no": "1", "student_answer": "A", "answer_unclear": false}
    ],
    "manual_note": "圈选答案很淡"
  }

脚本只读样本并汇总，不写数据库。它用于持续评估 U-009：
学生作答是否识别准，不清晰答案是否被要求确认。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def extract_student_answers(markdown: str) -> dict[str, str]:
    answers: dict[str, str] = {}
    current_no = "unknown"
    current_heading = ""
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading_match = re.search(r"【([^】]+)】", line)
        if heading_match:
            current_heading = heading_match.group(1).strip()
            current_no = current_heading
            continue
        no_match = re.match(r"^(?:第)?([（(]?\d+[）)]?)[.、：:\s]", line)
        if no_match and "学生作答" not in line:
            current_no = _join_heading_no(current_heading, no_match.group(1))
        answer_match = re.search(r"学生作答\s*[：:]\s*(.+)", line)
        if answer_match:
            answers[current_no] = _normalize_answer(answer_match.group(1))
    return answers


def _join_heading_no(heading: str, value: Any) -> str:
    no = _normalize_no(value)
    if not heading:
        return no
    if re.fullmatch(r"\d+", no):
        return f"{heading}({no})"
    return f"{heading}{no}"


def _normalize_no(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^第", "", text)
    text = re.sub(r"题$", "", text)
    if re.fullmatch(r"[（(].+[）)]", text):
        text = text[1:-1]
    return text or "unknown"


def _normalize_answer(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", "", text)
    text = text.strip("。.;；")
    return text


def _answer_is_unclear(value: Any) -> bool:
    clean = _normalize_answer(value)
    if not clean:
        return True
    return any(token in clean for token in ("[?]", "？", "?", "不清晰", "看不清", "无法识别", "不确定", "疑似", "模糊"))


def count_recognized_unclear(markdown: str) -> int:
    answer_unclear_count = 0
    for answer in extract_student_answers(markdown).values():
        if _answer_is_unclear(answer):
            answer_unclear_count += 1
    review_unclear_count = 0
    for line in markdown.splitlines():
        if "学生作答需要确认" in line:
            review_unclear_count += 1
    return max(answer_unclear_count, review_unclear_count)


def summarize_samples(samples: list[dict[str, Any]], human_reviewed_only: bool = True) -> dict[str, Any]:
    evaluated_rows: list[dict[str, Any]] = []
    by_label_status: dict[str, int] = {}
    for row in samples:
        label_status = str(row.get("label_status") or "unknown")
        by_label_status[label_status] = by_label_status.get(label_status, 0) + 1
        if human_reviewed_only and label_status != "human_reviewed":
            continue
        evaluated_rows.append(row)

    manual_question_count = 0
    recognized_answer_count = 0
    exact_match_count = 0
    manual_unclear_count = 0
    recognized_unclear_count = 0
    answer_risk_count = 0
    missing_answer_count = 0
    by_photo: list[dict[str, Any]] = []
    failure_details: list[dict[str, Any]] = []

    for row in evaluated_rows:
        markdown = str(row.get("recognized_markdown") or "")
        recognized_answers = extract_student_answers(markdown)
        recognized_unclear_for_sample = count_recognized_unclear(markdown)
        recognized_unclear_count += recognized_unclear_for_sample

        sample_question_count = 0
        sample_match_count = 0
        sample_risk_count = 0
        sample_missing_count = 0
        for question in row.get("manual_questions") or []:
            if not isinstance(question, dict):
                continue
            manual_question_count += 1
            sample_question_count += 1
            no = _normalize_no(question.get("no"))
            manual_answer = _normalize_answer(question.get("student_answer"))
            manual_unclear = bool(question.get("answer_unclear"))
            if manual_unclear:
                manual_unclear_count += 1
            recognized_answer = recognized_answers.get(no)
            if recognized_answer is not None:
                recognized_answer_count += 1
            if recognized_answer and manual_answer and recognized_answer == manual_answer:
                exact_match_count += 1
                sample_match_count += 1
                continue
            if manual_unclear:
                if recognized_answer and not _answer_is_unclear(recognized_answer):
                    answer_risk_count += 1
                    sample_risk_count += 1
                    failure_details.append(
                        {
                            "photo_path": row.get("photo_path"),
                            "no": no,
                            "type": "unclear_answer_guessed",
                            "manual_answer": manual_answer,
                            "recognized_answer": recognized_answer,
                        }
                    )
                continue
            if recognized_answer is None:
                missing_answer_count += 1
                sample_missing_count += 1
                failure_details.append(
                    {
                        "photo_path": row.get("photo_path"),
                        "no": no,
                        "type": "missing_student_answer",
                        "manual_answer": manual_answer,
                        "recognized_answer": "",
                    }
                )
                continue
            if recognized_answer != manual_answer:
                answer_risk_count += 1
                sample_risk_count += 1
                failure_details.append(
                    {
                        "photo_path": row.get("photo_path"),
                        "no": no,
                        "type": "wrong_student_answer",
                        "manual_answer": manual_answer,
                        "recognized_answer": recognized_answer,
                    }
                )

        by_photo.append(
            {
                "photo_path": row.get("photo_path"),
                "label_status": str(row.get("label_status") or "unknown"),
                "manual_question_count": sample_question_count,
                "recognized_answer_count": len(recognized_answers),
                "student_answer_exact_match_count": sample_match_count,
                "recognized_unclear_count": recognized_unclear_for_sample,
                "answer_risk_count": sample_risk_count,
                "missing_answer_count": sample_missing_count,
            }
        )

    return {
        "total_samples": len(samples),
        "evaluated_samples": len(evaluated_rows),
        "skipped_pending_samples": len(samples) - len(evaluated_rows),
        "manual_question_count": manual_question_count,
        "recognized_answer_count": recognized_answer_count,
        "student_answer_exact_match_count": exact_match_count,
        "student_answer_exact_match_rate": round(exact_match_count / manual_question_count, 4)
        if manual_question_count
        else None,
        "manual_unclear_count": manual_unclear_count,
        "recognized_unclear_count": recognized_unclear_count,
        "unclear_recall_rate": round(min(recognized_unclear_count, manual_unclear_count) / manual_unclear_count, 4)
        if manual_unclear_count
        else None,
        "answer_risk_count": answer_risk_count,
        "missing_answer_count": missing_answer_count,
        "failure_details": failure_details,
        "by_label_status": by_label_status,
        "human_reviewed_samples": by_label_status.get("human_reviewed", 0),
        "pending_human_review_samples": sum(
            count for status, count in by_label_status.items() if status != "human_reviewed"
        ),
        "by_photo": by_photo,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="评估拍题 Markdown 识别稿真实样本质量")
    parser.add_argument("--input", "--samples", dest="input", required=True, help="人工标注后的 JSONL 样本")
    parser.add_argument("--include-pending", action="store_true", help="把未人工确认样本也计入指标，仅调试用")
    parser.add_argument("--preview", type=int, default=5, help="输出前几条样本预览")
    args = parser.parse_args()

    samples = load_jsonl(Path(args.input))
    result = {
        "summary": summarize_samples(samples, human_reviewed_only=not args.include_pending),
        "samples": samples[: args.preview],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
