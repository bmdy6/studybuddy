"""结构化响应终态协议测试（AI 回复格式根治批次 1）。

覆盖：
- render_response_blocks：msg 2637 等价 blocks 渲染含分隔线+标题+quote+列表
- 校验拒绝用例：空 blocks/空文本/超长列表/表格列不一致/块级语法混入
- 数学防误伤：free text 里的数学比较/减法/负号不被块级标记判定误伤
- 自由正文违规 → 强制补调 present_response（不落库原文）
- 强制补调成功：落库 content / SSE text / done.content 三处一致
- 强制补调失败：fail-closed 安全 paragraph（坏 markdown 不出现）
- present_response 与业务工具混用：只执行业务工具，不重复执行
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core import ai_service
from app.features.agent import agent_loop
from app.features.agent.response_blocks import (
    ResponseBlocks,
    is_free_text_violation,
    parse_response_blocks,
    render_response_blocks,
    safe_paragraph_text,
)


# ---- render_response_blocks 纯函数 ----

def test_render_blocks_msg2637_equivalent():
    """msg 2637 等价 blocks 渲染：段落 + 分隔线标题 + quote + 无序列表。"""
    blocks = ResponseBlocks.model_validate(
        {
            "blocks": [
                {"type": "paragraph", "text": "对！**第 3 个** 不是一元二次函数，因为它有 x³。"},
                {"type": "heading", "level": 3, "text": "第二块：抛物线与顶点"},
                {"type": "quote", "text": "顶点 = (-b/2a, f(-b/2a))"},
                {
                    "type": "list",
                    "ordered": False,
                    "items": ["a > 0：开口朝上，顶点是最低点", "a < 0：开口朝下，顶点是最高点"],
                },
            ]
        }
    )
    rendered = render_response_blocks(blocks)
    assert "对！**第 3 个** 不是一元二次函数，因为它有 x³。" in rendered
    assert "### 第二块：抛物线与顶点" in rendered
    assert "> 顶点 = (-b/2a, f(-b/2a))" in rendered
    assert "- a > 0：开口朝上，顶点是最低点" in rendered
    assert "- a < 0：开口朝下，顶点是最高点" in rendered
    # 标题/引用/列表是独立行（不是挤在段落里）
    assert "\n\n### 第二块：抛物线与顶点\n\n" in rendered
    assert "\n\n> 顶点 = (-b/2a, f(-b/2a))\n\n" in rendered


def test_render_blocks_all_types():
    """全部 block 类型渲染为规范 markdown。"""
    blocks = ResponseBlocks.model_validate(
        {
            "blocks": [
                {"type": "paragraph", "text": "第一段"},
                {"type": "heading", "level": 2, "text": "章节"},
                {"type": "list", "ordered": True, "items": ["一", "二"]},
                {"type": "code", "language": "python", "code": "print(1)"},
                {"type": "formula", "latex": "x = -b/2a", "display": True},
                {"type": "table", "headers": ["a", "b"], "rows": [["1", "2"]]},
            ]
        }
    )
    rendered = render_response_blocks(blocks)
    assert "## 章节" in rendered
    assert "1. 一\n1. 二" in rendered
    assert "```python\nprint(1)\n```" in rendered
    assert "$$x = -b/2a$$" in rendered
    assert "| a | b |" in rendered
    assert "| --- | --- |" in rendered


# ---- 校验拒绝用例 ----

def test_validate_rejects_empty_blocks():
    with pytest.raises(Exception):
        ResponseBlocks.model_validate({"blocks": []})


def test_validate_rejects_empty_text():
    with pytest.raises(Exception):
        ResponseBlocks.model_validate({"blocks": [{"type": "paragraph", "text": "  "}]})


def test_validate_rejects_too_many_list_items():
    with pytest.raises(Exception):
        ResponseBlocks.model_validate(
            {"blocks": [{"type": "list", "ordered": False, "items": [f"项{i}" for i in range(21)]}]}
        )


def test_validate_rejects_table_column_mismatch():
    with pytest.raises(Exception):
        ResponseBlocks.model_validate(
            {
                "blocks": [
                    {
                        "type": "table",
                        "headers": ["a", "b"],
                        "rows": [["1"]],  # 列数不一致
                    }
                ]
            }
        )


def test_validate_rejects_block_markers_in_paragraph_text():
    """paragraph.text 里带 ###/行首 ---/行首 > /行首 - 等块级语法必须拒绝（强制走结构化）。"""
    for bad_text in ["### 标题在段落里", "--- 分隔线在行首", "> 引用混进段落", "- 列表混进段落"]:
        with pytest.raises(Exception):
            ResponseBlocks.model_validate(
                {"blocks": [{"type": "paragraph", "text": bad_text}]}
            )


def test_validate_accepts_inline_separator_in_paragraph():
    """句中 `---`（非行首、非分隔线+标题组合）不是块级语法，不误拦。"""
    ok = ResponseBlocks.model_validate(
        {"blocks": [{"type": "paragraph", "text": "前面 --- 分隔 是普通文本"}]}
    )
    assert len(ok.blocks) == 1


def test_math_expressions_pass_block_marker_check():
    """数学比较/减法/负号不是块级标记：safe_paragraph_text 不破坏数学语义。"""
    math_text = "a > 0；a < 0；Δ >= 0；x <= 1"
    # 自由正文非空即违规（协议层面），转义后数学语义必须保留
    assert is_free_text_violation(math_text) is True
    # 关键：safe_paragraph_text 不破坏数学语义
    for source in [
        "a > 0；a < 0；Δ >= 0；x <= 1",
        "x - b；x - 1；b² - 4ac；-b/2a；-4ac",
        "版本 1.2.3",
        "https://example.com/a-b?q=x>0",
    ]:
        assert safe_paragraph_text(source) == source


def test_safe_paragraph_text_escapes_block_markers():
    """fail-closed 降级：块级控制标记转义，不出现坏 markdown。"""
    result = safe_paragraph_text("### 标题\n- 列表项\n> 引用\n1. 编号")
    assert "标题：标题" in result  # ### → 标题：
    assert "· 列表项" in result  # - → ·
    assert "▶ 引用" in result  # > → ▶
    assert "序号 编号" in result  # 1. → 序号
    # 转义后不再以块级语法开头
    lines = result.splitlines()
    assert not any(line.startswith("### ") for line in lines)
    assert not any(line.startswith("- ") for line in lines)
    assert not any(line.startswith("> ") for line in lines)
    assert not any(line.startswith("1. ") for line in lines)


# ---- parse_response_blocks ----

def test_parse_response_blocks_valid_json():
    parsed = parse_response_blocks(
        json.dumps({"blocks": [{"type": "paragraph", "text": "你好"}]})
    )
    assert isinstance(parsed, ResponseBlocks)
    assert len(parsed.blocks) == 1


def test_parse_response_blocks_invalid_json_raises():
    with pytest.raises(Exception):
        parse_response_blocks("not json")


def test_parse_response_blocks_non_object_raises():
    with pytest.raises(Exception):
        parse_response_blocks(json.dumps(["a", "b"]))


def test_parse_response_blocks_blocks_as_nested_json_string():
    """真实 MiMo 偶发把 blocks 数组序列化成字符串（{"blocks": "[{...}]"}），必须容错。"""
    nested = json.dumps([{"type": "paragraph", "text": "你好"}])
    parsed = parse_response_blocks(json.dumps({"blocks": nested}))
    assert isinstance(parsed, ResponseBlocks)
    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].type == "paragraph"


def test_parse_response_blocks_blocks_string_invalid_inner_raises():
    """blocks 是字符串但内层不是合法 JSON：必须报错走 fail-closed。"""
    with pytest.raises(Exception):
        parse_response_blocks(json.dumps({"blocks": "not-json-list"}))


def test_parse_response_blocks_blocks_string_single_quotes():
    """真实 MiMo 偶发用单引号风格序列化 blocks 字符串：ast.literal_eval 兜底。"""
    inner = "[{'type': 'paragraph', 'text': '单引号内容'}]"
    parsed = parse_response_blocks(json.dumps({"blocks": inner}))
    assert isinstance(parsed, ResponseBlocks)
    assert len(parsed.blocks) == 1


def test_validate_accepts_numbered_heading_text():
    """heading 文本带编号（"1. 定义"）是合理标题，不误拒。"""
    ok = ResponseBlocks.model_validate(
        {"blocks": [{"type": "heading", "level": 3, "text": "1. 定义"}]}
    )
    assert len(ok.blocks) == 1


def test_validate_accepts_numbered_list_items():
    """list item 内部带 `- ` 或编号（列表项文本）不误拒。"""
    ok = ResponseBlocks.model_validate(
        {
            "blocks": [
                {
                    "type": "list",
                    "ordered": False,
                    "items": ["- a > 0：开口朝上", "1. 对称轴：x = -b/2a"],
                }
            ]
        }
    )
    assert len(ok.blocks) == 1


# ---- agent_loop 终态协议（mock LLM）----

def _chunk(content=None, reasoning=None, tool_call=None, finish=None):
    delta = type("D", (), {})()
    delta.content = content
    delta.reasoning_content = reasoning
    delta.tool_calls = None
    if tool_call is not None:
        tc = type("TC", (), {})()
        tc.index = tool_call.get("index", 0)
        tc.id = tool_call.get("id")
        tc.function = type("F", (), {})()
        tc.function.name = tool_call.get("name")
        tc.function.arguments = tool_call.get("arguments")
        delta.tool_calls = [tc]
    choice = type("C", (), {})()
    choice.delta = delta
    choice.finish_reason = finish
    chunk = type("CH", (), {})()
    chunk.choices = [choice]
    return chunk


def _async_iter(items):
    async def _gen():
        for item in items:
            yield item

    return _gen()


def _mock_text_stream(text):
    return _async_iter([_chunk(content=text), _chunk(finish="stop")])


def _mock_present_response_stream(blocks):
    args_str = json.dumps({"blocks": blocks}, ensure_ascii=False)
    return _async_iter(
        [
            _chunk(tool_call={"index": 0, "id": "call_1", "name": "present_response", "arguments": ""}),
            _chunk(tool_call={"index": 0, "id": None, "name": None, "arguments": args_str}),
            _chunk(finish="tool_calls"),
        ]
    )


def test_free_text_forced_to_present_response():
    """模型直接输出自由正文（无工具调用）→ 不 emit 原文、不落库原文，强制补调。"""
    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    raw_text = "对！**第 3 个** 不是一元二次函数 --- ### 标题 挤在一行"
    streams = [
        _mock_text_stream(raw_text),  # 第一轮：自由正文违规
        _mock_present_response_stream(  # 强制补调：present_response
            [{"type": "paragraph", "text": "对！第 3 个 不是一元二次函数。最 高次数是 3。"}]
        ),
    ]
    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "第 3 个是吗？"}],
                role="student",
                db=type("DB", (), {"get": lambda *a: None})(),
                teacher_id=2,
                emit=collect,
            )
        )
    # 原文（坏 markdown）不落库
    assert not any(
        msg.get("role") == "assistant" and raw_text in (msg.get("content") or "")
        for msg in result
    )
    # 落库的是渲染后的结构化正文
    final = result[-1].get("content") or ""
    assert "对！第 3 个 不是一元二次函数。" in final
    # SSE text 与落库一致
    text_events = [d for t, d in events if t == "text"]
    assert text_events
    assert text_events[-1]["content"] == final


def test_forced_success_three_places_consistent():
    """forced 成功：落库 content / SSE text / done.content（最终 assistant content）三处一致。"""
    events: list[tuple[str, dict]] = []
    blocks = [
        {"type": "paragraph", "text": "你判断对了！"},
        {"type": "heading", "level": 3, "text": "第二块"},
        {"type": "list", "ordered": False, "items": ["a > 0：向上", "a < 0：向下"]},
    ]
    expected = render_response_blocks(
        ResponseBlocks.model_validate({"blocks": blocks})
    )

    async def collect(evt_type, data):
        events.append((evt_type, data))

    streams = [
        _mock_text_stream("自由正文 违规内容 --- ### 无结构"),
        _mock_present_response_stream(blocks),
    ]
    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "请继续"}],
                role="student",
                db=type("DB", (), {"get": lambda *a: None})(),
                teacher_id=2,
                emit=collect,
            )
        )
    final_content = result[-1].get("content") or ""
    text_events = [d for t, d in events if t == "text"]
    assert final_content == expected
    assert text_events[-1]["content"] == expected


def test_forced_fail_closed_safe_paragraph():
    """强制补调仍失败 → fail-closed：只落安全 paragraph，坏 markdown 标记不出现。"""
    events: list[tuple[str, dict]] = []
    raw_text = "### 挤在一起的标题\n--- 分隔线\n- 列表项"

    async def collect(evt_type, data):
        events.append((evt_type, data))

    streams = [
        _mock_text_stream(raw_text),  # 自由正文违规
        _mock_text_stream("还是自由正文"),  # 强制补调仍无 present_response
    ]
    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "解释一下"}],
                role="student",
                db=type("DB", (), {"get": lambda *a: None})(),
                teacher_id=2,
                emit=collect,
            )
        )
    final = result[-1].get("content") or ""
    # 块级标记被转义，不出现坏 markdown 结构
    assert "挤在一起的标题" in final
    assert "分隔线" in final
    assert "列表项" in final
    # 不出现以块级语法开头的行
    lines = final.splitlines()
    assert not any(line.startswith("### ") for line in lines)
    assert not any(line.startswith("---") for line in lines)
    assert not any(line.startswith("- ") for line in lines)
    assert not any(line.startswith("> ") for line in lines)
    # SSE text 与落库一致
    text_events = [d for t, d in events if t == "text"]
    assert text_events
    assert text_events[-1]["content"] == final


def test_present_response_terminal_renders_directly():
    """模型直接调用 present_response（不违规）：渲染 emit，不做强制补调。"""
    events: list[tuple[str, dict]] = []
    blocks = [{"type": "paragraph", "text": "直接结构化回复"}]

    async def collect(evt_type, data):
        events.append((evt_type, data))

    streams = [_mock_present_response_stream(blocks)]
    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "你好"}],
                role="student",
                db=type("DB", (), {"get": lambda *a: None})(),
                teacher_id=2,
                emit=collect,
            )
        )
    assert result[-1].get("content") == "直接结构化回复\n"
    text_events = [d for t, d in events if t == "text"]
    assert text_events[-1]["content"] == "直接结构化回复\n"
    # 不落 tool_calls（协议工具不是业务动作）
    assert "tool_calls" not in result[-1] or not result[-1].get("tool_calls")


def test_present_response_mixed_with_business_tool_executes_business_only():
    """present_response 与业务工具混用：只执行业务工具（query_error_book），不重复执行。"""
    events: list[tuple[str, dict]] = []
    business_args = json.dumps({"student_id": 2}, ensure_ascii=False)
    present_args = json.dumps(
        {"blocks": [{"type": "paragraph", "text": "不应出现的终态"}]}, ensure_ascii=False
    )

    def make_mixed_stream():
        return _async_iter(
            [
                _chunk(tool_call={"index": 0, "id": "call_1", "name": "query_error_book", "arguments": ""}),
                _chunk(tool_call={"index": 0, "id": None, "name": None, "arguments": business_args}),
                _chunk(tool_call={"index": 1, "id": "call_2", "name": "present_response", "arguments": ""}),
                _chunk(tool_call={"index": 1, "id": None, "name": None, "arguments": present_args}),
                _chunk(finish="tool_calls"),
            ]
        )

    async def collect(evt_type, data):
        events.append((evt_type, data))

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[make_mixed_stream()]):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "查一下错题然后回复"}],
                role="student",
                db=type("DB", (), {"get": lambda *a: None})(),
                teacher_id=2,
                emit=collect,
            )
        )
    # 业务工具被执行
    tool_calls_emitted = [d for t, d in events if t == "tool_call"]
    assert any(d["name"] == "query_error_book" for d in tool_calls_emitted)
    # present_response 未被当作终态处理（未 emit 其渲染文本）
    text_events = [d for t, d in events if t == "text"]
    assert not any("不应出现的终态" in (d.get("content") or "") for d in text_events)


def test_extract_present_arguments_text_various_bad_formats():
    """fail-closed 降级：从各种坏格式 arguments 尽力提取可读文本（不丢内容）。"""
    # 1. 正常数组
    assert "你好" in agent_loop._extract_present_arguments_text(
        json.dumps({"blocks": [{"type": "paragraph", "text": "你好"}]})
    )
    # 2. blocks 是 JSON 字符串
    nested = json.dumps([{"type": "paragraph", "text": "字符串内层"}])
    assert "字符串内层" in agent_loop._extract_present_arguments_text(
        json.dumps({"blocks": nested})
    )
    # 3. blocks 是单引号字符串（ast.literal_eval）
    assert "单引号内容" in agent_loop._extract_present_arguments_text(
        json.dumps({"blocks": "[{'type': 'paragraph', 'text': '单引号内容'}]"})
    )
    # 4. 列表 block
    assert "开口朝上" in agent_loop._extract_present_arguments_text(
        json.dumps({"blocks": [{"type": "list", "items": ["a>0 开口朝上", "a<0 开口朝下"]}]})
    )
    # 5. 空/坏外层
    assert agent_loop._extract_present_arguments_text("") == ""
    assert agent_loop._extract_present_arguments_text("not json at all") != ""
