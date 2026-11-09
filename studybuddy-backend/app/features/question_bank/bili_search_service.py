"""B站视频搜索服务（P2 问题8）。

agent 推荐资源时，用关键词搜 B站拿到具体视频（BV号/标题/UP主/播放量/链接），
而非退化成搜索页 URL。按播放量排序，优先返回权威热门讲解视频。

用 bilibili-api-python 库的 search.search_by_type，匿名搜索（无需 Cookie）。
封装超时与降级：搜索失败时返回空列表，让 agent 退化为提示"暂未找到合适视频"。
"""

import asyncio
import logging

from app.config import settings

logger = logging.getLogger(__name__)


async def search_bilibili_videos(keyword: str) -> list[dict]:
    """按关键词搜 B站视频，返回 Top N 候选（按播放量降序）。

    Args:
        keyword: 搜索关键词，如「英语不规则动词过去式 讲解」

    Returns:
        [{"bvid","title","author","play","duration","url"}]；失败返回 []。
    """
    try:
        # 延迟导入，避免未装库时影响后端启动
        from bilibili_api import search as bili_search
        from bilibili_api.search import OrderVideo, SearchObjectType
    except ImportError:
        logger.warning("bilibili-api 未安装，资源搜索不可用")
        return []

    async def _do_search() -> list[dict]:
        result = await bili_search.search_by_type(
            keyword=keyword,
            search_type=SearchObjectType.VIDEO,
            order_type=OrderVideo.CLICK,  # 按播放量排序，优先权威热门
            page=1,
            page_size=settings.config.question_bank.bili_search_page_size,
        )
        videos = result.get("result", []) if isinstance(result, dict) else []
        # 过滤掉无效项并清洗
        cleaned: list[dict] = []
        for v in videos:
            bvid = v.get("bvid")
            if not bvid:
                continue
            title = (v.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")
            cleaned.append(
                {
                    "bvid": bvid,
                    "title": title.strip(),
                    "author": v.get("author", ""),
                    "play": v.get("play", 0),
                    "duration": v.get("duration", 0),
                    "url": f"https://www.bilibili.com/video/{bvid}",
                }
            )
        # 再次按播放量降序取 Top N（API 已排序，这里兜底）
        cleaned.sort(key=lambda x: x["play"], reverse=True)
        return cleaned[: settings.config.question_bank.bili_search_top_n]

    try:
        timeout = settings.config.question_bank.bili_search_timeout_seconds
        return await asyncio.wait_for(_do_search(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("B站搜索超时（%ss）：keyword=%s", settings.config.question_bank.bili_search_timeout_seconds, keyword)
        return []
    except Exception as e:  # noqa: BLE001
        logger.warning("B站搜索失败：%s：keyword=%s", e, keyword)
        return []


async def enrich_video_info(bvid: str) -> dict:
    """对单个视频补充简介+弹幕采样，供 agent 判断内容质量（B站预审）。

    返回 {desc, danmaku_sample}。失败返回空字段，不阻塞推荐。
    """
    try:
        from bilibili_api import video as bili_video

        v = bili_video.Video(bvid=bvid)
        info = await v.get_info()
        desc = (info.get("desc") or "")[:200]

        # 弹幕采样（前20条），看观众反馈倾向
        danmaku_sample: list[str] = []
        try:
            dms = await v.get_danmakus()
            danmaku_sample = [d.text[:20] for d in dms[:20]]
        except Exception:  # noqa: BLE001
            pass  # 弹幕失败不阻塞

        return {"desc": desc, "danmaku_sample": danmaku_sample}
    except Exception as e:  # noqa: BLE001
        logger.warning("B站视频信息补充失败：%s bvid=%s", e, bvid)
        return {"desc": "", "danmaku_sample": []}


async def search_and_enrich(keyword: str) -> list[dict]:
    """搜索 + 补充简介/弹幕（B站预审）。

    返回 Top3 视频，每个含 bvid/title/author/play/url + desc/danmaku_sample。
    agent 据简介+弹幕判断内容是否匹配需求，过滤明显不合适的。
    """
    candidates = await search_bilibili_videos(keyword)
    if not candidates:
        return []

    enriched = []
    for c in candidates:
        extra = await enrich_video_info(c["bvid"])
        enriched.append(
            {
                **c,
                "desc": extra["desc"],
                "danmaku_sample": extra["danmaku_sample"],
            }
        )
    return enriched
