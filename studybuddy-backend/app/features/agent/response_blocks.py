"""结构化响应终态协议（AI 回复格式根治核心）。

背景：MiMo 偶发把 \n 输出成空格，导致 markdown 标题/引用/列表全部失效
（生产 testverify session 627 msg 2637）。正则无法可靠恢复被空格化的
`-`/`>`（数学表达式 `a > 0`、`x - b` 存在不可逆歧义）。

本模块定义「结构化响应契约」：模型最终回复必须调用 present_response 工具，
输出 JSON blocks；本模块做 Pydantic 校验 + 确定性渲染 Markdown。换行由代码
生成，不依赖模型，坏格式永远进不了正式输出。

block 类型：paragraph / heading / list / quote / code / formula / table。
字段约束：blocks 1-40 项；文本 strip 后非空；列表 1-20 项；表格列数一致。
block 文本允许行内 **粗体**/`code`/链接/行内公式；禁止块级语法（###/---/行首 >/行首 - ）。
"""

import logging
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

BLOCKS_MAX_COUNT = 40
LIST_ITEMS_MAX_COUNT = 20
FORMULA_LATEX_MAX_LEN = 2000
TABLE_MAX_ROWS = 30
TABLE_MAX_COLS = 10

# 块级语法控制标记（text 内禁止出现；渲染时若强制转义用于 fail-closed 降级）
# 分级检查：paragraph/quote 严格全检；heading 允许编号（"1. 定义" 是合理标题）；
# list item 允许 `- ` 与编号（列表项内部文本）；code/formula/table 不检查。
_BLOCK_LEVEL_MARKERS_STRICT = (  # paragraph/quote：任何块级标记都拒
    re.compile(r"(^|\n)\s*#{1,6}\s"),      # 行首/段首标题
    re.compile(r"(^|\n)\s*---+"),           # 分隔线
    re.compile(r"(^|\n)\s*>\s+"),           # 行首引用
    re.compile(r"(^|\n)\s*[-*+]\s+"),       # 行首无序列表
    re.compile(r"(^|\n)\s*\d+[.、]\s+"),    # 行首有序列表
)
_BLOCK_LEVEL_MARKERS_HEADING = (  # heading：禁标题/分隔线/引用/无序列表，允许编号
    re.compile(r"(^|\n)\s*#{1,6}\s"),
    re.compile(r"(^|\n)\s*---+"),
    re.compile(r"(^|\n)\s*>\s+"),
    re.compile(r"(^|\n)\s*[-*+]\s+"),
)
_BLOCK_LEVEL_MARKERS_LIST_ITEM = (  # list item：禁标题/分隔线/引用，允许 `- ` 与编号
    re.compile(r"(^|\n)\s*#{1,6}\s"),
    re.compile(r"(^|\n)\s*---+"),
    re.compile(r"(^|\n)\s*>\s+"),
)

# fail-closed 降级：把块级控制标记转义成普通文本，不展示坏 markdown
_ESCAPE_BLOCK_MARKERS = (
    (re.compile(r"^\s*#{1,6}\s+(.*)$"), lambda m: f"标题：{m.group(1)}"),
    (re.compile(r"^\s*>+\s?(.*)$"), lambda m: f"▶ {m.group(1)}"),
    (re.compile(r"^\s*-{3,}(?:\s+(.*))?$"), lambda m: f"分隔线 {m.group(1)}" if m.group(1) else "分隔线"),
    (re.compile(r"^\s*[-*+]\s+(.*)$"), lambda m: f"· {m.group(1)}"),
    (re.compile(r"^\s*\d+[.、]\s+(.*)$"), lambda m: f"序号 {m.group(1)}"),
)


class ParagraphBlock(BaseModel):
    type: Literal["paragraph"] = "paragraph"
    text: str = Field(min_length=1, max_length=4000)


class HeadingBlock(BaseModel):
    type: Literal["heading"] = "heading"
    level: Literal[2, 3, 4] = 3
    text: str = Field(min_length=1, max_length=500)


class ListBlock(BaseModel):
    type: Literal["list"] = "list"
    ordered: bool = False
    items: list[str] = Field(min_length=1, max_length=LIST_ITEMS_MAX_COUNT)


class QuoteBlock(BaseModel):
    type: Literal["quote"] = "quote"
    text: str = Field(min_length=1, max_length=2000)


class CodeBlock(BaseModel):
    type: Literal["code"] = "code"
    language: str | None = Field(default=None, max_length=50)
    code: str = Field(min_length=1, max_length=4000)


class FormulaBlock(BaseModel):
    type: Literal["formula"] = "formula"
    latex: str = Field(min_length=1, max_length=FORMULA_LATEX_MAX_LEN)
    display: bool = False


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    headers: list[str] = Field(min_length=1, max_length=TABLE_MAX_COLS)
    rows: list[list[str]] = Field(min_length=1, max_length=TABLE_MAX_ROWS)


ResponseBlock = Annotated[
    Union[
        ParagraphBlock,
        HeadingBlock,
        ListBlock,
        QuoteBlock,
        CodeBlock,
        FormulaBlock,
        TableBlock,
    ],
    Field(discriminator="type"),
]


class ResponseBlocks(BaseModel):
    """present_response 工具入参：结构化内容块列表。"""

    blocks: list[ResponseBlock] = Field(min_length=1, max_length=BLOCKS_MAX_COUNT)

    @field_validator("blocks")
    @classmethod
    def _validate_blocks(cls, blocks: list[ResponseBlock]) -> list[ResponseBlock]:
        for block in blocks:
            _validate_block_text(block)
            text = _block_text(block)
            if text and _contains_block_level_marker(block, text):
                raise ValueError("块文本禁止包含 ###/---/行首> /行首- 等块级语法，请拆分到对应 blocks")
        return blocks


def _block_text(block: ResponseBlock) -> str:
    if isinstance(block, ListBlock):
        return "\n".join(block.items)
    if isinstance(block, TableBlock):
        parts: list[str] = list(block.headers)
        for row in block.rows:
            parts.extend(cell for cell in row if isinstance(cell, str))
        return "\n".join(parts)
    if isinstance(block, CodeBlock):
        return block.code
    if isinstance(block, FormulaBlock):
        return block.latex
    return getattr(block, "text", "")


def _validate_block_text(block: ResponseBlock) -> None:
    """逐项 strip 非空校验：段落/标题/引用文本、列表每项、表格每格、code 整块非空。"""
    text = getattr(block, "text", None)
    if isinstance(text, str) and not text.strip():
        raise ValueError(f"{type(block).__name__} 文本不能为空")
    if isinstance(block, ListBlock):
        for item in block.items:
            if not item.strip():
                raise ValueError("列表项不能为空")
    elif isinstance(block, TableBlock):
        col_count = len(block.headers)
        for row in block.rows:
            if len(row) != col_count:
                raise ValueError("表格行与表头列数不一致")
            for cell in row:
                if not cell.strip():
                    raise ValueError("表格单元格不能为空")
    elif isinstance(block, CodeBlock):
        if not block.code.strip():
            raise ValueError("代码块不能为空")
    elif isinstance(block, FormulaBlock):
        if not block.latex.strip():
            raise ValueError("公式不能为空")


def _contains_block_level_marker(block: ResponseBlock, text: str) -> bool:
    """按 block 类型分级检查块级标记：

    - paragraph/quote：严格全检（任何块级语法都拒，强制走结构化）
    - heading：允许编号（"1. 定义" 是合理标题），禁 ###/---/引用/无序列表
    - list item：允许 `- ` 与编号（列表项内部文本），禁 ###/---/引用
    - code/formula/table：不检查（自由内容）
    """
    if isinstance(block, (ParagraphBlock, QuoteBlock)):
        return any(pattern.search(text) for pattern in _BLOCK_LEVEL_MARKERS_STRICT)
    if isinstance(block, HeadingBlock):
        return any(pattern.search(text) for pattern in _BLOCK_LEVEL_MARKERS_HEADING)
    if isinstance(block, ListBlock):
        return any(
            pattern.search(item)
            for pattern in _BLOCK_LEVEL_MARKERS_LIST_ITEM
            for item in block.items
        )
    return False


def render_response_blocks(blocks: list[ResponseBlock] | ResponseBlocks) -> str:
    """把结构化 blocks 确定性渲染成规范 Markdown（纯函数，换行由代码生成）。

    渲染规则：
    - 段落：单行 + 前后空行
    - 标题：`### 文本` + 前后空行
    - 引用：`> 文本` + 前后空行
    - 列表：每项一行，前后空行
    - 代码：```language 块
    - 公式：display 用 $$...$$，inline 用 $...$
    - 表格：GFM 表格 + 分隔行
    所有 block 之间以空行分隔，保证 react-markdown 正确解析。
    """
    if isinstance(blocks, ResponseBlocks):
        blocks = blocks.blocks

    rendered: list[str] = []
    for block in blocks:
        rendered.append(_render_block(block))
    # 每个 block 渲染结果内部已带尾部空行，整体拼接后去除多余尾部空白
    return "\n".join(rendered).rstrip() + "\n"


def _render_block(block: ResponseBlock) -> str:
    if isinstance(block, ParagraphBlock):
        return f"{block.text}\n\n"
    if isinstance(block, HeadingBlock):
        return f"{'#' * block.level} {block.text}\n\n"
    if isinstance(block, QuoteBlock):
        return f"> {block.text}\n\n"
    if isinstance(block, ListBlock):
        marker = "1." if block.ordered else "-"
        return "\n".join(f"{marker} {item}" for item in block.items) + "\n\n"
    if isinstance(block, CodeBlock):
        lang = block.language or ""
        return f"```{lang}\n{block.code}\n```\n\n"
    if isinstance(block, FormulaBlock):
        delimiter = "$$" if block.display else "$"
        return f"{delimiter}{block.latex}{delimiter}\n\n"
    if isinstance(block, TableBlock):
        return _render_table(block)
    raise TypeError(f"未知 block 类型：{type(block).__name__}")


def _render_table(block: TableBlock) -> str:
    header_row = "| " + " | ".join(block.headers) + " |"
    separator_row = "| " + " | ".join("---" for _ in block.headers) + " |"
    body_rows = ["| " + " | ".join(cell for cell in row) + " |" for row in block.rows]
    return "\n".join([header_row, separator_row, *body_rows]) + "\n\n"


def parse_response_blocks(raw_arguments: str) -> ResponseBlocks:
    """解析并校验 present_response 工具入参（JSON 字符串）。

    容错（真实 MiMo 行为）：
    1. blocks 偶发被序列化成字符串（{"blocks": "[{...}]"}）→ 内层再解析；
    2. 内层偶发用单引号（Python 风格）→ ast.literal_eval 兜底。
    校验失败抛 ValueError，由调用方走 fail-closed 降级（安全 paragraph）。
    """
    import ast as _ast
    import json as _json

    data = _json.loads(raw_arguments)
    if not isinstance(data, dict):
        raise ValueError("present_response 参数必须是 JSON 对象")
    blocks_value = data.get("blocks")
    if isinstance(blocks_value, str):
        # MiMo 偶发把 blocks 序列化成字符串：内层再 parse 一次
        parsed_inner: object | None = None
        for loader in (_json.loads, _ast.literal_eval):
            try:
                parsed_inner = loader(blocks_value)
                break
            except (ValueError, TypeError, SyntaxError):
                continue
        if parsed_inner is None:
            raise ValueError("blocks 字段是字符串但内层 JSON 解析失败")
        data["blocks"] = parsed_inner
    return ResponseBlocks.model_validate(data)


def safe_paragraph_text(raw_text: str) -> str:
    """fail-closed 降级：把原始文本转义成安全段落文本。

    保留数学语义（a > 0、x - b 不动），只把明确的块级控制标记转义为普通文本
    （### → 文本、行首 > → "> "、行首 - → "· "、行首编号保留），
    坏 Markdown 不直接出现在 UI。
    """
    text = raw_text.strip()
    if not text:
        return "（暂无回复）"
    lines = []
    for line in text.splitlines():
        for pattern, repl in _ESCAPE_BLOCK_MARKERS:
            line = pattern.sub(repl, line)
        lines.append(line)
    return "\n".join(lines)


def is_free_text_violation(assistant_text: str | None) -> bool:
    """自由正文违规判定：模型直接输出正文且未调用 present_response。

    任何非空自由正文（未走结构化协议）都是协议违规——即使它看起来格式正确，
    因为无法保证换行/结构一致性。豁免的固定文案由调用方直接 emit，不进此判定。
    """
    return bool(assistant_text and assistant_text.strip())
