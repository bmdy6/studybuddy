#!/usr/bin/env python3
"""试跑可选外部 OCR provider，把图片转成 Markdown。

用法示例：
  cd studybuddy-backend
  MARKDOWN_OCR_PROVIDER=external_cli \
  MARKDOWN_OCR_COMMAND="/tmp/studybuddy-pix2text-venv/bin/python /path/to/ocr.py {photo}" \
  PYTHONPATH=. ../scripts/try_markdown_ocr.py /path/to/homework.png
"""

from __future__ import annotations

import argparse
import sys

from app.services.markdown_ocr_service import recognize_photos_to_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Try configured Markdown OCR provider on local images.")
    parser.add_argument("photos", nargs="+", help="Image paths to recognize")
    args = parser.parse_args()

    result = recognize_photos_to_markdown(args.photos)
    if not result:
        print("外部 OCR 未返回可用 Markdown；上层会回退到 MiMo 视觉模型。", file=sys.stderr)
        return 2
    print(f"provider={result.provider} elapsed_ms={result.elapsed_ms}")
    for warning in result.warnings:
        print(f"warning={warning}", file=sys.stderr)
    print()
    print(result.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
