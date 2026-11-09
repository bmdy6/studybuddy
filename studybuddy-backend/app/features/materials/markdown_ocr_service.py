"""可选的图片转 Markdown OCR provider。

默认不启用外部 OCR。配置 `MARKDOWN_OCR_PROVIDER=external_cli` 和
`MARKDOWN_OCR_COMMAND` 后，服务会用外部命令尝试识别图片；失败或超时返回 None，
由上层回退到现有 MiMo 视觉模型。
"""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass, field

from app.config import settings


@dataclass
class MarkdownOcrResult:
    markdown: str
    provider: str
    elapsed_ms: int
    warnings: list[str] = field(default_factory=list)


def recognize_photos_to_markdown(photo_paths: list[str]) -> MarkdownOcrResult | None:
    """按配置尝试把图片转成 Markdown。

    返回 None 表示没有可用外部 OCR 结果，上层应继续走视觉模型兜底。
    """
    provider = (settings.MARKDOWN_OCR_PROVIDER or "mimo").strip().lower()
    if provider not in {"external_cli", "auto"}:
        return None
    command_template = (settings.MARKDOWN_OCR_COMMAND or "").strip()
    if not command_template or not photo_paths:
        return None

    started = time.perf_counter()
    chunks: list[str] = []
    warnings: list[str] = []
    timeout = max(1, int(settings.MARKDOWN_OCR_TIMEOUT_SEC or 12))
    for index, photo_path in enumerate(photo_paths, start=1):
        command = _render_command(command_template, photo_path)
        try:
            completed = subprocess.run(  # noqa: S603 - command comes from trusted local .env config
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return None
        except OSError as exc:
            warnings.append(f"第{index}张图片 OCR 命令启动失败：{exc}")
            return None

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            if stderr:
                warnings.append(f"第{index}张图片 OCR 失败：{stderr[:160]}")
            return None
        if stdout:
            chunks.append(f"## 第{index}张图片\n\n{stdout}" if len(photo_paths) > 1 else stdout)

    markdown = "\n\n".join(chunks).strip()
    if not markdown:
        return None
    return MarkdownOcrResult(
        markdown=markdown,
        provider="external_cli",
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnings,
    )


def _render_command(command_template: str, photo_path: str) -> list[str]:
    quoted_photo = shlex.quote(photo_path)
    rendered = (
        command_template.replace("{photo}", quoted_photo)
        .replace("{image}", quoted_photo)
        .replace("{input}", quoted_photo)
    )
    if rendered == command_template:
        rendered = f"{command_template} {quoted_photo}"
    return shlex.split(rendered)
# agg-1
