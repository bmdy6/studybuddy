"""Agent 素材边界 live 测试：真实 MiMo 验证 AI 不暗示能爬虫抓取素材。

⚠️ @pytest.mark.live：默认 skip，带 --run-live 才跑（耗 token、需网络+真实 key）。
跑法：.venv/bin/python -m pytest tests/live/test_material_no_crawl_live.py --run-live -s --no-cov

回归场景：用户想要某份学习资料（如「书本第166页的单词表」）但还没上传素材时，
AI 不能暗示自己能去网上爬取/抓取/下载来获取素材，必须引导用户自己点相机按钮上传文件。
根因：素材链路 100% 是用户上传文件，后端没有任何「给 URL 让 AI 抓」的入口；
但旧 prompt 缺少明确的「你不能爬」边界声明，AI 在用户要资料时有暗示能抓的风险。
"""

import asyncio
import json
from typing import Any

import pytest

from app.features.agent import agent_loop

STUDENT_ID = 2


def _extract_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 agent_loop 返回消息中抽取 assistant 发起的工具调用及参数。"""
    calls = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tool_call in msg.get("tool_calls") or []:
            function = tool_call.get("function", {})
            try:
                args = json.loads(function.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            calls.append({"name": function.get("name"), "args": args})
    return calls


def _assistant_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(str(msg.get("content") or "") for msg in messages if msg.get("role") == "assistant")


@pytest.mark.live
class TestMaterialNoCrawlLive:
    """真实 MiMo 验证：用户要资料但没上传时，AI 引导上传，不暗示能爬虫/抓取。"""

    def test_student_wants_material_is_guided_to_upload_not_crawl(self, db):
        """学生想要单词表但没上传素材时，AI 应引导上传，不能暗示能爬取/抓取。"""
        messages = asyncio.run(
            agent_loop.agent_loop(
                [
                    {
                        "role": "user",
                        "content": "我要译林版八年级上册第一单元的单词表，帮我整理一下",
                    }
                ],
                "student",
                db,
                STUDENT_ID,
            )
        )

        calls = _extract_tool_calls(messages)
        call_names = [call["name"] for call in calls]
        text = _assistant_text(messages)

        # 硬性断言：用户没上传素材时，AI 不应调用爬虫工具 search_paper_sources
        # （那是题库建库用的，且学生角色根本没权限；更不该用来取学习素材）
        assert "search_paper_sources" not in call_names, (
            f"学生要学习素材不应调爬虫工具 search_paper_sources，实际调了: {call_names}"
        )

        # 不应在没素材的情况下直接调 read_material（没 material_id 可读）
        # 也不应自作主张调 save_note 生成一份「通用单词表」笔记
        assert "read_material" not in call_names, (
            f"用户没上传素材不应调 read_material，实际调了: {call_names}"
        )

        # 回复不应出现暗示能爬取/抓取/下载网页的措辞
        forbidden_phrases = [
            "帮你找",
            "帮你抓",
            "帮你爬",
            "我去网上",
            "我帮你下载",
            "抓取网页",
            "爬取",
            "搜索并整理",
        ]
        for phrase in forbidden_phrases:
            assert phrase not in text, (
                f"回复不应出现暗示能爬取的措辞「{phrase}」：{text}"
            )

        # 回复应引导用户上传素材（提到相机按钮/上传素材/拍照之一）
        upload_hints = ["上传素材", "相机", "拍照", "选文件"]
        assert any(hint in text for hint in upload_hints), (
            f"用户要资料但没上传时，应引导上传素材，回复里没出现上传引导：{text}"
        )
