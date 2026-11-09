"""文件上传工具：COS 优先，本地存储兜底（fail-soft，无 COS 配置时落本地）。

★ 熔断为单进程内存状态（P1 单实例足够），多实例需换 Redis 共享状态。
★ 当 COS_SECRET_ID/COS_BUCKET 任一为空时，自动降级为本地磁盘存储，
  文件落到 uploads/ 目录，nginx 直接静态服务，URL 形如 /sb/uploads/xxx.pdf。
"""

import asyncio
import os
import tempfile
import time
import uuid
from datetime import datetime
from typing import Any

from app.config import has_secret, reveal_secret, settings
from app.constants import COS_CIRCUIT_BREAK_SEC, COS_CIRCUIT_FAIL_THRESHOLD, COS_RETRY_BACKOFF_BASE, COS_RETRY_MAX, COS_UPLOAD_TIMEOUT_SEC

_circuit: dict[str, Any] = {"failures": 0, "open_until": 0.0}

# 本地存储根目录（项目根下的 uploads/）
_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")


def _is_circuit_open() -> bool:
    if _circuit["failures"] >= COS_CIRCUIT_FAIL_THRESHOLD:
        if time.time() < _circuit["open_until"]:
            return True
        # 半开：放行试探，重置计数
        _circuit["failures"] = 0
    return False


def _record_failure() -> None:
    _circuit["failures"] += 1
    if _circuit["failures"] >= COS_CIRCUIT_FAIL_THRESHOLD:
        _circuit["open_until"] = time.time() + COS_CIRCUIT_BREAK_SEC


def _record_success() -> None:
    _circuit["failures"] = 0


def reset_circuit() -> None:
    """测试用：重置熔断状态。"""
    _circuit["failures"] = 0
    _circuit["open_until"] = 0.0


def normalize_local_content_ref(content_ref: str) -> str:
    """规范化本地相对路径，兼容旧版错题照片 local:exams 前缀。"""
    rel = content_ref[6:] if content_ref.startswith("local:") else content_ref
    if rel.startswith("exams/"):
        return f"materials/{rel}"
    return rel


def build_public_url(content_ref: str) -> str:
    """把 content_ref 转成可访问 URL。local: 前缀走 StaticFiles，否则走 COS。"""
    if content_ref.startswith("local:"):
        base = settings.PUBLIC_UPLOAD_BASE_PATH.rstrip("/") or "/uploads"
        return f"{base}/{normalize_local_content_ref(content_ref)}"  # 去掉 local: 前缀，拼 StaticFiles 挂载路径
    return f"https://{settings.COS_BUCKET}.cos.{settings.COS_REGION}.myqcloud.com/{content_ref}"


def upload_file(file_bytes: bytes, ext: str, prefix: str = "materials") -> str:
    """上传文件，返回 file_key（COS 路径或本地相对路径）。

    COS 配置完整时走 COS（带重试/熔断）；未配置时降级本地存储，
    文件落到 uploads/，key 形如 local:materials/2026/06/xxxx.pdf，
    调用方用 build_public_url 拼出 /sb/uploads/... 的可访问 URL。

    prefix：存储分类目录（默认 materials；家庭任务证据用 family_goal），
    决定文件在 COS / 本地 uploads 下的落点。
    """
    now = datetime.now()
    file_subpath = f"{prefix}/{now.year}/{now.month:02d}/{uuid.uuid4().hex}.{ext}"

    # 无 COS 配置 → 本地存储
    if not has_secret(settings.COS_SECRET_ID) or not settings.COS_BUCKET:
        os.makedirs(os.path.join(_UPLOAD_DIR, prefix, str(now.year), f"{now.month:02d}"), exist_ok=True)
        local_full = os.path.join(_UPLOAD_DIR, file_subpath)
        with open(local_full, "wb") as f:
            f.write(file_bytes)
        return f"local:{file_subpath}"

    # 有 COS 配置 → 走 COS 上传（带熔断/重试）
    if _is_circuit_open():
        raise RuntimeError("COS 熔断中，稍后重试")

    from qcloud_cos import CosConfig, CosS3Client  # 延迟导入，测试可 mock

    config = CosConfig(
        Region=settings.COS_REGION,
        SecretId=reveal_secret(settings.COS_SECRET_ID),
        SecretKey=reveal_secret(settings.COS_SECRET_KEY),
        Timeout=COS_UPLOAD_TIMEOUT_SEC,
    )
    client = CosS3Client(config)

    cos_key = file_subpath

    last_err: Exception | None = None
    for attempt in range(COS_RETRY_MAX):
        try:
            client.put_object(
                Bucket=settings.COS_BUCKET,
                Body=file_bytes,
                Key=cos_key,
            )
            _record_success()
            return cos_key
        except Exception as e:
            last_err = e
            time.sleep(COS_RETRY_BACKOFF_BASE * (2**attempt))  # 指数退避

    _record_failure()
    raise RuntimeError(f"COS 上传失败（重试 {COS_RETRY_MAX} 次）: {last_err}")


async def download_to_temp(cos_key: str) -> str:
    """下载 COS 对象到临时文件，返回临时路径（spec 6.3）。

    调用方识别完成后负责 os.unlink 清理。
    熔断/超时/失败 -> 抛 RuntimeError，ensure_extraction 捕获置 failed。
    在线程池执行同步 COS 下载，避免阻塞事件循环。
    """
    if not has_secret(settings.COS_SECRET_ID) or not settings.COS_BUCKET:
        raise RuntimeError("COS 未配置，无法下载素材")

    if _is_circuit_open():
        raise RuntimeError("COS 熔断中，稍后重试")

    def _download() -> str:
        from qcloud_cos import CosConfig, CosS3Client  # 延迟导入，测试可 mock

        config = CosConfig(
            Region=settings.COS_REGION,
            SecretId=reveal_secret(settings.COS_SECRET_ID),
            SecretKey=reveal_secret(settings.COS_SECRET_KEY),
            Timeout=COS_UPLOAD_TIMEOUT_SEC,
        )
        client = CosS3Client(config)
        ext = cos_key.rsplit(".", 1)[-1].lower() if "." in cos_key else "bin"
        tmp = tempfile.NamedTemporaryFile(prefix="material_cos_", suffix=f".{ext}", delete=False)
        tmp.close()
        try:
            response = client.get_object(Bucket=settings.COS_BUCKET, Key=cos_key)
            response["Body"].get_stream_to_file(tmp.name)
            _record_success()
            return tmp.name
        except Exception as exc:  # noqa: BLE001 - 下载失败回到上层兜底
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            _record_failure()
            raise RuntimeError(f"COS 下载失败：{exc}") from exc

    return await asyncio.to_thread(_download)
