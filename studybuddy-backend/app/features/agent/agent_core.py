"""通用 Agent 骨架（公共层，跨空间复用）。

职责：多轮循环 + 工具调用解析执行 + 超时熔断 + 工具结果回填。
空间差异通过外部传入：system 提示词（md）、tools 集合、tool handler 映射。
- 学习空间主循环是 agent_loop.py（与学习服务/守卫深度耦合的超集）；
- 本模块是通用子集，兴趣空间（hobbybuddy）等轻量空间复用；
- 未来多空间底座统一时，学习空间也可逐步迁移到本模块。
LLM 调用复用 app.core.ai_service（含重试/熔断）。
"""

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

from app.core import ai_service  # 底座：LLM 调用（复用重试/熔断）

logger = logging.getLogger(__name__)

MAX_TURNS = 8
TOOL_TIMEOUT_SEC = 20

# handler 签名：async (args: dict, db: Session, user_id: int) -> dict
ToolHandler = Callable[[dict, Session, int | None], Awaitable[dict]]


def _parse_tool_calls(message: Any) -> list[dict]:
    """从 OpenAI 返回的 message 提取工具调用列表。"""
    tool_calls = getattr(message, "tool_calls", None) or []
    parsed = []
    for tc in tool_calls:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        parsed.append({"id": tc.id, "name": tc.function.name, "arguments": args})
    return parsed


async def run_agent(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]],
    handlers: dict[str, ToolHandler],
    db: Session,
    user_id: int | None,
) -> list[dict[str, Any]]:
    """运行极简 agent 循环，返回更新后的 messages（含最终 assistant 回复）。

    - 每轮 LLM 返回工具调用就执行并回填结果，然后继续下一轮；
    - 工具超时/异常返回结构化失败，不让 AI 声称成功；
    - 达到 MAX_TURNS 强制终止。
    """
    loop_messages = list(messages)
    if system:
        loop_messages = [{"role": "system", "content": system}] + loop_messages

    for _ in range(MAX_TURNS):
        resp = await ai_service.call_llm(loop_messages, tools=tools)
        message = resp.choices[0].message

        tool_calls = _parse_tool_calls(message)
        if not tool_calls:
            # 没有工具调用：正文即最终回复
            loop_messages.append(
                {"role": "assistant", "content": message.content or ""}
            )
            return loop_messages

        # 有工具调用：先回填 assistant（含 tool_calls），再执行每个工具
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": message.content or "",
        }
        if message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ]
        loop_messages.append(assistant_msg)

        for tc in tool_calls:
            handler = handlers.get(tc["name"])
            if handler is None:
                result = {"ok": False, "error": f"未知工具：{tc['name']}"}
            else:
                try:
                    result = await asyncio.wait_for(
                        handler(tc["arguments"], db, user_id), timeout=TOOL_TIMEOUT_SEC
                    )
                except asyncio.TimeoutError:
                    result = {"ok": False, "error": f"工具 {tc['name']} 执行超时"}
                except Exception as exc:  # noqa: BLE001 - 工具失败必须结构化返回，不吞
                    logger.warning("工具 %s 执行失败: %s", tc["name"], exc)
                    result = {
                        "ok": False,
                        "error": f"工具 {tc['name']} 执行失败: {exc}",
                    }
            loop_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    # 达到轮数上限：最后一条若是 assistant 且无正文（只有 tool_calls），补一条收尾消息，
    # 保证调用方总能拿到可展示的正文。
    last = loop_messages[-1] if loop_messages else {}
    if last.get("role") == "assistant" and not (last.get("content") or "").strip():
        loop_messages.append(
            {"role": "assistant", "content": "这轮先到这里，你随时可以继续。"}
        )
    return loop_messages
