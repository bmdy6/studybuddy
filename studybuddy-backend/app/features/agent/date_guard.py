"""Agent 域统一日期口径（M0/M1 后端日期硬边界）。

结构化草案链路此前信任模型输出的 planned_date/标题日期，跨天旧会话会把
昨天的日期写进今天（P3 B4）。本模块是服务端日期唯一权威：

- local_today()：只依赖 settings.WECHAT_TIMEZONE，不用宿主机 date.today()
- normalize_planned_date()：空/非法/过去日期 → 今天；今天与合法未来日期保留
- sync_today_label_in_title()：只同步「今日/今天…（YYYY-MM-DD）」标题末尾括号日期
- current_round_date_anchor()：本轮 LLM 输入的隐藏日期锚点（只进 LLM 输入，不落库）
- strip_current_round_date_anchor()：服务端逻辑读取用户原文时剥掉锚点前缀
- should_correct_today_label()/correct_today_label_in_text()：最终文本窄范围校正

结构化草案 handler 与 confirm_and_create 共用本模块，保证
handler 返回值 / StudyPlanDraft.draft_data / 正式计划 planned_date 三处一致。
"""

from datetime import date, datetime
from re import Match, compile as _compile
from zoneinfo import ZoneInfo

from app.config import settings
from app.prompts import render

# 标题中明确把某日称为“今天”的标签（窄范围，避免全局替换历史日期）
_TODAY_TITLE_LABELS = ("今日", "今天")
# 标题末尾全角/半角括号内的 YYYY-MM-DD
_TRAILING_PAREN_DATE = _compile(r"[（(](\d{4}-\d{2}-\d{2})[）)]$")

# M1：锚点前缀（与 current_round_date_anchor.md 模板开头一致，服务端逻辑按此前缀剥离）
_ANCHOR_PREFIX = "[服务端本轮时间事实："
# 「今天是 YYYY-MM-DD」：明确把某日称为“今天”
_TODAY_IS_DATE = _compile(r"今天是\s*(\d{4}-\d{2}-\d{2})")
# 段末括号日期：今日/今天…（YYYY-MM-DD），允许后跟句末标点或行尾
_TODAY_LABEL_PAREN_DATE = _compile(r"[（(](\d{4}-\d{2}-\d{2})[）)]\s*[。！？!?，,；;]?$")
# 句边界：最终文本校正按段处理，避免跨句误伤
_SENTENCE_BOUNDARY = _compile(r"(?<=[。！？!?\n；;])")


def local_today() -> date:
    """服务端当前本地日期，统一口径为 settings.WECHAT_TIMEZONE。"""
    return datetime.now(ZoneInfo(settings.WECHAT_TIMEZONE)).date()


def normalize_planned_date(raw: str | None, today: date | None = None) -> str:
    """空/非法/过去日期 → 今天；今天与合法未来日期原样保留。

    today 仅测试固定时钟用，默认取 local_today()。
    """
    today = today or local_today()
    if not raw:
        return today.isoformat()
    value = raw.strip()
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return today.isoformat()
    return value if parsed >= today else today.isoformat()


def sync_today_label_in_title(title: str, planned_date: str) -> str:
    """标题含「今日/今天」且末尾括号内是日期时，同步为权威 planned_date。

    只处理标题末尾「（YYYY-MM-DD）」，不扫描 description/focus/items，
    避免把「复习 2026-07-23 错题」这类历史日期引用改坏。
    """
    if not title or not any(label in title for label in _TODAY_TITLE_LABELS):
        return title
    match = _TRAILING_PAREN_DATE.search(title)
    if not match:
        return title
    try:
        date.fromisoformat(match.group(1))
    except ValueError:
        return title
    return title[: match.start(1)] + planned_date + title[match.end(1):]


def current_round_date_anchor() -> str:
    """本轮 LLM 输入的隐藏日期锚点（只进 LLM 输入，不落库、不展示）。

    文案模板在 app/prompts/agent/current_round_date_anchor.md（提示词不硬编码），
    动态变量（今天/时区）在代码算。调用方把该前缀加到最新一条 user 消息内容前。
    """
    today = local_today()
    return render(
        "agent/current_round_date_anchor",
        today=today.isoformat(),
        timezone=settings.WECHAT_TIMEZONE,
    )


def strip_current_round_date_anchor(content: str) -> str:
    """去掉只进 LLM 输入的日期锚点前缀，返回干净的用户原文（服务端逻辑读取用）。

    锚点只应影响 LLM 输入；画像解析/错题路由/空消息判断等服务端逻辑读到的是原文。
    """
    if not content or not content.startswith(_ANCHOR_PREFIX):
        return content
    end = content.find("]")
    if end == -1:
        return content
    return content[end + 1:]


def should_correct_today_label(user_content: str) -> bool:
    """最终文本窄范围校正的启用条件：最新用户消息含「今天/今日」才启用。

    避免改动普通日期问答/历史引用。
    """
    return bool(user_content) and any(label in user_content for label in _TODAY_TITLE_LABELS)


def correct_today_label_in_text(text: str, today: date | None = None) -> str:
    """窄范围最终文本校正：只把明确称为「今天」的过去日期改为今天。

    命中：`今天是 YYYY-MM-DD`、`今日/今天…（YYYY-MM-DD）`（段末括号日期）且日期早于今天。
    不命中：单独历史日期、`今天复习 2026-07-23 的错题`、未来日期、无「今天/今日」语义的日期。
    调用方负责按「最新用户消息含今天/今日」启用（should_correct_today_label）。
    """
    if not text:
        return text
    today = today or local_today()
    text = _TODAY_IS_DATE.sub(lambda m: _replace_today_label_date(m.group(0), m, today), text)
    segments = _SENTENCE_BOUNDARY.split(text)
    for index, segment in enumerate(segments):
        if not any(label in segment for label in _TODAY_TITLE_LABELS):
            continue
        match = _TODAY_LABEL_PAREN_DATE.search(segment)
        if match:
            segments[index] = _replace_today_label_date(segment, match, today)
    return "".join(segments)


def _replace_today_label_date(full: str, match: Match[str], today: date) -> str:
    """match 命中「今天标签+过去日期」时只替换日期为今天；今天/未来日期原样保留。"""
    raw = match.group(1)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        return full
    if parsed >= today:
        return full
    return full[: match.start(1)] + today.isoformat() + full[match.end(1):]
