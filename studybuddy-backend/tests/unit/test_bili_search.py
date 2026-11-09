"""B站视频搜索服务单元测试（mock bilibili-api，不真实调网络/不耗 token）。

用 asyncio.run() 跑 async 函数，不引入 pytest-asyncio 依赖（与 live 测试同风格）。

覆盖：
- search_bilibili_videos：清洗 <em> 高亮、过滤无 bvid 项、按播放量降序取 Top N
- enrich_video_info：补充简介+弹幕采样，失败兜底不阻塞
- search_and_enrich：搜索+逐个 enrich 串联，返回带 desc/danmaku_sample
- 降级：超时/异常/空结果都返回空，不抛
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.features.question_bank import bili_search_service


def _fake_search_result(videos: list[dict]) -> dict:
    """构造 search_by_type 的返回结构。"""
    return {"result": videos}


def _fake_video(bvid: str, play: int = 0, title: str = "t", author: str = "up") -> dict:
    return {"bvid": bvid, "title": title, "author": author, "play": play, "duration": 120}


class TestSearchBilibiliVideos:
    """search_bilibili_videos 清洗 + 排序 + 降级。"""

    def test_cleans_keyword_highlight_and_sorts_by_play(self):
        """搜到的视频去 <em> 高亮、按播放量降序、取 Top N。"""
        raw = _fake_search_result(
            [
                _fake_video("BV1aaa", play=100, title='<em class="keyword">英语</em>动词讲解'),
                _fake_video("BV1bbb", play=500, title="语法入门"),
                _fake_video("BV1ccc", play=300, title="阅读技巧"),
            ]
        )
        with patch("bilibili_api.search.search_by_type", new=AsyncMock(return_value=raw)):
            result = asyncio.run(bili_search_service.search_bilibili_videos("英语"))
        # 按播放量降序：bbb(500) > ccc(300) > aaa(100)
        assert [r["bvid"] for r in result] == ["BV1bbb", "BV1ccc", "BV1aaa"]
        # <em> 高亮已清洗
        assert result[2]["title"] == "英语动词讲解"
        # 每项含完整字段 + url
        for r in result:
            assert r["url"] == f"https://www.bilibili.com/video/{r['bvid']}"

    def test_filters_out_items_without_bvid(self):
        """无 bvid 的项被过滤掉。"""
        raw = _fake_search_result(
            [
                _fake_video("BV1ok", play=10),
                {"title": "无bvid项", "play": 999},  # 无 bvid
                _fake_video("BV1ok2", play=20),
            ]
        )
        with patch("bilibili_api.search.search_by_type", new=AsyncMock(return_value=raw)):
            result = asyncio.run(bili_search_service.search_bilibili_videos("x"))
        assert len(result) == 2
        assert all(r["bvid"] for r in result)

    def test_timeout_returns_empty(self):
        """搜索超时 → 返回空列表，不抛。"""

        async def _timeout(*a, **kw):
            raise asyncio.TimeoutError

        # 替换只读配置副本，确认行为从配置读取。
        question_bank = bili_search_service.settings.config.question_bank.model_copy(
            update={"bili_search_timeout_seconds": 1}
        )
        config = bili_search_service.settings.config.model_copy(update={"question_bank": question_bank})
        with patch("bilibili_api.search.search_by_type", new=_timeout), patch.object(
            bili_search_service.settings, "config", config
        ):
            result = asyncio.run(bili_search_service.search_bilibili_videos("x"))
        assert result == []

    def test_exception_returns_empty(self):
        """搜索抛异常 → 返回空列表，不抛。"""
        with patch("bilibili_api.search.search_by_type", new=AsyncMock(side_effect=RuntimeError("网络错误"))):
            result = asyncio.run(bili_search_service.search_bilibili_videos("x"))
        assert result == []

    def test_empty_result(self):
        """搜不到结果 → 返回空列表。"""
        with patch("bilibili_api.search.search_by_type", new=AsyncMock(return_value={"result": []})):
            result = asyncio.run(bili_search_service.search_bilibili_videos("无匹配词"))
        assert result == []


class TestEnrichVideoInfo:
    """enrich_video_info 补充简介+弹幕，失败兜底。"""

    def test_returns_desc_and_danmaku_sample(self):
        """正常情况返回 desc（截200字）+ 弹幕采样（前20条各截20字）。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value={"desc": "讲动词过去式变化规则"})
        fake_dm = MagicMock()
        fake_dm.text = "发现宝藏打call" * 3  # 长文本测截断
        fake_video.get_danmakus = AsyncMock(return_value=[fake_dm] * 5)

        with patch("bilibili_api.video.Video", return_value=fake_video):
            result = asyncio.run(bili_search_service.enrich_video_info("BV1xxx"))

        assert result["desc"] == "讲动词过去式变化规则"
        assert len(result["danmaku_sample"]) == 5
        assert all(len(d) <= 20 for d in result["danmaku_sample"])

    def test_desc_truncated_to_200(self):
        """desc 超 200 字被截断。"""
        long_desc = "x" * 300
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value={"desc": long_desc})
        fake_video.get_danmakus = AsyncMock(return_value=[])
        with patch("bilibili_api.video.Video", return_value=fake_video):
            result = asyncio.run(bili_search_service.enrich_video_info("BV1xxx"))
        assert len(result["desc"]) == 200

    def test_danmaku_failure_does_not_block(self):
        """弹幕接口失败 → danmaku_sample 为空，但 desc 仍返回。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value={"desc": "简介"})
        fake_video.get_danmakus = AsyncMock(side_effect=RuntimeError("弹幕挂了"))
        with patch("bilibili_api.video.Video", return_value=fake_video):
            result = asyncio.run(bili_search_service.enrich_video_info("BV1xxx"))
        assert result["desc"] == "简介"
        assert result["danmaku_sample"] == []

    def test_get_info_failure_returns_empty_fields(self):
        """get_info 整体失败 → 返回空字段，不抛。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(side_effect=RuntimeError("视频不存在"))
        with patch("bilibili_api.video.Video", return_value=fake_video):
            result = asyncio.run(bili_search_service.enrich_video_info("BV1xxx"))
        assert result == {"desc": "", "danmaku_sample": []}


class TestSearchAndEnrich:
    """search_and_enrich 串联搜索+enrich。"""

    def test_combines_search_and_enrich(self):
        """搜索结果逐个 enrich，返回带 desc/danmaku_sample 的合并结构。"""
        raw = _fake_search_result([_fake_video("BV1a", play=100, title="t1")])
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value={"desc": "简介a"})
        fake_video.get_danmakus = AsyncMock(return_value=[])

        with patch("bilibili_api.search.search_by_type", new=AsyncMock(return_value=raw)), patch("bilibili_api.video.Video", return_value=fake_video):
            result = asyncio.run(bili_search_service.search_and_enrich("英语"))

        assert len(result) == 1
        item = result[0]
        # 搜索字段
        assert item["bvid"] == "BV1a"
        assert item["title"] == "t1"
        # enrich 字段
        assert item["desc"] == "简介a"
        assert item["danmaku_sample"] == []

    def test_empty_when_no_search_results(self):
        """搜索无结果 → 返回空列表。"""
        with patch("bilibili_api.search.search_by_type", new=AsyncMock(return_value={"result": []})):
            result = asyncio.run(bili_search_service.search_and_enrich("无匹配"))
        assert result == []

    def test_enrich_failure_keeps_search_fields(self):
        """某视频 enrich 失败 → 该项仍保留搜索字段，desc/danmaku 为空。"""
        raw = _fake_search_result([_fake_video("BV1a", play=100, title="t1")])
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(side_effect=RuntimeError("挂了"))
        with patch("bilibili_api.search.search_by_type", new=AsyncMock(return_value=raw)), patch("bilibili_api.video.Video", return_value=fake_video):
            result = asyncio.run(bili_search_service.search_and_enrich("x"))
        assert len(result) == 1
        assert result[0]["bvid"] == "BV1a"  # 搜索字段仍在
        assert result[0]["desc"] == ""  # enrich 兜底空
