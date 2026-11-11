"""HOBBY_TOOLS：兴趣空间工具集。

v1 定位 = 资源推荐对话：用户说想学什么 → AI 搜真实 B站资源推荐。
核心只留 search_hobby_resource；练习/作品记录不建表不落库，在对话里聊。
机制模仿底座 tools.py（_TOOL_* schema + 角色可见集），不暴露出卷/判分/错题等学科工具。
"""

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------- 工具 schema ----------

_TOOL_SEARCH_RESOURCE = {
    "name": "search_hobby_resource",
    "description": (
        "搜 B站真实学习资源（唱歌/乐器/配音/口语等兴趣教程）。"
        "你只需提供搜索关键词（如「唱歌 气息练习 教程」），后端会真实搜 B站返回 Top 视频"
        "（含标题/UP主/播放量/链接/简介/弹幕采样）。"
        "返回的候选带简介和弹幕采样——你要据此判断内容是否匹配用户兴趣，过滤明显不合适的"
        "（如娱乐向、无关内容）。在回复里推荐 1-2 个并说明理由，必须给出完整可点击链接。"
        "不要编造 URL 或给搜索页链接。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "B站搜索关键词，尽量精确如「唱歌 气息练习 教程」",
            },
            "reason": {
                "type": "string",
                "description": "推荐理由（结合用户想学的兴趣）",
            },
        },
        "required": ["keyword"],
    },
}

HOBBY_TOOLS = [_TOOL_SEARCH_RESOURCE]

# ---------- 工具实现 ----------


def _require_user_id(user_id: int | None) -> int:
    if not user_id:
        raise ValueError("缺少用户身份")
    return user_id


async def handle_search_resource(args: dict, db: Session, user_id: int | None) -> dict:
    """搜 B站真实资源（复用底座 bili_search_service），返回候选给 AI 推荐，不落库。

    搜索设施是通用层：底座 search_and_enrich 纯搜索、无学习表依赖，兴趣空间直接复用。
    搜索失败/无结果时结构化返回，AI 如实说明，不编造 URL。
    """
    _require_user_id(user_id)
    keyword = (args.get("keyword") or "").strip()
    if not keyword:
        return {"ok": False, "error": "请提供搜索关键词 keyword"}
    try:
        # 底座：B站搜索+简介/弹幕预审（匿名，无需 Cookie）
        from app.features.question_bank.bili_search_service import search_and_enrich

        candidates = await search_and_enrich(keyword)
    except Exception as exc:  # noqa: BLE001 - 外部搜索失败必须结构化返回，不吞
        logger.warning("兴趣资源搜索失败 keyword=%s: %s", keyword, exc)
        return {"ok": False, "error": "资源搜索暂时不可用，请稍后再试或换个关键词"}
    if not candidates:
        return {"ok": False, "error": "没搜到合适的视频，换个关键词试试", "keyword": keyword}
    return {
        "ok": True,
        "keyword": keyword,
        "candidates": [
            {
                "title": c["title"],
                "url": c["url"],
                "author": c["author"],
                "play": c["play"],
                "desc": c.get("desc", ""),
                "danmaku_sample": c.get("danmaku_sample", [])[:5],
            }
            for c in candidates
        ],
    }


TOOL_HANDLERS = {
    "search_hobby_resource": handle_search_resource,
}
