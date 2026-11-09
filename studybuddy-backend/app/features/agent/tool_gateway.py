"""Agent 工具网关：在 _dispatch 前对每次工具调用做统一兜底（防 AI 幻觉的硬机制）。

业界调研（docs/99-调研/2026-08-02-Agent工具调用可靠性-业界做法调研.md）：
模型失败是可预测的（该给 JSON 时给散文 / code fence 包 JSON / 截断 / 缺字段），
所以用确定性机制兜底：白名单 + 严格 JSON + schema 校验 + 统一异常 + 循环熔断。

Task 1：白名单校验（G3）+ 严格 JSON 解析（G1）。
后续 Task：Pydantic schema 校验（G2）→ 统一异常（G5）→ 循环熔断（G4）。

关键区分（业界标准）：
- 可重试错误（retryable=True）：JSON 格式错 / 参数校验错 → 返回错误给 AI，AI 修正后重试
- 不可重试：工具执行异常（业务失败）→ 如实告知，不要求 AI 盲目重试
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft7Validator

from .tools import ALL_TOOLS

logger = logging.getLogger(__name__)

# 工具调用层错误（给 AI 看，要求修正）。retryable=True 时 AI 可以修正后重试。
class ToolCallError(Exception):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class GatewayResult:
    """网关统一结果：成功时 data 是工具输出；失败时 error 给 AI 看。"""

    ok: bool
    data: Any = None
    error: str | None = None
    tool: str = ""
    retryable: bool = False


def _strip_code_fence(raw: str) -> str:
    """模型常把 JSON 包在 ```json ... ``` 里，剥掉让 json.loads 能过（业界常见修复）。"""
    s = raw.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


def parse_arguments(tool_name: str, raw_args: str | None, allowed_tools: set[str]) -> GatewayResult:
    """白名单 + 严格 JSON 解析（Task1：G3 + G1）。

    - 工具不在白名单 → 拒绝（可重试：AI 应改用允许的工具）
    - arguments 畸形 JSON → 返回可重试错误，**不静默降级为 {}**
    - 支持剥离 ```json code fence（模型常见输出，业界标准修复）
    - 参数必须是 JSON 对象（dict）
    """
    if tool_name not in allowed_tools:
        return GatewayResult(
            ok=False,
            tool=tool_name,
            retryable=True,
            error=f"工具「{tool_name}」不在可用列表，请改用已提供的工具",
        )
    if not raw_args or not raw_args.strip():
        return GatewayResult(ok=True, tool=tool_name, data={})
    cleaned = _strip_code_fence(raw_args)
    try:
        args = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("agent 工具参数 JSON 解析失败: tool=%s err=%s", tool_name, exc.msg)
        return GatewayResult(
            ok=False,
            tool=tool_name,
            retryable=True,
            error=f"参数不是合法 JSON（{exc.msg}），请重新以合法 JSON 调用 {tool_name}",
        )
    if not isinstance(args, dict):
        return GatewayResult(
            ok=False,
            tool=tool_name,
            retryable=True,
            error=f"参数必须是 JSON 对象（当前是 {type(args).__name__}），请重新调用 {tool_name}",
        )
    return GatewayResult(ok=True, tool=tool_name, data=args)


# === 参数校验（G2，单一事实源） ===
# input_schema（tools.py）既是发给 LLM 的工具参数定义，也是服务端校验源，
# 一份 schema 两用，避免手写 Pydantic 重复定义（DRY）。

# 从 ALL_TOOLS 构建 工具名 -> input_schema 映射
_SCHEMA_BY_TOOL: dict[str, dict] = {
    t["name"]: t["input_schema"] for t in ALL_TOOLS if t.get("input_schema")
}


def validate_args(tool_name: str, args: dict[str, Any]) -> GatewayResult:
    """用工具的 input_schema（JSON Schema）统一校验参数（G2 全量）。

    所有工具自动覆盖（一份 schema 两用）；校验失败返回可重试错误（列出字段），
    AI 修正后重试；不静默用默认值执行。工具不在映射（白名单已拦）则放行。
    """
    schema = _SCHEMA_BY_TOOL.get(tool_name)
    if schema is None:
        return GatewayResult(ok=True, tool=tool_name, data=args)
    errors = list(Draft7Validator(schema).iter_errors(args))
    if errors:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors[:5]
        )
        logger.warning("agent 工具参数校验失败: tool=%s errs=%s", tool_name, details)
        return GatewayResult(
            ok=False,
            tool=tool_name,
            retryable=True,
            error=f"参数校验失败：{details}，请修正后重新调用 {tool_name}",
        )
    return GatewayResult(ok=True, tool=tool_name, data=args)


async def run_tool(
    tool_name: str,
    args: dict[str, Any],
    role: str,
    db: Any,
    teacher_id: int | None,
    dispatch: Any,
    breaker: CircuitBreaker | None = None,
) -> GatewayResult:
    """统一执行工具 + 异常包装（Task3：G5）+ 循环熔断（Task4：G4）。

    执行失败不可重试（retryable=False）：业务失败如实告知，不要求 AI 盲目重试。
    PermissionError / 通用异常都包装为结构化结果，不吞异常、不改写事实。
    传入 breaker 时：熔断中的工具不执行；失败计数，成功复位。
    """
    if breaker is not None and breaker.is_open(tool_name):
        logger.warning("agent 工具已熔断: tool=%s", tool_name)
        return GatewayResult(
            ok=False,
            tool=tool_name,
            error=f"「{tool_name}」连续失败已暂停，请先做别的，不要再调用它",
            retryable=False,
        )
    try:
        output = await dispatch(tool_name, args, role, db, teacher_id)
        result = GatewayResult(ok=True, tool=tool_name, data=output)
    except PermissionError as e:
        logger.warning("agent 工具权限不足: tool=%s", tool_name)
        result = GatewayResult(ok=False, tool=tool_name, error=f"权限不足：{e}", retryable=False)
    except Exception as e:  # noqa: BLE001 - 网关兜底所有业务异常
        logger.warning("agent 工具执行失败：tool=%s", tool_name, exc_info=True)
        result = GatewayResult(ok=False, tool=tool_name, error=f"工具执行失败：{e}", retryable=False)
    if breaker is not None:
        if result.ok:
            breaker.record_success(tool_name)
        else:
            breaker.record_failure(tool_name)
    return result


class CircuitBreaker:
    """循环检测熔断器（Task4：G4）：同一工具连续失败达到阈值即熔断，防止 AI 死循环。

    - 失败计数按工具名隔离（一个工具熔断不影响其他工具）
    - 成功即复位（不永久封锁）
    """

    def __init__(self, max_consecutive_failures: int = 3):
        self.max = max_consecutive_failures
        self._fails: dict[str, int] = {}
        self._open: set[str] = set()

    def record_failure(self, tool_name: str) -> None:
        count = self._fails.get(tool_name, 0) + 1
        self._fails[tool_name] = count
        if count >= self.max:
            self._open.add(tool_name)

    def record_success(self, tool_name: str) -> None:
        self._fails.pop(tool_name, None)
        self._open.discard(tool_name)

    def is_open(self, tool_name: str) -> bool:
        return tool_name in self._open
