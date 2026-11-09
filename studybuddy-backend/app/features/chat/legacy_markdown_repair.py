"""历史消息保守 Markdown 适配器（AI 回复格式根治批次 2）。

背景：批次 1 结构化终态协议保证新消息格式正确；但数据库里已存在的旧消息
（如 testverify session 627 msg 2637）是 MiMo 偶发丢换行的单行文本，
`--- ### 标题`、`> 引用`、`- 列表` 全挤一行。正则无法可靠恢复被空格化的
`-`/`>`（数学表达式 `a > 0`、`x - b` 存在不可逆歧义），因此本适配器只做
**高置信修复**，不确定时保留数学语义；无法解析的块级控制标记转义为普通文本。

修复规则（首版，砍掉 SOL 方案规则 5 数学条件无序列表）：
1. 分隔线+标题：`空白+---+空白+###` → `\n\n---\n\n`
2. 句末后标题：`句末标点+空白+###` → `\n\n### `
3. 冒号后引用：`冒号+空白+>+空白+非数字` → `冒号\n> `
4. 连续有序列表：同一行 ≥2 项、从 1 起、严格连续 → 编号前插换行
6. 一般无序列表（保守版）：冒号后开始 + 同段 ≥2 候选 → 拆列表；单个 ` - ` 不拆

实现先保护 code/公式/链接/URL（占位符替换），修复完成后原样放回。
失败策略：修复后 validator 仍命中坏模式 → 转义块级控制标记作普通段落，
记录结构化日志 legacy_markdown_repair=degraded（不记录完整正文）。
"""

import logging
import re

logger = logging.getLogger(__name__)

# ---- 高置信修复正则 ----
_HR_HEADING = re.compile(r"\s+---\s+(?=#{1,6}\s)")
_SENTENCE_HEADING = re.compile(r"(?<=[。！？!?；;])\s+(#{1,6})\s+")
_COLON_QUOTE = re.compile(r"([：:])\s+>\s+(?=[^0-9+\-=<>])")
# 单行内紧凑有序列表编号（从 1 起、严格连续，见 _split_compact_ordered）
_COMPACT_NUMBER = re.compile(r"(^|[\s:：])(\d+)\.\s")
# 无序列表候选：`- ` 后跟非数字/减号内容（避免负号 -4ac 误判）；
# lookbehind 空白，match.start() 精确指向 `-` 本身
_UL_CANDIDATE = re.compile(r"(?<=[\s：:])-\s(?=[^\d\s-])")

# ---- 保护占位符（修复完成后原样放回）----
# 依次为：fenced code / inline code / $$...$$ / $...$ / 链接目标 / http(s) URL
_PROTECT_PATTERNS = (
    re.compile(r"```[\s\S]*?```"),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"\$\$[\s\S]*?\$\$"),
    re.compile(r"\$[^$\n]+?\$"),
    re.compile(r"\[[^\]]*\]\([^)]*\)"),
    re.compile(r"https?://[^\s)\]]+"),
)

# ---- 坏模式 validator（修复后仍命中则降级）----
# 用 [ \t] 而非 \s：合法 markdown 的分隔线/标题是跨行结构（--- 换行 ###），
# 只有同一行内 `--- ###` 挤一起才是坏模式。
_BAD_PATTERNS = (
    re.compile(r"[ \t]---[ \t]#{1,6}[ \t]"),          # 分隔线+标题仍挤一行
    re.compile(r"[^。！？!?；;\n][ \t]#{1,6}[ \t]"),  # 句中标题（非句末后、同行）
    re.compile(r"[：:][ \t]+>[ \t]+"),             # 冒号后引用仍挤
    # 同行紧凑编号：同一行内出现至少 2 个 `数字. `（用 [ \t] 限定同行，避免把
    # 已分行的合法有序列表误判为坏模式）
    re.compile(r"(^|[ \t])\d+\.\s.*(?:[ \t])\d+\.\s"),
)

# ---- 降级转义：块级控制标记 → 普通文本 ----
_ESCAPE_BLOCK_MARKERS = (
    (re.compile(r"^\s*#{1,6}\s+(.*)$"), lambda m: f"标题：{m.group(1)}"),
    (re.compile(r"^\s*>+\s?(.*)$"), lambda m: f"▶ {m.group(1)}"),
    (re.compile(r"^\s*-{3,}(?:\s+(.*))?$"), lambda m: f"分隔线 {m.group(1)}" if m.group(1) else "分隔线"),
    (re.compile(r"^\s*[-*+]\s+(.*)$"), lambda m: f"· {m.group(1)}"),
    (re.compile(r"^\s*\d+[.、]\s+(.*)$"), lambda m: f"序号 {m.group(1)}"),
    # 句中残留的标题/分隔线标记（###/--- 几乎不可能是数学内容，可安全转义）
    (re.compile(r"#{1,6}\s+"), lambda m: "标题："),
    (re.compile(r"-{3,}"), lambda m: "分隔线"),
)


def _protect_sensitive(text: str) -> tuple[str, list[str]]:
    """把 code/公式/链接/URL 替换成占位符并保存原文，返回 (masked, originals)。"""
    placeholders: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        token = f"\x00LEGACY_PROTECT_{len(placeholders)}\x00"
        placeholders.append(match.group(0))
        return token

    masked = text
    for pattern in _PROTECT_PATTERNS:
        masked = pattern.sub(_replace, masked)
    return masked, placeholders


def _restore_sensitive(masked: str, placeholders: list[str]) -> str:
    for index, original in enumerate(placeholders):
        masked = masked.replace(f"\x00LEGACY_PROTECT_{index}\x00", original)
    return masked


def _split_compact_ordered_line(line: str) -> str:
    """单行内紧凑有序列表拆分：≥2 项、从 1 起、严格连续才拆；否则原样。

    与前端 normalizeCompactNumberedList 规则一致（含 `**1.` 变体）。
    """
    items = list(_COMPACT_NUMBER.finditer(line))
    if len(items) < 2:
        return line
    numbers = [int(m.group(2)) for m in items]
    if numbers[0] != 1:
        return line
    for index in range(1, len(numbers)):
        if numbers[index] != numbers[index - 1] + 1:
            return line
    result = line
    for index in range(len(items) - 1, -1, -1):
        match = items[index]
        num_start = (match.start() + len(match.group(0)) - len(match.group(2)) - 2)
        separator = "\n\n" if index == 0 else "\n"
        result = result[:num_start] + separator + result[num_start:]
    return f"{result}\n"


def _split_compact_ul_line(line: str) -> str:
    """保守无序列表拆分：同段 ≥2 个 ` - ` 候选且每项含中文冒号/比较符才拆。

    候选判定：` - ` 后跟非数字/减号内容，且该项内（到下一个候选或行尾）
    含中文冒号「：」或比较符（> < >= <= =）——教学列表项特征。
    防误伤：`x - b`、`-4ac`、`y = 2x² - 4x` 不含冒号/比较符 → 不拆。
    单个 ` - ` 一律不拆（首项前保留上下文，项间单换行）。
    """
    matches = list(_UL_CANDIDATE.finditer(line))
    if len(matches) < 2:
        return line
    # 每项起点 = 候选的 `-` 起始位置（换行插在 `-` 前，并去掉 `-` 前多余空白）
    item_starts = []
    for match in matches:
        rest = line[match.end():]
        # 该候选到行尾（下一候选由外层切割保证）含冒号或比较符才算列表项
        if re.search(r"[：:]|[<>]=\s*\d|[<>]\s*[A-Za-zΔ]", rest):
            # 从 `-` 往前跳过空白，换行插在空白前（保留 `- ` 前缀，不留前导空格）
            item_starts.append(match.start())
    if len(item_starts) < 2:
        return line
    result = line
    for index in range(len(item_starts) - 1, 0, -1):
        start = item_starts[index]
        result = result[:start].rstrip() + "\n" + result[start:]
    # 首项前插空行，避免 remark-breaks 把相邻正文吞进列表
    first = item_starts[0]
    result = result[:first].rstrip() + "\n" + result[first:]
    return result


def repair_legacy_markdown(content: str | None) -> str:
    """保守修复历史单行 markdown。幂等：已规范文本不变；空/None 返回空串。

    新消息（批次 1 渲染后）已含规范换行，本函数高置信规则不会改动它们。
    """
    if not content:
        return content or ""
    if not content.strip():
        return ""
    masked, placeholders = _protect_sensitive(content)
    lines = masked.split("\n")
    repaired_lines: list[str] = []
    for line in lines:
        # 高置信规则：分隔线+标题、句末后标题、冒号后引用
        line = _HR_HEADING.sub("\n\n---\n\n", line)
        line = _SENTENCE_HEADING.sub(r"\n\n\1 ", line)
        line = _COLON_QUOTE.sub(r"\1\n> ", line)
        # 有序/无序列表（保守）
        line = _split_compact_ordered_line(line)
        line = _split_compact_ul_line(line)
        repaired_lines.append(line)
    repaired = _restore_sensitive("\n".join(repaired_lines), placeholders)

    # 失败策略：仍命中坏模式 → 转义块级控制标记作普通段落
    if any(pattern.search(repaired) for pattern in _BAD_PATTERNS):
        logger.info("legacy_markdown_repair=degraded")
        return _degrade_escaped(repaired)
    return repaired


def _degrade_escaped(text: str) -> str:
    """把明确残留的块级控制标记转义为普通文本（数学内容不动）。"""
    lines = []
    for line in text.splitlines():
        for pattern, repl in _ESCAPE_BLOCK_MARKERS:
            line = pattern.sub(repl, line)
        lines.append(line)
    return "\n".join(lines)
