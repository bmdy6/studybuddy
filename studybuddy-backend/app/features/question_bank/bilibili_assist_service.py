"""B站学习闭环助手服务（POC 批次1+2）。

闭环 = 合集目录 → 推荐第几集（直链）→ 单集内容感知（字幕/音频转写）。
- fetch_course_directory：解析 BV（支持 URL 与裸 BV）→ get_info → 合集目录/单集信息
- fetch_video_content：字幕优先（bilibili_api get_subtitle + subtitle_url 下载 json），
  无字幕 → bili audio 子进程切 25s WAV → 并发调 groq whisper 转写 → 拼接截断

安全约束：子进程一律 create_subprocess_exec 参数数组（无 shell 拼接）；
GROQ key 只进请求头，不打印不落日志；路径/超时/上限全走 settings.config.bilibili_assist。
无字幕且转写路径不可用时返回结构化失败，不伪装成功。
注意：bili-cli 音频下载固定取第 1 分 P（get_audio_url page_index=0），多 P 视频
whisper 转写的是整稿音频，与 p_index 无对应关系（POC 单 P 场景足够）。
"""

import asyncio
import logging
import re
import shutil
import tempfile
import wave
from pathlib import Path

import httpx

from app.config import reveal_secret, settings

logger = logging.getLogger(__name__)

_GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
_SEGMENT_SECONDS = 25  # bili audio 切段时长（秒），与 bili-cli 默认一致


def parse_bvid(url_or_bvid: str) -> str | None:
    """从裸 BV 号或 bilibili.com/video/BVxxx?p=N URL 提取 BV 号，无效返回 None。"""
    match = _BV_RE.search((url_or_bvid or "").strip())
    return match.group(0) if match else None


def parse_page_index(url_or_bvid: str) -> int:
    """从 URL 的 ?p=N 提取分 P 序号（1 起），无 p 参数返回 1。"""
    match = re.search(r"[?&]p=(\d+)", url_or_bvid or "")
    return int(match.group(1)) if match else 1


async def fetch_course_directory(url_or_bvid: str, top_n: int = 20) -> dict:
    """解析 BV → 合集目录（每集标题/时长/直链）或单集信息。

    Args:
        url_or_bvid: bilibili.com/video/BVxxx[?p=N] 或裸 BV 号
        top_n: 合集最多返回前 N 集

    Returns:
        合集: {ok:true, bvid, title, author, is_collection:true, episodes:[{index,title,duration_seconds,url}]}
        非合集: {ok:true, bvid, title, author, is_collection:false, duration_seconds, desc, url}
        失败: {ok:false, error:"invalid_url"/"api_error"}
    """
    bvid = parse_bvid(url_or_bvid)
    if not bvid:
        return {"ok": False, "error": "invalid_url"}
    try:
        # 延迟导入，避免未装库时影响后端启动
        from bilibili_api import Credential, video as bili_video

        v = bili_video.Video(bvid=bvid, credential=Credential())
        info = await asyncio.wait_for(v.get_info(), timeout=settings.config.bilibili_assist.api_timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning("B站 get_info 超时：bvid=%s", bvid)
        return {"ok": False, "error": "timeout"}
    except Exception as e:  # noqa: BLE001
        logger.warning("B站视频信息获取失败：%s bvid=%s", e, bvid)
        return {"ok": False, "error": "api_error"}

    title = (info.get("title") or "").strip()
    author = ((info.get("owner") or {}).get("name") or "").strip()
    base_url = f"https://www.bilibili.com/video/{bvid}"
    ugc_season = info.get("ugc_season")

    if ugc_season:
        episodes: list[dict] = []
        for section in ugc_season.get("sections") or []:
            for ep in section.get("episodes") or []:
                index = len(episodes) + 1  # 跨 section 连续编号，与 B站分P号一致
                arc = ep.get("arc") or {}
                episodes.append(
                    {
                        "index": index,
                        "title": (ep.get("title") or "").strip(),
                        "duration_seconds": arc.get("duration", 0),
                        "url": f"{base_url}?p={index}",
                    }
                )
        return {
            "ok": True,
            "bvid": bvid,
            "title": (ugc_season.get("title") or title),
            "author": author,
            "is_collection": True,
            "episodes": episodes[:top_n],
        }

    return {
        "ok": True,
        "bvid": bvid,
        "title": title,
        "author": author,
        "is_collection": False,
        "duration_seconds": info.get("duration", 0),
        "desc": (info.get("desc") or "")[:500],
        "url": base_url,
    }


async def fetch_video_content(
    bvid: str, p_index: int = 1, max_seconds: int | None = None, max_chars: int | None = None
) -> dict:
    """读取单集内容：字幕优先，无字幕走音频转写（whisper）。

    Args:
        bvid: BV 号
        p_index: 分 P 序号（1 起）
        max_seconds: 音频转写只转前 N 秒（默认取配置 audio_max_seconds）
        max_chars: 转写文本截断上限（默认取配置 transcript_max_chars）

    Returns:
        成功: {ok:true, source:"subtitle"/"whisper", transcript, truncated, char_count, duration_used}
        失败: {ok:false, error:"subtitle_unavailable"/"transcribe_unavailable"/"timeout"/"process_error"}
    """
    cfg = settings.config.bilibili_assist
    max_seconds = max_seconds or cfg.audio_max_seconds
    max_chars = max_chars or cfg.transcript_max_chars

    try:
        from bilibili_api import Credential, video as bili_video

        v = bili_video.Video(bvid=bvid, credential=Credential())
        info = await asyncio.wait_for(v.get_info(), timeout=cfg.api_timeout_seconds)
        pages = info.get("pages") or []
        page_duration = pages[p_index - 1].get("duration", 0) if 0 < p_index <= len(pages) else info.get("duration", 0)
        cid = pages[p_index - 1].get("cid") if 0 < p_index <= len(pages) else None
    except asyncio.TimeoutError:
        logger.warning("B站 get_info 超时：bvid=%s", bvid)
        return {"ok": False, "error": "timeout"}
    except Exception as e:  # noqa: BLE001
        logger.warning("B站视频信息获取失败：%s bvid=%s", e, bvid)
        return {"ok": False, "error": "api_error"}

    # a) 字幕优先：get_subtitle → subtitle_url 下载 json 转文字
    if cid:
        try:
            subtitle = (await asyncio.wait_for(v.get_subtitle(cid=cid), timeout=cfg.api_timeout_seconds)) or {}
            subtitle_url = _pick_subtitle_url(subtitle)
            if subtitle_url:
                transcript = await asyncio.wait_for(
                    _download_subtitle_text(subtitle_url), timeout=cfg.api_timeout_seconds
                )
                if transcript.strip():
                    return _build_ok("subtitle", transcript, max_chars, page_duration)
        except asyncio.TimeoutError:
            logger.info("字幕获取超时，转音频转写：bvid=%s p=%s", bvid, p_index)
        except Exception as e:  # noqa: BLE001
            logger.info("字幕获取失败，转音频转写：%s bvid=%s p=%s", e, bvid, p_index)

    # b) 无字幕 → 音频转写（whisper）
    # bili-cli 固定取第 1 分 P 音频：多 P 视频 p>1 且无字幕时 fail-closed，
    # 不转写第 1 分 P 伪装成"已读取第 N 集内容"（防数据误导，P1 审查修复）
    if p_index > 1:
        return {"ok": False, "error": "multi_page_whisper_unsupported"}
    if not cfg.enabled:
        return {"ok": False, "error": "subtitle_unavailable"}
    api_key = reveal_secret(settings.secrets.GROQ_API_KEY)
    if not api_key:
        return {"ok": False, "error": "transcribe_unavailable"}

    out_dir = tempfile.mkdtemp(prefix="bili_assist_")
    try:
        async def _run_transcribe() -> tuple[str, int, int]:
            segments = await _download_audio_segments(bvid, out_dir, cfg.bili_cli_path, cfg.bili_cli_timeout_seconds)
            kept, duration_used = _truncate_segments(segments, max_seconds)
            semaphore = asyncio.Semaphore(cfg.concurrent_segments)
            async with httpx.AsyncClient(timeout=cfg.groq_timeout_seconds) as client:
                texts = await asyncio.gather(
                    *[
                        _transcribe_segment(semaphore, client, seg, cfg.groq_model, api_key, idx)
                        for idx, seg in enumerate(kept)
                    ]
                )
            non_empty = [t for t in texts if t]
            if not non_empty:
                raise _BiliAudioError("transcribe_unavailable")
            return "\n".join(non_empty).strip(), duration_used, len(texts) - len(non_empty)

        # 整体硬性执行预算：超过即返回 timeout 结构化失败，避免长音频转写无限阻塞对话轮
        transcript, duration_used, failed_segments = await asyncio.wait_for(
            _run_transcribe(), timeout=cfg.transcribe_total_timeout_seconds
        )
        return _build_ok("whisper", transcript, max_chars, duration_used, failed_segments)
    except asyncio.TimeoutError:
        logger.info("转写超时（%ss）bvid=%s", cfg.transcribe_total_timeout_seconds, bvid)
        return {"ok": False, "error": "timeout"}
    except _BiliAudioError as e:
        return {"ok": False, "error": e.code}
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


# ---- 内部实现 ----

class _BiliAudioError(Exception):
    """bili audio 子进程失败，code 对应对外错误码。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _pick_subtitle_url(subtitle: dict) -> str | None:
    """从 get_subtitle 返回结构挑一条可用字幕 URL（AI 字幕或人工字幕）。"""
    for item in (subtitle.get("subtitles") or []):
        url = item.get("subtitle_url")
        if url:
            return f"https:{url}" if url.startswith("//") else url
    return None


async def _download_subtitle_text(subtitle_url: str) -> str:
    """下载字幕 json 并拼接 body[].content 为纯文本。"""
    cfg = settings.config.bilibili_assist
    async with httpx.AsyncClient(timeout=cfg.groq_timeout_seconds) as client:
        resp = await client.get(subtitle_url)
        resp.raise_for_status()
        data = resp.json()
    lines = [item.get("content", "") for item in (data.get("body") or []) if item.get("content")]
    return "\n".join(lines)


async def _download_audio_segments(bvid: str, out_dir: str, cli_path: str, timeout_seconds: int) -> list[str]:
    """调 bili audio 子进程下载并切 25s WAV 片段，返回片段路径列表。

    参数数组传参（无 shell 拼接）。失败抛 _BiliAudioError：
    timeout=超时；process_error=进程失败/无输出；CLI 缺失按 transcribe_unavailable。
    """
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            cli_path,
            "audio",
            bvid,
            "-s",
            str(_SEGMENT_SECONDS),
            "-o",
            out_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except FileNotFoundError:
        logger.warning("bili-cli 未找到：%s", cli_path)
        raise _BiliAudioError("transcribe_unavailable") from None
    except asyncio.TimeoutError:
        logger.warning("bili audio 超时（%ss）：bvid=%s", timeout_seconds, bvid)
        raise _BiliAudioError("timeout") from None
    finally:
        # 无论正常/超时/外部取消（CancelledError），都回收子进程，防止孤儿进程泄漏
        if proc is not None and proc.returncode is None:
            proc.kill()
            try:
                await asyncio.shield(proc.wait())
            except asyncio.CancelledError:
                pass

    if proc.returncode != 0:
        logger.warning(
            "bili audio 失败（exit=%s）：bvid=%s stderr=%s",
            proc.returncode,
            bvid,
            (stderr or b"")[:200].decode(errors="ignore"),
        )
        raise _BiliAudioError("process_error")
    segments = sorted(str(p) for p in Path(out_dir).glob("seg_*.wav"))
    if not segments:
        logger.warning("bili audio 无输出片段：bvid=%s stdout=%s", bvid, (stdout or b"")[:200])
        raise _BiliAudioError("process_error")
    return segments


def _truncate_segments(segments: list[str], max_seconds: int) -> tuple[list[str], int]:
    """音频总时长超过 max_seconds 只保留前 N 个整段（段边界截断）。

    Returns: (保留段列表, 实际转写秒数)
    """
    kept: list[str] = []
    used = 0
    for seg in segments:
        duration = _wav_seconds(seg)
        if kept and used + duration > max_seconds:
            break
        kept.append(seg)
        used += duration
    return kept, used


def _wav_seconds(path: str) -> int:
    """读 WAV 头算实际时长（秒）。"""
    try:
        with wave.open(path, "rb") as w:
            return round(w.getnframes() / w.getframerate())
    except Exception:  # noqa: BLE001 坏文件按 1 段计，不阻塞整体
        return _SEGMENT_SECONDS


async def _transcribe_segment(
    semaphore: asyncio.Semaphore,
    client: httpx.AsyncClient,
    wav_path: str,
    model: str,
    api_key: str,
    seg_index: int,
) -> str:
    """并发转写单段 WAV（并发上限由 semaphore 控制）。失败重试 1 次（0.5s 退避），
    仍失败返回空串由调用方兜底（整体 transcript 为空则报 transcribe_unavailable）。"""
    async with semaphore:
        data = Path(wav_path).read_bytes()
        for attempt in (1, 2):
            try:
                resp = await client.post(
                    _GROQ_TRANSCRIBE_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (f"seg_{seg_index:03d}.wav", data, "audio/wav")},
                    data={"model": model},  # 不传 language，让 whisper 自动识别中/英文
                )
                resp.raise_for_status()
                return (resp.json().get("text") or "").strip()
            except Exception as e:  # noqa: BLE001
                logger.info("groq 转写失败（段 %s，尝试 %s/2）：%s", seg_index, attempt, e)
                if attempt == 1:
                    await asyncio.sleep(0.5)
        return ""


def _build_ok(
    source: str, transcript: str, max_chars: int, duration_used: int, failed_segments: int = 0
) -> dict:
    """组装成功返回：统一截断 max_chars 并标注 truncated/char_count/duration_used。
    部分分段失败时标注 partial=true + failed_segments，让 LLM 明确内容不完整。"""
    truncated = len(transcript) > max_chars
    clipped = transcript[:max_chars]
    result = {
        "ok": True,
        "source": source,
        "transcript": clipped,
        "truncated": truncated,
        "char_count": len(clipped),
        "duration_used": duration_used,
    }
    if failed_segments:
        result["partial"] = True
        result["failed_segments"] = failed_segments
    return result
