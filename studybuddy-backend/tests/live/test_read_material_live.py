"""素材读取 live 测试：真实 MiMo 视觉，验证 read_material 能识别图片内容。

⚠️ @pytest.mark.live：默认 skip，带 --run-live 才跑。
跑法：.venv/bin/python -m pytest tests/live/ --run-live -s --no-cov

解决问题9：agent 之前说「不能看图片」，现在 read_material 用视觉读素材内容。
本测试用真实上传的图片素材，验证 agent 能识别出内容（单词/主题等）。
"""

import asyncio
import time

import pytest

from app.features.agent import agent_loop
from app.database import SessionLocal

# 用户真实上传的图片素材 id（DB 里已存在）
IMAGE_MATERIAL_ID = 60  # Unit1-2_cottage-lawyer


@pytest.mark.live
class TestReadMaterialLive:
    """read_material 真实视觉识别测试。"""

    def test_read_material_recognizes_image_content(self):
        """真实图片素材走 read_material，验证识别出内容 + 耗时。"""
        db = SessionLocal()
        try:
            t0 = time.time()
            result = asyncio.run(agent_loop._dispatch("read_material", {"material_id": IMAGE_MATERIAL_ID}, "student", db, 2))
            elapsed = time.time() - t0

            print(f"\n[read_material] 耗时 {elapsed:.1f}s")
            print(f"  素材名: {result.get('name')}")
            print(f"  识别内容(前200字): {(result.get('content') or '')[:200]}")

            # 应成功识别（有 content），不返回 error
            assert "error" not in result, f"识别失败: {result.get('error')}"
            assert result.get("content"), "识别内容为空"
            assert elapsed < 30, f"识别耗时 {elapsed:.1f}s 超 30s 基线"
        finally:
            db.close()

    def test_agent_calls_read_material_when_material_uploaded(self, db):
        """用户发带 material_id 的素材消息 → agent 应调 read_material（不再说不能看）。"""
        msg = (
            f"我上传了一份素材「Unit1-2 单词表」（类型：image，material_id={IMAGE_MATERIAL_ID}），"
            "已经存到素材库了。你可以用 read_material 工具看它的内容，然后帮我整理笔记。"
        )
        messages = asyncio.run(agent_loop.agent_loop([{"role": "user", "content": msg}], "student", db, 2))

        # 提取工具调用
        calls = []
        for m in messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    calls.append(tc["function"]["name"])

        print(f"\n[agent 调用工具]: {calls}")
        assert "read_material" in calls, f"应调 read_material，实际调了: {calls}"
