"""LLM 提示词集中仓库。

所有提示词内容存为 .md 文件，按用途分文件夹（agent/ growth/ exam_vision/ material_vision/）。
- load(name): 读 .md 模板并替换内置 {{BRAND_NAME}}，lru_cache 缓存（启动后首次读文件，之后走内存）。
- render(name, **vars): 读模板并替换 {{key}} 动态占位符（如用户称呼），不缓存。

agent 的 system_prompt/task_system_prompt 在 agent.py 里动态拼装
（基础提示读 .md + 当前日期 + 回复格式 + 用户称呼注入）。

依赖方向：本包只依赖标准库 + app.config，不依赖任何 app.features.*（单向向下）。
版本管理由 git 承担；暂不做数据库版本表 / AB 框架 / 运营后台。

占位符规范（见 AGENTS.md「提示词」条）：
- 静态/品牌：{{BRAND_NAME}}，load() 内置替换。
- 动态变量：{{var}}，render() 替换，调用方传值。
- 统一双花括号，不混用 .format() 单花括号。
"""

from functools import lru_cache
from pathlib import Path

from app.config import settings

_DIR = Path(__file__).parent
_BRAND_PLACEHOLDER = "{{BRAND_NAME}}"


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """按名字读取提示词 .md 模板。

    name 为相对 app/prompts/ 的路径（不含 .md 后缀），如 "growth/daily_summary"。
    进程启动后首次调用读文件，之后走缓存。文件缺失快速失败（约束 #10）。
    内置替换 {{BRAND_NAME}} 为品牌名。动态变量用 render() 替换。
    """
    path = _DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"提示词文件不存在：{path}")
    content = path.read_text(encoding="utf-8").strip()
    return content.replace(_BRAND_PLACEHOLDER, settings.BRAND_NAME)


def render(name: str, **variables: str) -> str:
    """读取模板并替换 {{key}} 占位符。

    用于含动态变量的提示词（如用户称呼 {{student_name}}、冷启动字段 {{field_label}}）。
    不缓存（变量每次可能不同）；模板读取本身走 load() 的 lru_cache。
    变量值由调用方负责（如 display_name 来自 DB，已做 fallback）。
    """
    content = load(name)
    for key, value in variables.items():
        content = content.replace("{{" + key + "}}", value)
    return content
