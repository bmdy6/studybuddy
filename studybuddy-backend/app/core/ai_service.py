"""LLM 服务层。

封装对小米 MiMo（OpenAI 兼容端点）的调用，配齐超时/重试/熔断（约束 #18）。

用 OpenAI SDK 调 MiMo（OpenAI 兼容协议）。
agent_loop 通过本模块调用 LLM，不直接接触 SDK。

模型与地址由配置提供；工具调用和视觉支持取决于选用的服务。
"""

import asyncio
import time
from typing import Any, cast

from openai import AsyncOpenAI, omit
from openai._types import Omit
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

from app.config import has_secret, reveal_secret, settings

LLM_RETRY_MAX = settings.config.llm.retry_count
LLM_RETRY_BACKOFF_BASE = settings.config.llm.retry_backoff_base
LLM_CIRCUIT_FAIL_THRESHOLD = settings.config.llm.circuit_fail_threshold
LLM_CIRCUIT_RESET_SEC = settings.config.llm.circuit_reset_seconds


class CircuitOpenError(RuntimeError):
    """熔断器开启时抛出，agent_loop 据此降级。"""


class _CircuitBreaker:
    """最简熔断器：closed/open/half-open 三态。单进程内存（单用户场景够用）。"""

    def __init__(self) -> None:
        self._fail_count = 0
        self._state = "closed"
        self._opened_at = 0.0

    def before_call(self) -> None:
        if self._state == "open":
            if time.monotonic() - self._opened_at >= LLM_CIRCUIT_RESET_SEC:
                self._state = "half_open"
            else:
                raise CircuitOpenError(f"LLM 熔断中，{LLM_CIRCUIT_RESET_SEC}s 后重试")

    def on_success(self) -> None:
        self._fail_count = 0
        self._state = "closed"

    def on_failure(self) -> None:
        self._fail_count += 1
        if self._fail_count >= LLM_CIRCUIT_FAIL_THRESHOLD:
            self._state = "open"
            self._opened_at = time.monotonic()


_breaker = _CircuitBreaker()
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """懒加载单例 async client。

    用 AsyncOpenAI 原生 async 接口，agent_loop 用 async for 迭代 stream，
    reasoning 能真正逐 chunk 实时 emit（旧版同步 stream+线程+Queue 会攒批不实时）。
    """
    global _client
    if _client is None:
        if not has_secret(settings.LLM_API_KEY):
            raise RuntimeError("LLM_API_KEY 未配置，请在环境变量中设置")
        _client = AsyncOpenAI(
            api_key=reveal_secret(settings.LLM_API_KEY),
            base_url=settings.LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SEC,
            max_retries=0,
        )
    return _client


def _reasoning_kwargs() -> dict[str, Any]:
    """MiMo 思考程度。none=关思考（thinking.type=disabled，最快）；空/其他=默认开思考。
    注：mimo-v2.5 的 low/medium/high 实测不区分强度（都开思考），只有 none 有实际效果。"""
    if settings.config.llm.provider == "openai":
        return {"reasoning_effort": settings.LLM_REASONING_EFFORT} if settings.LLM_REASONING_EFFORT else {}
    if settings.LLM_REASONING_EFFORT == "none":
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


def _token_limit_kwargs(max_tokens: int) -> dict[str, Any]:
    field = "max_completion_tokens" if settings.config.llm.provider == "openai" else "max_tokens"
    return {field: max_tokens}


async def call_llm(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    system: str | None = None,
    max_tokens: int = 4096,
) -> Any:
    """调用 LLM（OpenAI 兼容格式，非流式）。

    messages 用 OpenAI 格式（role/content/tool_calls/tool_call_id）。
    返回 OpenAI ChatCompletion 对象：response.choices[0].message。
    agent_loop 从 message.content 取文本、message.tool_calls 取工具调用。
    """
    # 把 system 塞进 messages 开头（OpenAI 格式 system 是 role=system 的消息）
    full_messages: list[dict[str, Any]] = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    # OpenAI tools 格式：[{type:function, function:{name,description,parameters}}]
    openai_tools: list[ChatCompletionToolParam] | Omit = omit
    if tools:
        tool_params: list[dict[str, Any]] = []
        for t in tools:
            tool_params.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
            )
        openai_tools = cast(list[ChatCompletionToolParam], tool_params)

    last_err: Exception | None = None
    for attempt in range(LLM_RETRY_MAX + 1):
        _breaker.before_call()
        try:
            resp = await _get_client().chat.completions.create(
                model=settings.LLM_MODEL,
                messages=cast(list[ChatCompletionMessageParam], full_messages),
                tools=openai_tools,
                **_token_limit_kwargs(max_tokens),
                **_reasoning_kwargs(),
            )
            _breaker.on_success()
            return resp
        except CircuitOpenError:
            raise
        except Exception as e:  # noqa: BLE001 - 重试需兜底所有 SDK 错误
            last_err = e
            _breaker.on_failure()
            if attempt < LLM_RETRY_MAX:
                await asyncio.sleep(LLM_RETRY_BACKOFF_BASE**attempt)
                continue
            break
    raise RuntimeError(f"LLM 调用失败（重试 {LLM_RETRY_MAX} 次）: {last_err}")


async def call_llm_stream(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    system: str | None = None,
    max_tokens: int = 4096,
    tool_choice: dict[str, Any] | None = None,
):
    """调用 LLM 流式版（OpenAI 兼容格式，返回 AsyncStream）。

    供 chat 路由 SSE 推送用。调用方用 `async for chunk in stream` 迭代。
    返回 AsyncStream，reasoning/content/tool_calls 逐 chunk 到达，前端实时可见。
    tool_choice 支持 OpenAI 兼容的 named function choice（M0 计划守卫补调用），
    如 {"type": "function", "function": {"name": "draft_study_plan"}}；
    不传时保持默认 auto。
    """
    full_messages: list[dict[str, Any]] = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    openai_tools: list[ChatCompletionToolParam] | Omit = omit
    if tools:
        tool_params: list[dict[str, Any]] = []
        for t in tools:
            tool_params.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
            )
        openai_tools = cast(list[ChatCompletionToolParam], tool_params)

    last_err: Exception | None = None
    for attempt in range(LLM_RETRY_MAX + 1):
        _breaker.before_call()
        try:
            create_kwargs: dict[str, Any] = dict(
                model=settings.LLM_MODEL,
                messages=cast(list[ChatCompletionMessageParam], full_messages),
                tools=openai_tools,
                **_token_limit_kwargs(max_tokens),
                stream=True,
                stream_options={"include_usage": True},
                **_reasoning_kwargs(),
            )
            if tool_choice is not None:
                create_kwargs["tool_choice"] = tool_choice
            stream = await _get_client().chat.completions.create(**create_kwargs)
            _breaker.on_success()
            return stream
        except CircuitOpenError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            _breaker.on_failure()
            if attempt < LLM_RETRY_MAX:
                await asyncio.sleep(LLM_RETRY_BACKOFF_BASE**attempt)
                continue
            break
    raise RuntimeError(f"LLM 调用失败（重试 {LLM_RETRY_MAX} 次）: {last_err}")


def reset_client() -> None:
    """配置变更后重置 client（热重载用）。"""
    global _client
    _client = None
