"""B站学习闭环助手服务单元测试（mock bilibili-api / 子进程 / groq，不真实调网络）。

用 asyncio.run() 跑 async 函数，不引入 pytest-asyncio 依赖（与 test_bili_search 同风格）。

覆盖：
- parse_bvid/parse_page_index：URL/BV 解析
- fetch_course_directory：合集目录结构化（跨 section 编号）、非合集降级、top_n、invalid_url/api_error
- fetch_video_content：字幕路径、max_chars 截断、whisper 路径（mock 子进程+groq）、
  音频时长截断、失败结构化（subtitle_unavailable/transcribe_unavailable/timeout/process_error）
- 角色白名单：tools_for_actor(student) 含 / teacher 与 channel_guardian 不含
- handler：仅学生、不落库、keyword/read_content 分发、结构化失败
"""

import asyncio
import wave
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.features.agent.handlers.learning import _handle_bilibili_course_assist
from app.features.question_bank import bilibili_assist_service as service


def _fake_info(**overrides) -> dict:
    """bilibili_api get_info 返回结构（单 P 页面 2 个，无合集）。"""
    info = {
        "bvid": "BV1pw411p7ig",
        "title": "英语语法合集",
        "owner": {"name": "UP主"},
        "duration": 3600,
        "desc": "合集简介" * 200,  # 超 500 字测简介截断
        "pages": [{"cid": 101, "duration": 600}, {"cid": 102, "duration": 700}],
        "ugc_season": None,
    }
    info.update(overrides)
    return info


def _fake_collection_info() -> dict:
    """带 ugc_season（两个 section 共 3 集）的 get_info 返回。"""
    return _fake_info(
        ugc_season={
            "title": "英语语法合集",
            "sections": [
                {
                    "title": "S1",
                    "episodes": [
                        {"title": "过去时", "arc": {"duration": 601}},
                        {"title": "将来时", "arc": {"duration": 602}},
                    ],
                },
                {"title": "S2", "episodes": [{"title": "完成时", "arc": {"duration": 603}}]},
            ],
        }
    )


def _make_wav(path: Path, seconds: int = 2) -> Path:
    """造一个 16kHz mono 的静音 WAV（测试用短时长）。"""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * (16000 * seconds))
    return path


def _mock_httpx_client(resp) -> MagicMock:
    """构造 async with httpx.AsyncClient(...) 的 fake，get 返回 resp。"""
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestParse:
    """BV/URL 解析。"""

    def test_parse_bvid_from_bare_and_url(self):
        assert service.parse_bvid("BV1pw411p7ig") == "BV1pw411p7ig"
        assert service.parse_bvid("https://www.bilibili.com/video/BV1pw411p7ig?p=3") == "BV1pw411p7ig"
        assert service.parse_bvid("  BV1pw411p7ig  ") == "BV1pw411p7ig"

    def test_parse_bvid_invalid(self):
        assert service.parse_bvid("") is None
        assert service.parse_bvid("https://example.com/video/abc") is None
        assert service.parse_bvid("BV123") is None  # 长度不足

    def test_parse_page_index(self):
        assert service.parse_page_index("https://www.bilibili.com/video/BV1pw411p7ig?p=3") == 3
        assert service.parse_page_index("https://www.bilibili.com/video/BV1pw411p7ig") == 1
        assert service.parse_page_index("BV1pw411p7ig") == 1


class TestFetchCourseDirectory:
    """合集目录结构化 + 非合集降级 + 失败。"""

    def test_collection_directory_structure(self):
        """合集：跨 section 连续编号，每集带直链，取 top_n。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_collection_info())
        with patch("bilibili_api.video.Video", return_value=fake_video):
            result = asyncio.run(
                service.fetch_course_directory("https://www.bilibili.com/video/BV1pw411p7ig?p=3")
            )
        assert result["ok"] is True
        assert result["is_collection"] is True
        assert result["title"] == "英语语法合集"
        assert result["author"] == "UP主"
        assert len(result["episodes"]) == 3
        assert result["episodes"][0] == {
            "index": 1,
            "title": "过去时",
            "duration_seconds": 601,
            "url": "https://www.bilibili.com/video/BV1pw411p7ig?p=1",
        }
        # 第二个 section 的集继续编号，URL 直链指向对应分P
        assert result["episodes"][2]["index"] == 3
        assert result["episodes"][2]["url"] == "https://www.bilibili.com/video/BV1pw411p7ig?p=3"

    def test_collection_respects_top_n(self):
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_collection_info())
        with patch("bilibili_api.video.Video", return_value=fake_video):
            result = asyncio.run(service.fetch_course_directory("BV1pw411p7ig", top_n=2))
        assert len(result["episodes"]) == 2

    def test_non_collection_fallback(self):
        """无合集：降级返回单集信息（时长/简介/链接）。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_info())
        with patch("bilibili_api.video.Video", return_value=fake_video):
            result = asyncio.run(service.fetch_course_directory("BV1pw411p7ig"))
        assert result["ok"] is True
        assert result["is_collection"] is False
        assert result["bvid"] == "BV1pw411p7ig"
        assert result["duration_seconds"] == 3600
        assert len(result["desc"]) == 500  # 简介截断
        assert result["url"] == "https://www.bilibili.com/video/BV1pw411p7ig"

    def test_invalid_url(self):
        result = asyncio.run(service.fetch_course_directory("https://example.com/not-bili"))
        assert result == {"ok": False, "error": "invalid_url"}

    def test_api_error(self):
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(side_effect=RuntimeError("视频不存在或风控"))
        with patch("bilibili_api.video.Video", return_value=fake_video):
            result = asyncio.run(service.fetch_course_directory("BV1pw411p7ig"))
        assert result == {"ok": False, "error": "api_error"}

    def test_get_info_timeout(self):
        """B站 get_info 挂起 → timeout 结构化失败（外部调用超时，P1 回归）。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(side_effect=asyncio.TimeoutError)
        cfg = service.settings.config.bilibili_assist.model_copy(update={"api_timeout_seconds": 1})
        config = service.settings.config.model_copy(update={"bilibili_assist": cfg})
        with patch("bilibili_api.video.Video", return_value=fake_video), patch.object(
            service.settings, "config", config
        ):
            result = asyncio.run(service.fetch_course_directory("BV1pw411p7ig"))
        assert result == {"ok": False, "error": "timeout"}


class TestFetchVideoContentSubtitle:
    """字幕路径 + 截断。"""

    def _subtitle_response(self, contents: list[str]) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"body": [{"content": c} for c in contents]})
        return resp

    def test_subtitle_source(self):
        """有字幕：下载 subtitle_url json 拼文本，duration_used 取该分P时长。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_info())
        fake_video.get_subtitle = AsyncMock(
            return_value={"subtitles": [{"subtitle_url": "//aisubtitle.hdslb.com/abc.json"}]}
        )
        resp = self._subtitle_response(["第一句", "第二句"])
        with patch("bilibili_api.video.Video", return_value=fake_video), patch(
            "app.features.question_bank.bilibili_assist_service.httpx.AsyncClient",
            return_value=_mock_httpx_client(resp),
        ):
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig"))
        assert result["ok"] is True
        assert result["source"] == "subtitle"
        assert result["transcript"] == "第一句\n第二句"
        assert result["char_count"] == 7
        assert result["truncated"] is False
        assert result["duration_used"] == 600  # pages[0].duration

    def test_subtitle_truncated_to_max_chars(self):
        """转写文本超 max_chars 截断并标记 truncated。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_info())
        fake_video.get_subtitle = AsyncMock(
            return_value={"subtitles": [{"subtitle_url": "//aisubtitle.hdslb.com/abc.json"}]}
        )
        resp = self._subtitle_response(["你好世界"] * 5)  # 拼接后 29 字
        with patch("bilibili_api.video.Video", return_value=fake_video), patch(
            "app.features.question_bank.bilibili_assist_service.httpx.AsyncClient",
            return_value=_mock_httpx_client(resp),
        ):
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig", max_chars=10))
        assert result["truncated"] is True
        assert result["char_count"] == 10
        assert result["transcript"] == "你好世界\n你好世界\n"

    def test_subtitle_download_failure_falls_to_whisper_disabled_error(self):
        """字幕接口异常 → 走转写路径；转写未启用时返回 subtitle_unavailable。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_info())
        fake_video.get_subtitle = AsyncMock(side_effect=RuntimeError("字幕接口挂了"))
        cfg = service.settings.config.bilibili_assist.model_copy(update={"enabled": False})
        config = service.settings.config.model_copy(update={"bilibili_assist": cfg})
        with patch("bilibili_api.video.Video", return_value=fake_video), patch.object(
            service.settings, "config", config
        ):
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig"))
        assert result == {"ok": False, "error": "subtitle_unavailable"}


class TestFetchVideoContentWhisper:
    """whisper 转写路径（mock 子进程产出 WAV + mock groq 转写）。"""

    def _whisper_env(self, tmp_path: Path, wav_seconds: int = 2):
        """无字幕 get_info + 两个 WAV 片段 + 假 groq 转写。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_info())
        fake_video.get_subtitle = AsyncMock(return_value={})  # 无字幕
        segs = [
            str(_make_wav(tmp_path / "seg_000.wav", wav_seconds)),
            str(_make_wav(tmp_path / "seg_001.wav", wav_seconds)),
        ]
        patches = [
            patch("bilibili_api.video.Video", return_value=fake_video),
            patch.object(service.settings.secrets, "GROQ_API_KEY", SecretStr("groq-test-key")),
            patch("app.features.question_bank.bilibili_assist_service._download_audio_segments", new=AsyncMock(return_value=segs)),
        ]
        return fake_video, patches

    def test_whisper_source(self, tmp_path: Path):
        """无字幕 → 下载 WAV → 并发转写 → 拼接；时长/字数正确。"""
        _, patches = self._whisper_env(tmp_path)
        fake_transcribe = AsyncMock(side_effect=["第一段转写", "第二段转写"])
        patches.append(
            patch("app.features.question_bank.bilibili_assist_service._transcribe_segment", new=fake_transcribe)
        )
        with _patched(patches):
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig"))
        assert result["ok"] is True
        assert result["source"] == "whisper"
        assert result["transcript"] == "第一段转写\n第二段转写"
        assert result["char_count"] == len("第一段转写\n第二段转写")
        assert result["truncated"] is False
        assert result["duration_used"] == 4  # 两段各 2s

    def test_whisper_audio_max_seconds_truncation(self, tmp_path: Path):
        """音频总时长超 max_seconds 只转前 N 段（段边界截断）。"""
        _, patches = self._whisper_env(tmp_path)
        fake_transcribe = AsyncMock(side_effect=["第一段转写"])
        patches.append(
            patch("app.features.question_bank.bilibili_assist_service._transcribe_segment", new=fake_transcribe)
        )
        with _patched(patches):
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig", max_seconds=3))
        assert result["ok"] is True
        assert result["transcript"] == "第一段转写"  # 只转第 1 段
        assert result["duration_used"] == 2
        assert fake_transcribe.await_count == 1

    def test_whisper_all_segments_failed(self, tmp_path: Path):
        """全部段转写失败 → transcribe_unavailable。"""
        _, patches = self._whisper_env(tmp_path)
        patches.append(
            patch("app.features.question_bank.bilibili_assist_service._transcribe_segment", new=AsyncMock(return_value=""))
        )
        with _patched(patches):
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig"))
        assert result == {"ok": False, "error": "transcribe_unavailable"}

    def test_whisper_partial_failure_marked(self, tmp_path: Path):
        """部分段转写失败 → partial=true + failed_segments 标记，不静默返回不完整内容（P1 回归）。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_info())
        fake_video.get_subtitle = AsyncMock(return_value={})
        segs = [
            str(_make_wav(tmp_path / "seg_000.wav", 2)),
            str(_make_wav(tmp_path / "seg_001.wav", 2)),
            str(_make_wav(tmp_path / "seg_002.wav", 2)),
        ]
        fake_transcribe = AsyncMock(side_effect=["第一段", "", "第三段"])  # 第 2 段失败
        patches = [
            patch("bilibili_api.video.Video", return_value=fake_video),
            patch.object(service.settings.secrets, "GROQ_API_KEY", SecretStr("groq-test-key")),
            patch(
                "app.features.question_bank.bilibili_assist_service._download_audio_segments",
                new=AsyncMock(return_value=segs),
            ),
            patch("app.features.question_bank.bilibili_assist_service._transcribe_segment", new=fake_transcribe),
        ]
        with _patched(patches):
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig"))
        assert result["ok"] is True
        assert result["partial"] is True
        assert result["failed_segments"] == 1
        assert result["transcript"] == "第一段\n第三段"

    def test_no_api_key(self, tmp_path: Path):
        """未配置 GROQ key → transcribe_unavailable（不发请求）。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_info())
        fake_video.get_subtitle = AsyncMock(return_value={})
        with patch("bilibili_api.video.Video", return_value=fake_video), patch.object(
            service.settings.secrets, "GROQ_API_KEY", SecretStr("")
        ):
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig"))
        assert result == {"ok": False, "error": "transcribe_unavailable"}

    def test_no_subtitle_and_disabled(self, tmp_path: Path):
        """无字幕且 bilibili_assist.enabled=false → subtitle_unavailable。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_info())
        fake_video.get_subtitle = AsyncMock(return_value={})
        cfg = service.settings.config.bilibili_assist.model_copy(update={"enabled": False})
        config = service.settings.config.model_copy(update={"bilibili_assist": cfg})
        with patch("bilibili_api.video.Video", return_value=fake_video), patch.object(
            service.settings, "config", config
        ):
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig"))
        assert result == {"ok": False, "error": "subtitle_unavailable"}

    def test_multi_page_no_subtitle_fail_closed(self, tmp_path: Path):
        """多 P 视频 p>1 且无字幕 → multi_page_whisper_unsupported（不转写第 1 分 P 伪装，P1 回归）。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(
            return_value=_fake_info(
                pages=[{"duration": 10, "cid": 111}, {"duration": 20, "cid": 222}]
            )
        )
        fake_video.get_subtitle = AsyncMock(return_value={})  # 该分 P 无字幕
        with patch("bilibili_api.video.Video", return_value=fake_video), patch.object(
            service.settings.secrets, "GROQ_API_KEY", SecretStr("groq-test-key")
        ):
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig?p=2", p_index=2))
        assert result == {"ok": False, "error": "multi_page_whisper_unsupported"}

    def test_multi_page_with_subtitle_ok(self, tmp_path: Path):
        """多 P 视频 p>1 但有字幕 → 正常走字幕路径（不误伤有字幕的分 P）。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(
            return_value=_fake_info(pages=[{"duration": 10, "cid": 111}, {"duration": 20, "cid": 222}])
        )
        subtitle = {"subtitles": [{"lan": "zh", "subtitle_url": "https://sub.example/x.json"}]}
        fake_video.get_subtitle = AsyncMock(return_value=subtitle)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"body": [{"content": "第2集字幕内容"}]})
        with patch("bilibili_api.video.Video", return_value=fake_video), patch(
            "app.features.question_bank.bilibili_assist_service.httpx.AsyncClient",
        ) as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=resp)
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig?p=2", p_index=2))
        assert result["ok"] is True
        assert result["source"] == "subtitle"
        assert "第2集字幕内容" in result["transcript"]

    def test_whisper_total_timeout(self, tmp_path: Path):
        """整体转写超时 → timeout 结构化失败（不无限阻塞对话轮，P1 回归）。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_info())
        fake_video.get_subtitle = AsyncMock(return_value={})
        segs = [str(_make_wav(tmp_path / "seg_000.wav", 2))]
        cfg = service.settings.config.bilibili_assist.model_copy(update={"transcribe_total_timeout_seconds": 1})
        config = service.settings.config.model_copy(update={"bilibili_assist": cfg})

        async def slow(*_a, **_k):
            await asyncio.sleep(5)
            return ""

        patches = [
            patch("bilibili_api.video.Video", return_value=fake_video),
            patch.object(service.settings.secrets, "GROQ_API_KEY", SecretStr("groq-test-key")),
            patch(
                "app.features.question_bank.bilibili_assist_service._download_audio_segments",
                new=AsyncMock(return_value=segs),
            ),
            patch.object(service.settings, "config", config),
            patch("app.features.question_bank.bilibili_assist_service._transcribe_segment", new=slow),
        ]
        with _patched(patches):
            result = asyncio.run(service.fetch_video_content("BV1pw411p7ig"))
        assert result == {"ok": False, "error": "timeout"}


class TestDownloadAudioSegments:
    """bili audio 子进程下载：超时/取消必须回收子进程（P1 孤儿进程回归）。"""

    def test_cancel_kills_proc(self):
        """外部取消（CancelledError）时子进程被 kill 回收，不泄漏孤儿进程。"""

        class FakeProc:
            def __init__(self):
                self.returncode = None
                self.killed = False

            def kill(self):
                self.killed = True
                self.returncode = -9

            async def wait(self):
                return -9

            async def communicate(self):
                await asyncio.Event().wait()  # 永远挂起，模拟长下载

        fake_proc = FakeProc()

        async def run():
            task = asyncio.create_task(
                service._download_audio_segments("BV1x", "/tmp/x", "bili", 30)
            )
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            asyncio.run(run())
        assert fake_proc.killed is True

    def test_timeout_kills_proc(self, tmp_path: Path):
        """内层超时（TimeoutError）时子进程被 kill 回收，并抛 timeout 错误。"""

        class FakeProc:
            def __init__(self):
                self.returncode = None
                self.killed = False

            def kill(self):
                self.killed = True
                self.returncode = -9

            async def wait(self):
                return -9

            async def communicate(self):
                await asyncio.sleep(30)  # 超过 timeout_seconds

        fake_proc = FakeProc()
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            with pytest.raises(service._BiliAudioError) as exc:
                asyncio.run(service._download_audio_segments("BV1x", str(tmp_path), "bili", 1))
        assert exc.value.code == "timeout"
        assert fake_proc.killed is True

    """bili audio 子进程：参数数组、超时/失败/CLI 缺失映射。"""

    def test_timeout(self):
        """子进程超时 → kill + error=timeout。"""
        proc = MagicMock()
        proc.returncode = None  # 模拟运行中的进程，finally 才能触发 kill 回收
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=-9)
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            with pytest.raises(service._BiliAudioError) as exc_info:
                asyncio.run(service._download_audio_segments("BV1x", "/tmp/out", "bili", 5))
        assert exc_info.value.code == "timeout"
        proc.kill.assert_called_once()

    def test_process_error_on_nonzero_exit(self):
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", "下载失败".encode()))
        proc.returncode = 1
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            with pytest.raises(service._BiliAudioError) as exc_info:
                asyncio.run(service._download_audio_segments("BV1x", "/tmp/out", "bili", 5))
        assert exc_info.value.code == "process_error"

    def test_process_error_on_no_segments(self, tmp_path: Path):
        """退出码 0 但目录无 WAV → process_error。"""
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            with pytest.raises(service._BiliAudioError) as exc_info:
                asyncio.run(service._download_audio_segments("BV1x", str(tmp_path), "bili", 5))
        assert exc_info.value.code == "process_error"

    def test_cli_missing_is_transcribe_unavailable(self):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            with pytest.raises(service._BiliAudioError) as exc_info:
                asyncio.run(service._download_audio_segments("BV1x", "/tmp/out", "bili", 5))
        assert exc_info.value.code == "transcribe_unavailable"

    def test_success_returns_sorted_segments(self, tmp_path: Path):
        _make_wav(tmp_path / "seg_000.wav")
        _make_wav(tmp_path / "seg_002.wav")
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            segments = asyncio.run(service._download_audio_segments("BV1x", str(tmp_path), "bili", 5))
        assert [Path(s).name for s in segments] == ["seg_000.wav", "seg_002.wav"]


class TestToolWhitelist:
    """角色可见集：student 含，teacher/channel_guardian 不含。"""

    def test_student_only(self):
        from app.features.agent import tools

        student = {t["name"] for t in tools.tools_for_actor("student")}
        teacher = {t["name"] for t in tools.tools_for_actor("teacher")}
        guardian = {t["name"] for t in tools.tools_for_actor("teacher", "channel_guardian")}
        assert "bilibili_course_assist" in student
        assert "bilibili_course_assist" not in teacher
        assert "bilibili_course_assist" not in guardian


class TestHandler:
    """handler：仅学生、不落库、分发、结构化失败。"""

    def test_teacher_forbidden(self):
        with pytest.raises(PermissionError):
            asyncio.run(_handle_bilibili_course_assist({"url": "BV1pw411p7ig"}, "teacher", MagicMock(), 1))

    def test_missing_args(self):
        result = asyncio.run(_handle_bilibili_course_assist({}, "student", MagicMock(), 1))
        assert result["error"] == "请提供 url 或 keyword 至少一个"

    def test_student_directory_no_db_write(self):
        """学生拿合集目录：不落库（db 零调用）。"""
        fake_video = MagicMock()
        fake_video.get_info = AsyncMock(return_value=_fake_collection_info())
        db = MagicMock()
        with patch("bilibili_api.video.Video", return_value=fake_video):
            result = asyncio.run(_handle_bilibili_course_assist({"url": "BV1pw411p7ig"}, "student", db, 7))
        assert result["ok"] is True
        assert result["is_collection"] is True
        db.commit.assert_not_called()
        db.execute.assert_not_called()

    def test_keyword_search(self):
        """keyword → search_and_enrich Top3 候选。"""
        candidates = [{"bvid": f"BV1a{i}", "title": f"t{i}"} for i in range(3)]
        with patch(
            "app.features.question_bank.bili_search_service.search_and_enrich", new=AsyncMock(return_value=candidates)
        ):
            result = asyncio.run(_handle_bilibili_course_assist({"keyword": "英语 时态"}, "student", MagicMock(), 1))
        assert [c["bvid"] for c in result["candidates"]] == ["BV1a0", "BV1a1", "BV1a2"]

    def test_keyword_empty_result(self):
        with patch(
            "app.features.question_bank.bili_search_service.search_and_enrich", new=AsyncMock(return_value=[])
        ):
            result = asyncio.run(_handle_bilibili_course_assist({"keyword": "不存在的内容"}, "student", MagicMock(), 1))
        assert "未搜到" in result["error"]

    def test_read_content_success(self):
        """url+read_content → fetch_video_content，带选集上下文。"""
        directory = {
            "ok": True,
            "bvid": "BV1pw411p7ig",
            "title": "英语语法合集",
            "author": "UP主",
            "is_collection": True,
            "episodes": [
                {"index": 1, "title": "过去时", "duration_seconds": 601, "url": "u1"},
                {"index": 2, "title": "将来时", "duration_seconds": 602, "url": "u2"},
            ],
        }
        content = {
            "ok": True,
            "source": "subtitle",
            "transcript": "讲将来时用法",
            "truncated": False,
            "char_count": 7,
            "duration_used": 602,
        }
        with patch(
            "app.features.question_bank.bilibili_assist_service.fetch_course_directory", new=AsyncMock(return_value=directory)
        ), patch(
            "app.features.question_bank.bilibili_assist_service.fetch_video_content", new=AsyncMock(return_value=content)
        ):
            result = asyncio.run(
                _handle_bilibili_course_assist(
                    {"url": "https://www.bilibili.com/video/BV1pw411p7ig?p=2", "read_content": True},
                    "student",
                    MagicMock(),
                    1,
                )
            )
        assert result["episode_index"] == 2
        assert result["episode_title"] == "将来时"
        assert result["content"]["source"] == "subtitle"

    def test_read_content_failure_structured(self):
        """内容读取失败 → 结构化失败返回（含错误码与视频上下文），不伪装成功。"""
        directory = {"ok": True, "bvid": "BV1pw411p7ig", "title": "英语语法合集", "is_collection": False, "episodes": []}
        with patch(
            "app.features.question_bank.bilibili_assist_service.fetch_course_directory", new=AsyncMock(return_value=directory)
        ), patch(
            "app.features.question_bank.bilibili_assist_service.fetch_video_content",
            new=AsyncMock(return_value={"ok": False, "error": "transcribe_unavailable"}),
        ):
            result = asyncio.run(
                _handle_bilibili_course_assist(
                    {"url": "BV1pw411p7ig", "read_content": True}, "student", MagicMock(), 1
                )
            )
        assert result["error"] == "transcribe_unavailable"
        assert result["bvid"] == "BV1pw411p7ig"
        assert result["episode_index"] == 1

    def test_invalid_url_structured(self):
        result = asyncio.run(_handle_bilibili_course_assist({"url": "https://example.com/x"}, "student", MagicMock(), 1))
        assert result["error"] == "invalid_url"


def _patched(patches: list):
    """嵌套 context 管理器（python3.10+ 单行括号语法）。"""
    from contextlib import ExitStack

    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack
