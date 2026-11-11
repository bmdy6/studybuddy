"""错题导入 live 测试：真实调用 MiMo，验证 agent 工具选择/参数提取 + 视觉解析效果与速度。

⚠️ 标记 @pytest.mark.live：默认 skip，带 --run-live 才跑（耗 token、需网络+真实 key）。
跑法：.venv/bin/python -m pytest tests/live/ --run-live -s --no-cov

两类测试：
1. TestErrorImportAgentFlow：真实 MiMo 跑 agent_loop，验证从自然语言对话里
   - 正确选工具（import_errors_process / import_errors_grade）
   - 正确提取参数（batch_id、grade_mode、manual_scores 题号/分数）
   这是防幻觉测试——agent 不能编 batch_id、不能传错 grade_mode、不能把题号搞成数字。
2. TestVisionParseLive：真实照片走 import_errors_process，看识别准不准 + 耗时。
"""

import asyncio
import json
import os
import time
from typing import Any

import pytest

from app.features.agent import agent_loop
from app.database import SessionLocal
from app.models.chat import ChatSession
from app.models.exam_batch import ExamBatch
from app.features.exams import batch_service as exam_batch_service

# 真实试卷照片（开发期留存的）
TEST_PHOTO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "uploads",
    "materials",
    "exams",
    "2_英语_诊断卷_2026-06-28",
)
TEST_PHOTO = os.path.join(TEST_PHOTO_DIR, "01_答题卡_第1页.jpg")

# 测试用学生/家长（init_users.py 建的固定账号）
TEACHER_ID = 1
STUDENT_ID = 2


def _extract_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 agent_loop 返回的 messages 里抽出所有 assistant 发起的工具调用。"""
    calls = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                calls.append({"name": fn.get("name"), "args": args})
    return calls


@pytest.mark.live
class TestErrorImportAgentFlow:
    """agent 幻觉测试：真实 MiMo，验证工具选择 + 参数提取。"""

    def test_process_tool_triggered_by_batch_id_message(self, db):
        """用户发「已上传到批次 #N，请解析」→ agent 应调 import_errors_process(batch_id=N)。

        防幻觉点：不能调别的工具、不能编 batch_id、参数要对。
        """
        batch_id = 999  # 故意用不存在的 id，看 agent 是否原样透传（不编造）
        user_msg = f"[错题导入] 已上传 2 张照片到批次 #{batch_id}（英语 U5 测验），请解析并帮我判分入错题本。"

        messages = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": user_msg}],
                "teacher",
                db,
                TEACHER_ID,
                student_id=STUDENT_ID,
            )
        )

        calls = _extract_tool_calls(messages)
        process_calls = [c for c in calls if c["name"] == "import_errors_process"]
        assert process_calls, f"应调 import_errors_process，实际调了: {[c['name'] for c in calls]}"
        # batch_id 必须原样透传，不能编造
        assert process_calls[0]["args"].get("batch_id") == batch_id, f"batch_id 应为 {batch_id}，实际: {process_calls[0]['args'].get('batch_id')}"

    def test_grade_tool_extracts_mode_and_scores_from_natural_language(self, db):
        """用户说「有分数，第3题65分，第5题0分」→ agent 应调 import_errors_grade。

        防幻觉点：
        - grade_mode 必须是 has_score（不能瞎选 no_score_no_answer）
        - manual_scores 必须含 {"3": 65, "5": 0}（题号是字符串、分数是数字）
        - 不能把「第3题」理解成题号=3 之外的怪东西
        - batch_id 要带上（前文给过）
        """
        batch_id = 888
        # 先给 agent 上下文：已解析出题，现在用户给判分信息
        messages_seed = [
            {"role": "user", "content": f"[错题导入] 已上传照片到批次 #{batch_id}，请解析。"},
            # 模拟 process 工具已返回（让 agent 知道有题、batch_id 是多少）
            {"role": "assistant", "content": "已解析出题目，请问试卷上有老师打的分数吗？"},
            {"role": "user", "content": "有分数，第3题65分，第5题0分，帮我入错题本"},
        ]

        messages = asyncio.run(
            agent_loop.agent_loop(
                messages_seed,
                "teacher",
                db,
                TEACHER_ID,
                student_id=STUDENT_ID,
            )
        )

        calls = _extract_tool_calls(messages)
        grade_calls = [c for c in calls if c["name"] == "import_errors_grade"]
        assert grade_calls, f"应调 import_errors_grade，实际调了: {[c['name'] for c in calls]}"

        args = grade_calls[0]["args"]
        assert args.get("grade_mode") == "has_score", f"grade_mode 应为 has_score，实际: {args.get('grade_mode')}"
        assert args.get("batch_id") == batch_id, f"batch_id 应为 {batch_id}，实际: {args.get('batch_id')}"
        manual = args.get("manual_scores") or {}
        # 题号 3→65、5→0（容忍 key 是 str/int，分数是 int/float/str）
        assert int(manual.get("3", manual.get(3, -1))) == 65, f"第3题分数应为 65，实际: {manual}"
        assert int(manual.get("5", manual.get(5, -1))) == 0, f"第5题分数应为 0，实际: {manual}"

    def test_no_score_no_answer_mode_when_user_says_neither(self, db):
        """用户说「都没有分数和答案」→ grade_mode 应为 no_score_no_answer，不传 manual_scores。"""
        batch_id = 777
        messages_seed = [
            {"role": "user", "content": f"[错题导入] 已上传照片到批次 #{batch_id}，请解析。"},
            {"role": "assistant", "content": "已解析出题目，请问试卷上有老师打的分数吗？还是有标准答案？"},
            {"role": "user", "content": "都没有，直接入错题本吧"},
        ]

        messages = asyncio.run(
            agent_loop.agent_loop(
                messages_seed,
                "teacher",
                db,
                TEACHER_ID,
                student_id=STUDENT_ID,
            )
        )

        calls = _extract_tool_calls(messages)
        grade_calls = [c for c in calls if c["name"] == "import_errors_grade"]
        assert grade_calls, f"应调 import_errors_grade，实际: {[c['name'] for c in calls]}"
        args = grade_calls[0]["args"]
        assert args.get("grade_mode") == "no_score_no_answer", f"grade_mode 应为 no_score_no_answer，实际: {args.get('grade_mode')}"


@pytest.mark.live
class TestVisionParseLive:
    """视觉解析真实效果 + 速度：真实照片走 import_errors_process。"""

    def test_vision_parse_real_photo_returns_questions_and_timed(self, db):
        """用真实试卷照片走完整 process：建批次→上传→合成→解析，看识别结果 + 耗时。

        速度基线：单张照片视觉解析应 < 30s（前端设了 90s 超时，留 3 倍余量）。
        效果基线：应识别出至少 1 道题（题号/作答非空）。
        """
        if not os.path.exists(TEST_PHOTO):
            pytest.skip(f"测试照片不存在: {TEST_PHOTO}")

        # 建批次 + 上传真实照片
        batch_item = exam_batch_service.create_batch(db, STUDENT_ID, "english", "live视觉测试卷", "2026-06-30")
        batch = exam_batch_service.get_batch(db, batch_item.id)  # ORM 模型，用于清理
        with open(TEST_PHOTO, "rb") as f:
            data = f.read()
        exam_batch_service.save_photo_to_batch(db, batch, "01_答题卡_第1页.jpg", data, TEACHER_ID, "试卷")

        try:
            # 计时：合成 + 视觉解析
            t0 = time.time()
            # 直接调 service（绕过 agent，纯测视觉链路速度）
            exam_batch_service.synthesize_pdf(db, batch)
            result = asyncio.run(exam_batch_service.parse_photos_with_vision(db, batch))
            elapsed = time.time() - t0

            print(f"\n[视觉解析] 耗时 {elapsed:.1f}s，识别 {len(result.questions)} 道题")
            for q in result.questions[:5]:
                print(f"  题{q.no}: 作答={q.answer[:40]!r} 分数={q.score}")

            assert elapsed < 30, f"视觉解析耗时 {elapsed:.1f}s 超过 30s 基线"
            assert len(result.questions) >= 1, f"应识别出至少 1 道题，实际 {len(result.questions)}"
            # 每题题号/作答应非空
            for q in result.questions:
                assert q.no.strip(), f"题号为空: {q}"
                assert q.answer.strip() or q.score, f"题 {q.no} 作答和分数都空"
        finally:
            # 清理：删批次记录（照片文件留档，不删）
            db.query(ExamBatch).filter(ExamBatch.id == batch_item.id).delete()
            db.commit()
