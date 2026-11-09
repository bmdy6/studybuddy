from __future__ import annotations

import base64
import mimetypes
from io import BytesIO
from typing import Any

__all__ = ["encode_image_for_vision", "encode_bytes_for_vision"]

# 视觉 LLM 图片编码统一入口：所有「图片 -> base64 -> LLM」的路径都走这里，
# 统一做缩放压缩，避免散落各处各自裸 base64 导致大图直接喂 LLM 浪费 token。
# 放 app/utils（稳定底层），业务域单向依赖，不反向依赖任何业务模块。


def _compress_pil_to_jpeg_data_url(image, max_long_side: int, jpeg_quality: int) -> str:
    """把 PIL Image 缩放压缩成 JPEG base64 data URL。

    长边超过 max_long_side 时按比例缩放（LANCZOS），统一转 JPEG（quality + optimize）。
    返回形如 ``data:image/jpeg;base64,...`` 的字符串。
    """
    from PIL import Image

    long_side = max(image.size)
    if long_side > max_long_side:
        ratio = max_long_side / long_side
        new_size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
    b64 = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"


def encode_image_for_vision(image_path: str, max_long_side: int = 1800, jpeg_quality: int = 82) -> dict[str, Any]:
    """读取图片文件，缩放压缩后转 base64 data URL 供视觉 LLM 使用。

    解码失败（非图片或损坏）时回退为原始字节 base64，按文件后缀猜 MIME。
    """
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(image_path) as img:
            url = _compress_pil_to_jpeg_data_url(img.convert("RGB"), max_long_side, jpeg_quality)
        return {"type": "image_url", "image_url": {"url": url}}
    except (UnidentifiedImageError, OSError):
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def encode_bytes_for_vision(data: bytes, max_long_side: int = 1800, jpeg_quality: int = 82) -> dict[str, Any]:
    """对内存中的图片字节（如 PDF 渲染出的 PNG）做同样的缩放压缩后转 data URL。

    与 :func:`encode_image_for_vision` 行为一致，只是输入是 bytes 而非文件路径。
    解码失败时回退为原始字节 base64（按 PNG 处理，因为常见来源是 PDF 页面渲染）。
    """
    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(BytesIO(data)).convert("RGB")
        url = _compress_pil_to_jpeg_data_url(image, max_long_side, jpeg_quality)
        return {"type": "image_url", "image_url": {"url": url}}
    except (UnidentifiedImageError, OSError):
        b64 = base64.b64encode(data).decode()
        return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
