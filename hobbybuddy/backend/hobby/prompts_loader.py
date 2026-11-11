"""兴趣空间提示词仓库。

模仿底座 app/prompts/__init__.py：.md 文件 + load() 内置替换 {{BRAND_NAME}}。
品牌名从 hobbybuddy 自己的 config 读取（趣爱好）。
"""

from functools import lru_cache
from pathlib import Path

from hobby.config import settings

_DIR = Path(__file__).parent / "prompts"
_BRAND_PLACEHOLDER = "{{BRAND_NAME}}"


@lru_cache(maxsize=None)
def load(name: str) -> str:
    path = _DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"提示词文件不存在：{path}")
    return (
        path.read_text(encoding="utf-8")
        .strip()
        .replace(_BRAND_PLACEHOLDER, settings.BRAND_NAME)
    )


def render(name: str, **variables: str) -> str:
    """读取模板并替换 {{key}} 动态占位符（如 {{user_name}}）。"""
    content = load(name)
    for key, value in variables.items():
        content = content.replace("{{" + key + "}}", value)
    return content
