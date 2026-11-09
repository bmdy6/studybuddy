"""Agent 主循环：把用户消息跑成多轮工具调用，直到纯文本回复或达到上限。

是 agent 域对外的"门面 + 主循环"模块。主循环必须留在本文件（features/agent/agent_loop.py
子模块），而非 features/agent/__init__.py——这样 `from app.features.agent import agent_loop`
返回的是模块对象（不是函数），保留测试中 `agent_loop.X` 属性访问与 `patch.object(agent_loop, X)`
语义。

下方显式 re-export prompts/tools/context/handlers 全部公开符号，让历史调用方
`agent_loop._build_profile_context` 等仍命中。跨子模块的 patch（date、
daily_learning_record_service 等只在子模块内部使用的名字）须指向各自子模块
（agent_loop.context），见测试改动。
"""
import asyncio
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

from app.constants import TOOL_RESULT_PERSIST_THRESHOLD, TOOL_RESULT_PREVIEW_LEN
from app.config import settings
from app.core import ai_service
from app.models.user import User
from app.features.growth import intent_service
from app.features.p2 import profile as profile_service
from .study_plan_confirmation import validate_study_plan_confirmation
from .plan_draft_guard import (
    PLAINTEXT_DRAFT_PLACEHOLDER as _PLAINTEXT_DRAFT_PLACEHOLDER,
    PLAN_GUARD_CORRECTION_PROMPT,
    PLAN_GUARD_FAILURE_TEXT,
    is_plan_negotiation_round,
    looks_like_plaintext_draft,
)
from .response_blocks import (
    ResponseBlocks,
    is_free_text_violation,
    parse_response_blocks,
    render_response_blocks,
    safe_paragraph_text,
)
from .textbook_honesty_guard import (
    TEXTBOOK_GUARD_CORRECTION_PROMPT,
    annotate_draft_textbook_source,
    build_textbook_evidence,
    check_draft_plan_textbook_source,
    extract_lesson_no,
    is_textbook_sensitive_round,
    textbook_body_reply_blocked,
    textbook_honesty_fixed_reply,
)
from .tool_gateway import CircuitBreaker, ToolCallError, parse_arguments, run_tool, validate_args

# 兼容历史 import（from app.core.agent_loop import X）；新增调用方应直接 from app.features.agent.<子模块> import。
from .context import (
    _ROUTE_HINT_INJECTED_MARKER,
    _WRONG_REASON_PREFIX,
    _build_daily_learning_record_context,
    _build_error_import_context,
    _build_learning_memory_context,
    _build_learning_memory_section,
    _build_profile_context,
    _build_task_context,
    _extract_manual_scores,
    _extract_profile_onboarding_args,
    _forced_error_import_tool,
    _forced_profile_onboarding_tool,
    practice_exam_route_hint,
    in_light_practice_round,
    _format_day_label,
    _format_wrong_reason_feedback,
    _has_tool_call_after,
    _is_daily_review_for_target_date,
    _is_study_plan_confirmed,
    _is_wrong_reason_feedback,
    _latest_error_import_batch_id,
    _latest_user_content,
    _latest_user_index,
    _material_ai_readiness,
    _material_status_label,
    _resolve_tool_student_id,
    _shorten_learning_memory_text,
    _should_include_learning_memory,
    _summarize_error_book_groups,
    _summarize_error_review_notes,
    _summarize_material_memory_items,
)
from .handlers import (
    _HANDLERS,
    _can_access_exam_batch,
    _dedupe_keep_order,
    _get_exam_batch_photo_paths,
    _handle_archive_study_plan,
    _handle_bilibili_course_assist,
    _handle_complete_task_item,
    _handle_create_exam,
    _handle_create_practice_exam,
    _handle_create_study_plan,
    _handle_get_attributes,
    _handle_grade_homework_photo,
    _handle_import_errors_grade,
    _handle_import_errors_process,
    _handle_init_attributes,
    _handle_list_materials,
    _handle_present_choice_question,
    _handle_present_profile_question,
    _handle_query_diagnosis,
    _handle_query_error_book,
    _handle_query_feedback,
    _handle_query_learning_map,
    _handle_query_notes,
    _handle_query_recommendations,
    _handle_query_study_plans,
    _handle_read_material,
    _handle_recommend_resource,
    _handle_recognize_homework_photo_markdown,
    _handle_record_feedback,
    _handle_record_interest,
    _handle_save_graded_homework_errors,
    _handle_save_note,
    _handle_save_profile_onboarding,
    _handle_search_paper_sources,
    _handle_update_attributes,
    _handle_update_profile,
    _handle_update_study_plan,
    _load_exam_batch_photos,
    _suggest_material_metadata,
)
from app.prompts import load
from app.prompts.agent import system_prompt, task_system_prompt
from .tools import (
    ALL_TOOLS,
    CHANNEL_GUARDIAN_TOOLS,
    STUDENT_TOOLS,
    TEACHER_TOOLS,
    _TOOL_ARCHIVE_STUDY_PLAN,
    _TOOL_COMPLETE_TASK_ITEM,
    _TOOL_CREATE_EXAM,
    _TOOL_CREATE_PRACTICE_EXAM,
    _TOOL_CREATE_STUDY_PLAN,
    _TOOL_GET_ATTRIBUTES,
    _TOOL_GRADE_HOMEWORK_PHOTO,
    _TOOL_IMPORT_ERRORS_GRADE,
    _TOOL_IMPORT_ERRORS_PROCESS,
    _TOOL_INIT_ATTRIBUTES,
    _TOOL_LIST_MATERIALS,
    _TOOL_PRESENT_PROFILE_QUESTION,
    _TOOL_PRESENT_RESPONSE,
    _TOOL_QUERY_DIAGNOSIS,
    _TOOL_QUERY_ERROR_BOOK,
    _TOOL_QUERY_FEEDBACK,
    _TOOL_QUERY_LEARNING_MAP,
    _TOOL_QUERY_NOTES,
    _TOOL_QUERY_RECOMMENDATIONS,
    _TOOL_QUERY_STUDY_PLANS,
    _TOOL_READ_MATERIAL,
    _TOOL_RECOGNIZE_HOMEWORK_PHOTO_MARKDOWN,
    _TOOL_RECORD_FEEDBACK,
    _TOOL_RECORD_INTEREST,
    _TOOL_RECOMMEND_RESOURCE,
    _TOOL_SAVE_GRADED_HOMEWORK_ERRORS,
    _TOOL_SAVE_NOTE,
    _TOOL_SAVE_PROFILE_ONBOARDING,
    _TOOL_SEARCH_PAPER_SOURCES,
    _TOOL_UPDATE_ATTRIBUTES,
    _TOOL_UPDATE_PROFILE,
    tools_for_actor,
    tools_for_role,
)

logger = logging.getLogger(__name__)

EventHandler = Callable[[str, dict[str, Any]], Awaitable[None]]

_MAX_TURNS = 15

# 空消息轮（注册后冷启动自动触发，前端 skipUserMessage 发空 content）：
# 用户还没说过话，禁止调用会创建/推进学习数据的工具，防止 LLM 面对空输入
# 编造学习事实落库（复现：841 首轮 AI 谎称「背了6个单词」并调 record_feedback）。
EMPTY_MESSAGE_BLOCKED_TOOLS = {
    "record_feedback",
    "complete_task_item",
    "save_note",
    "save_profile_onboarding",
    "create_study_plan",
    "draft_study_plan",
    "import_errors_process",
    "import_errors_grade",
    "create_practice_exam",
}

async def _stream_llm_turn(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system: str,
    emit: EventHandler,
    *,
    buffer_text: bool = True,
    tool_choice: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]], str]:
    """流式调一次 LLM：逐 chunk 累积正文，reasoning 仅服务端兜底，返回 (assistant_text, tool_uses, reasoning_text)。

    tool_uses 元素结构: {id, name, arguments(str)} —— arguments 是 JSON 字符串，调用方解析。
    流式 tool_calls 按 delta.index 累积（首个 chunk 含 id+name，后续 chunk 拼 arguments 片段）。

    reasoning_text 是本轮累积的思考过程全文，供调用方在 content 为空时兜底用作正文
    （MiMo 偶尔把完整答案放进 reasoning_content 而 content 为空，此时需兜底，否则用户看到空白回复）。

    buffer_text=True（结构化终态协议默认）：正文逐 chunk 累积但不实时 emit，由调用方校验后一次性发送，
    避免坏格式（模型丢换行）闪现。工具调用与进度仍流式展示。
    tool_choice：OpenAI 兼容 named function choice（计划守卫补调/present_response 强制补调用）；不传保持默认。

    用 AsyncOpenAI 原生 async stream：`async for chunk in stream` 逐 chunk 消费，
    事件循环不阻塞，正文能真正逐个实时 emit。

    网络韧性：流式迭代中途断开（网络抖动/LLM 超时）时，若尚未向前端 emit 任何
    text/tool_call，可安全重试整个调用；已 emit 内容后断开则不重试（避免重复推送），
    包装成 RuntimeError 由调用方 emit error。建连阶段重试仍由 ai_service.call_llm_stream 负责。
    """
    last_err: Exception | None = None
    for attempt in range(ai_service.LLM_RETRY_MAX + 1):
        assistant_text = ""
        reasoning_text = ""
        tool_acc: dict[int, dict[str, Any]] = {}
        emitted_any = False
        _llm_usage = None
        try:
            llm_kwargs: dict[str, Any] = dict(messages=messages, tools=tools, system=system)
            if tool_choice is not None:
                llm_kwargs["tool_choice"] = tool_choice
            stream = await ai_service.call_llm_stream(**llm_kwargs)
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    _llm_usage = chunk.usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                # 思考过程只作为服务端兜底来源，不能暴露给学生端。
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_text += rc
                # 正文文本：默认逐 chunk 实时 emit（流式输出）；缓冲轮攒完一次性发送
                if delta.content:
                    assistant_text += delta.content
                    if not buffer_text:
                        await emit("text", {"content": delta.content})
                        emitted_any = True
                # 工具调用分片累积
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index if tc.index is not None else 0
                        if idx not in tool_acc:
                            tool_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_acc[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_acc[idx]["arguments"] += tc.function.arguments
                    emitted_any = True
        except ai_service.CircuitOpenError:
            raise
        except Exception as e:  # noqa: BLE001 - 流式中断需兜底所有 SDK/网络错误
            last_err = e
            if emitted_any:
                # 已向前端推送内容，重试会重复，交给上层 emit error
                raise RuntimeError(f"LLM 流式中途断开（已推送内容不重试）: {e}") from e
            if attempt < ai_service.LLM_RETRY_MAX:
                logger.warning("LLM 流式迭代中断（未推送内容），第 %d 次重试：%r", attempt + 1, e)
                await asyncio.sleep(ai_service.LLM_RETRY_BACKOFF_BASE ** attempt)
                continue
            raise RuntimeError(f"LLM 流式调用失败（重试 {ai_service.LLM_RETRY_MAX} 次）: {last_err}") from last_err
        tool_uses = [tool_acc[k] for k in sorted(tool_acc.keys())]
        if _llm_usage:
            logger.info(
                "LLM token input=%d output=%d total=%d",
                _llm_usage.prompt_tokens, _llm_usage.completion_tokens, _llm_usage.total_tokens,
            )
        return assistant_text, tool_uses, reasoning_text
    raise RuntimeError(f"LLM 流式调用失败（重试 {ai_service.LLM_RETRY_MAX} 次）: {last_err}")


_DRAFT_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "draft_study_plan"},
}

# 结构化终态协议：强制补调 present_response 用的 tool_choice
_PRESENT_RESPONSE_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "present_response"},
}

# P1 修复：试卷路由约束已注入但 LLM 未建卷时，强制补调 create_practice_exam 用的 tool_choice
_CREATE_PRACTICE_EXAM_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "create_practice_exam"},
}

# 试卷路由约束与强制补调共用同一模板（正文在 app/prompts/agent/practice_exam_route.md）；
# 仅本次补调调用可见，不持久化。"强制"由 tool_choice + 仅保留建卷工具实现。
PRACTICE_EXAM_ROUTE_RETRY_PROMPT = load("agent/practice_exam_route")

PRESENT_RESPONSE_FAILURE_TEXT = load("agent/present_response_failure")

# 自由正文违规后强制补调的强纠正提示（仅本次补调调用可见，不持久化）
PRESENT_RESPONSE_CORRECTION_PROMPT = load("agent/present_response_correction")


def _is_present_response_tool(tu: dict[str, Any]) -> bool:
    return bool(tu) and tu.get("name") == _TOOL_PRESENT_RESPONSE["name"]


def _extract_present_arguments_text(raw_arguments: str) -> str:
    """从 present_response 原始 arguments 尽力提取可读文本（fail-closed 降级用）。

    模型可能把 blocks 序列化成各种坏格式（字符串/单引号/残缺 JSON），这里尽力
    拼出段落文本；提取失败返回空串，由调用方回退 assistant_text。
    """
    import ast as _ast
    import json as _json

    if not raw_arguments or not raw_arguments.strip():
        return ""
    try:
        data = _json.loads(raw_arguments)
    except Exception:
        # 外层就坏（截断/坏 JSON）：正则尽力提取 text/items 片段，保内容不丢
        return _regex_extract_texts(raw_arguments)
    if not isinstance(data, dict):
        return _regex_extract_texts(raw_arguments)
    blocks_value = data.get("blocks")
    blocks: list[Any] | None = None
    if isinstance(blocks_value, list):
        blocks = blocks_value
    elif isinstance(blocks_value, str):
        for loader in (_json.loads, _ast.literal_eval):
            try:
                parsed = loader(blocks_value)
                if isinstance(parsed, list):
                    blocks = parsed
                    break
            except (ValueError, TypeError, SyntaxError):
                continue
    if not blocks:
        # blocks 字符串内层也坏：对整段原始文本做正则提取
        return _regex_extract_texts(raw_arguments)
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "paragraph")
        if block_type == "list":
            items = block.get("items")
            if isinstance(items, list):
                parts.extend(str(item) for item in items if str(item).strip())
        elif block_type == "table":
            headers = block.get("headers")
            rows = block.get("rows")
            if isinstance(headers, list):
                parts.append(" | ".join(str(h) for h in headers))
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, list):
                        parts.append(" | ".join(str(cell) for cell in row))
        elif block_type == "code":
            code = block.get("code")
            if code:
                parts.append(str(code))
        else:
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
    return "\n".join(parts)[:4000]


# 截断 JSON 兜底：先把双重转义解一层（\\" → "，\\n → \n），再提取 text/code 字段值。
_REGEX_TEXT_FIELD = re.compile(r'["\'](?:text|code)["\']\s*:\s*["\']([^"\']+)["\']')
_REGEX_LIST_ITEM = re.compile(r'["\']([^"\']+)["\']\s*(?:[,}])')


def _regex_extract_texts(raw: str) -> str:
    """坏 JSON 时正则提取可读文本：text/code 字段 + items 数组字符串项。"""
    if not raw:
        return ""
    # 双重转义预处理：只把 \\" → "、\\n → \n（不动中文 UTF-8）
    preprocessed = raw.replace(r'\"', '"').replace(r"\\'", "'").replace(r"\\n", "\\n")
    parts: list[str] = []
    for match in _REGEX_TEXT_FIELD.finditer(preprocessed):
        value = match.group(1).strip()
        if value and value not in parts and not value.startswith("{") and not value.startswith("["):
            parts.append(value)
    if not parts:
        # 退而求其次：提取 items 里的字符串项（列表文本）
        for match in _REGEX_LIST_ITEM.finditer(preprocessed):
            value = match.group(1).strip()
            if (
                value
                and value not in parts
                and not value.startswith("{")
                and not value.startswith("[")
                and not value.startswith("type")
            ):
                parts.append(value)
    if parts:
        return "\n".join(parts)[:4000]
    # 完全提取不到：整体当文本（不丢内容）
    cleaned = raw.strip()[:4000]
    return cleaned if cleaned else ""


def _render_present_response(raw_arguments: str) -> str | None:
    """解析校验并渲染 present_response 入参；失败返回 None（由调用方 fail-closed）。"""
    try:
        blocks = parse_response_blocks(raw_arguments)
    except (ValueError, TypeError) as exc:  # 校验失败走 fail-closed 降级
        logger.warning("present_response 参数校验失败，降级安全段落：%r", exc)
        return None
    return render_response_blocks(blocks)


def _render_fail_closed_paragraph(fallback_text: str) -> str:
    """fail-closed 安全段落渲染：二次校验异常不冒泡，直接返回转义文本。"""
    try:
        return render_response_blocks(
            ResponseBlocks.model_validate(
                {"blocks": [{"type": "paragraph", "text": fallback_text}]}
            )
        )
    except Exception as exc:  # noqa: BLE001 - 二次校验异常不冒泡
        logger.warning("fail-closed 二次校验异常，直接输出转义文本：%r", exc)
        return safe_paragraph_text(fallback_text) or PRESENT_RESPONSE_FAILURE_TEXT


async def _present_response_force_retry(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system: str,
    emit: EventHandler,
) -> tuple[str, list[dict[str, Any]], str]:
    """自由正文违规后强制补调 present_response 一次（结构化终态协议）。

    只保留 present_response 工具 + tool_choice 强制 + 强纠正提示。
    返回 (assistant_text, tool_uses, reasoning_text)；无合法终态工具时返回
    ("", [], "")，由调用方 fail-closed 降级为安全段落。补调正文始终缓冲。
    """
    corrected_system = system + PRESENT_RESPONSE_CORRECTION_PROMPT
    present_only_tools = [
        tool for tool in tools if tool.get("name") == _TOOL_PRESENT_RESPONSE["name"]
    ]
    try:
        text, tool_uses, reasoning = await _stream_llm_turn(
            messages,
            present_only_tools,
            corrected_system,
            emit,
            tool_choice=_PRESENT_RESPONSE_TOOL_CHOICE,
            buffer_text=True,
        )
    except Exception as exc:  # noqa: BLE001 - 网关失败按无结果处理
        logger.warning("present_response 强制补调失败：%r", exc)
        return "", [], ""
    valid = [tu for tu in tool_uses if _is_present_response_tool(tu)]
    if valid:
        return text, valid, reasoning
    return "", [], ""



async def _create_practice_exam_force_retry(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system: str,
    emit: EventHandler,
) -> tuple[str, list[dict[str, Any]], str]:
    """P1 修复：试卷路由约束已注入但 LLM 未建卷时，强制补调 create_practice_exam 一次。

    只保留建卷工具 + tool_choice 强制 + 强纠正提示，逼模型生成完整自练卷参数。
    返回 (assistant_text, tool_uses, reasoning_text)；无合法建卷调用时返回 ("", [], "")。
    """
    corrected_system = system + PRACTICE_EXAM_ROUTE_RETRY_PROMPT
    practice_only_tools = [
        tool for tool in tools if tool.get("name") == "create_practice_exam"
    ]
    try:
        text, tool_uses, reasoning = await _stream_llm_turn(
            messages,
            practice_only_tools,
            corrected_system,
            emit,
            tool_choice=_CREATE_PRACTICE_EXAM_TOOL_CHOICE,
            buffer_text=True,
        )
    except Exception as exc:  # noqa: BLE001 - 网关失败按无结果处理
        logger.warning("create_practice_exam 强制补调失败：%r", exc)
        return "", [], ""
    valid = [tu for tu in tool_uses if tu.get("name") == "create_practice_exam"]
    if valid:
        return text, valid, reasoning
    return "", [], ""


async def _plan_guard_auto_retry(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system: str,
    emit: EventHandler,
) -> tuple[str, list[dict[str, Any]], str]:
    """计划守卫命中后自动补调一次（方案 2.2.2 第 6-7 条）。

    优先 OpenAI 兼容 named tool_choice=draft_study_plan；网关不支持（调用抛错、
    或忽略 tool_choice 仍返回文字/其他工具）时，退回「只保留 draft 工具 + 强纠正提示」
    的一次重试。只有产出 draft_study_plan 工具调用才算成功，返回
    (assistant_text, tool_uses, reasoning_text)；两次都无合法工具结果时返回 ("", [], "")，
    由调用方输出固定失败文案。补调正文始终缓冲：第二次文字草案不会闪现，
    不会作为被拒正文发出或持久化。
    """
    corrected_system = system + PLAN_GUARD_CORRECTION_PROMPT
    draft_only_tools = [tool for tool in tools if tool.get("name") == "draft_study_plan"]
    # E 修复：旧会话历史里的文字草案示例会诱导 LLM 模仿。补调时把 messages 里
    # 命中文字草案形状的 assistant 消息替换为占位提示（只改本轮 LLM 输入，不改库），
    # 避免模型照抄"草案如下："格式而不是调用工具。
    sanitized_messages = [
        {
            **msg,
            "content": _PLAINTEXT_DRAFT_PLACEHOLDER
            if msg.get("role") == "assistant"
            and isinstance(msg.get("content"), str)
            and looks_like_plaintext_draft(msg["content"])
            else msg.get("content"),
        }
        for msg in messages
    ]
    attempts = (
        (tools, _DRAFT_TOOL_CHOICE),   # 第 1 形式：named tool_choice
        (draft_only_tools, None),      # 第 2 形式：只保留 draft 工具 + 强纠正提示
    )
    for attempt, (turn_tools, choice) in enumerate(attempts, start=1):
        try:
            text, tool_uses, reasoning = await _stream_llm_turn(
                sanitized_messages, turn_tools, corrected_system, emit,
                tool_choice=choice, buffer_text=True,
            )
        except Exception as exc:  # noqa: BLE001 - 网关不支持 tool_choice 时切换到下一形式
            logger.warning("plan_guard 补调第 %d 次调用失败，切换重试形式：%r", attempt, exc)
            continue
        if tool_uses and all(tu["name"] == "draft_study_plan" for tu in tool_uses):
            return text, tool_uses, reasoning
        logger.warning("plan_guard 补调第 %d 次未产出 draft_study_plan，切换重试形式", attempt)
    return "", [], ""


async def _textbook_guard_retry(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system: str,
    emit: EventHandler,
) -> tuple[str, list[dict[str, Any]], str]:
    """教材守卫命中后纠正重试一次（方案 2.4.5.4）。

    追加纠正提示后重发同一轮（不强制工具，正文缓冲）。返回 (text, tool_uses, reasoning)；
    调用失败返回 ("", [], "")，由调用方输出固定诚实文案。
    """
    corrected_system = system + TEXTBOOK_GUARD_CORRECTION_PROMPT
    try:
        return await _stream_llm_turn(
            messages, tools, corrected_system, emit, buffer_text=True
        )
    except Exception as exc:  # noqa: BLE001 - 网关失败按无重试结果处理
        logger.warning("textbook_guard 纠正重试调用失败：%r", exc)
        return "", [], ""


async def agent_loop(
    messages: list[dict[str, Any]],
    role: str,
    db: Session,
    teacher_id: int,
    student_id: int = 0,
    emit: EventHandler | None = None,
    business_actor: str | None = None,
    session_type: str = "main",
    task_context: str = "",
    chat_session_id: int | None = None,
) -> list[dict[str, Any]]:
    """运行 agent 循环，返回更新后的 messages。

    session_type="task" 时走任务执行分支：用任务导向系统提示 + task_context，
    不灌全量画像/学习记忆/错题导入（让 AI 按需调工具查，省 token）。
    """
    tools = tools_for_actor(role, business_actor)
    # Tool Gateway：每次会话一个熔断器 + 当前轮工具白名单（防 AI 幻觉硬机制）
    _breaker = CircuitBreaker()
    allowed_tool_names = {t["name"] for t in tools}
    _tool_history: list[dict[str, Any]] = []  # 循环检测：run 级工具调用历史（同工具同参数重复检测）
    is_task = session_type == "task"
    # 决定要注入画像的学生 id：teacher 辅导时用 student_id，student 用自己
    profile_sid = student_id if (role == "teacher" and student_id) else (teacher_id if role == "student" else 0)
    # M2 C：画像里的教材版本（科目->版本）只作证据退路（profile_only），不是目录证据；缺失不编默认值
    textbook_profile_versions: dict[str, Any] | None = None
    if profile_sid:
        try:
            profile_summary = profile_service.get_profile_summary(db, profile_sid)
            versions = (profile_summary.summary or {}).get("textbook_versions")
            if isinstance(versions, dict) and versions:
                textbook_profile_versions = versions
        except Exception:  # noqa: BLE001 - 画像读取失败不阻塞对话
            logger.warning("读取教材版本画像失败：student_id=%s", profile_sid, exc_info=True)

    # 查用户称呼（动态注入，不硬编码弟弟/哥哥；db 无 get 或查询失败时回退默认称呼）
    parent_name = "哥哥"
    student_name = "弟弟"
    db_get = getattr(db, "get", None)
    if db_get is not None:
        try:
            teacher = db_get(User, teacher_id)
            if teacher:
                name = teacher.display_name or teacher.username
                if isinstance(name, str) and name.strip():
                    parent_name = name.strip()
            if profile_sid:
                student = db_get(User, profile_sid)
                if student:
                    name = student.display_name or student.username
                    if isinstance(name, str) and name.strip():
                        student_name = name.strip()
        except Exception:
            logger.warning("查询用户称呼失败，回退默认称呼", exc_info=True)
    system = (
        task_system_prompt(student_name)
        if is_task
        else system_prompt(role, business_actor, student_name, parent_name)
    )
    # 注入当前上下文（学生 id、操作人），让 agent 不用问就知道
    ctx = f"\n\n[当前上下文] 你的 user_id 是 {teacher_id}（角色：{role}）。"
    if role == "teacher" and student_id:
        ctx += f" 你正在辅导的学生 student_id 是 {student_id}。出题/查学情/初始化属性时直接用这个 student_id，不要问。"
    elif role == "student":
        ctx += f" 你就是学生本人，student_id 用你自己的 id {teacher_id}。"

    if is_task:
        # task session：注入任务上下文（计划说明 + 任务目标 + 相关知识点 + 稳定画像）
        ctx += task_context
    else:
        # 注入用户画像：学习档案 + 兴趣，让 agent 知道在跟谁对话、据此个性化推荐
        if profile_sid and business_actor != "channel_guardian":
            ctx += _build_profile_context(db, profile_sid, _latest_user_content(messages), mode=business_actor or "study")
            is_hobby = business_actor == "hobby"
            if not is_hobby:
                # 学习专属上下文（hobby 模式不注入：错题/笔记/每日记录/成长策略是学科体系，
                # 注入会把学科记忆带进兴趣对话——OpenClaw 记忆按需注入原则）
                if role == "student":
                    daily_record_context = _build_daily_learning_record_context(db, profile_sid)
                    if daily_record_context:
                        ctx += daily_record_context
                learning_memory_context = _build_learning_memory_context(
                    db, profile_sid, _latest_user_content(messages)
                )
                if learning_memory_context:
                    ctx += learning_memory_context
        if business_actor != "channel_guardian":
            if business_actor != "hobby":
                # 错题导入是学科体系，hobby 会话不注入
                ctx += _build_error_import_context(messages)
            # 成长策略保留（hobby 也注入）：含 wellbeing 安全护栏（疼痛/受伤/药物→建议告诉家长）
            # + 兴趣探索引导，hobby 场景正需要
            ctx += intent_service.build_growth_strategy_context(
                _latest_user_content(messages)
            )
    system = system + ctx

    # 空消息轮（注册后冷启动自动触发，前端 skipUserMessage 发空 content）：
    # 用户还没说过话。代码层强制首轮只输出冷启动引导问题（画像字段缺失时），
    # 防止 LLM 面对空输入自由发挥（复现：841 假报背单词、842 给选项干等）。
    if not (_latest_user_content(messages) or "").strip():
        system += (
            "\n\n[本轮约束] 用户刚进入会话还没说话（空消息）。"
            "本轮正文**只输出一个冷启动引导问题**（如：你是几年级？1. 七年级 2. 八年级 3. 九年级 4. 其他），"
            "不要自我介绍、不要罗列能力、不要发欢迎语、不要调任何工具、不要编造任何学习事实。"
        )

    _run_started_at = time.time()
    logger.info(
        "agent_run 开始 role=%s session_type=%s student_id=%s system_len=%d",
        role, session_type, profile_sid, len(system),
    )
    if is_task:
        logger.info("agent_run task_context=%s", task_context[:500])
    else:
        logger.info("agent_run ctx_tail=%s", ctx[-500:])

    async def _emit(evt_type: str, data: dict[str, Any]) -> None:
        if emit:
            await emit(evt_type, data)

    for _turn in range(_MAX_TURNS):
        # 高置信工具意图先执行工具，再让 LLM 基于工具结果组织回复。
        # 这样拍题上传不会先产生一段可见思考并根据画像误猜学科。
        route_hint_injected = False
        forced_tool = (
            None
            if business_actor in ("channel_guardian", "hobby")
            else _forced_error_import_tool(messages)
        )
        assistant_text = ""
        reasoning_text = ""
        tool_uses: list[dict[str, Any]] = []
        # M0 计划协商轮：正文先缓冲、校验后一次性发送（普通聊天继续流式）。
        # 只影响“先攒还是边生成边发”，不决定是否建计划。
        plan_negotiation = (
            not is_task
            and business_actor != "channel_guardian"
            and is_plan_negotiation_round(messages)
        )
        if forced_tool:
            tool_uses = [
                {
                    "id": f"forced-{forced_tool['name']}-{_turn}",
                    "name": forced_tool["name"],
                    "arguments": json.dumps(forced_tool["args"], ensure_ascii=False),
                }
            ]
        else:
            # P1 修复：轻练会话后发「做一套卷子」被轻练上下文带偏不建卷——
            # 检测高置信正式试卷意图，注入强路由约束消息，纠偏 LLM 路由到 create_practice_exam。
            route_hint = (
                practice_exam_route_hint(messages)
                if role == "student" and business_actor not in ("channel_guardian", "hobby") and not is_task
                else None
            )
            if route_hint:
                # system 角色注入：服务端指令遵循度高于 assistant 历史，且不落库不展示。
                # 稳定标记放正文开头（[route:create_practice_exam]）：LLM 截断回显约束正文时
                # 从开头复制必带标记，落库过滤命中；供"已注入"检测（与模板正文解耦）。
                messages.append({"role": "system", "content": _ROUTE_HINT_INJECTED_MARKER + "\n" + route_hint})
                route_hint_injected = True
            try:
                # 流式调用：正文统一缓冲（结构化终态协议），由下方终态校验后一次性 emit。
                # reasoning 仅服务端兜底，不暴露给学生端
                assistant_text, tool_uses, reasoning_text = await _stream_llm_turn(
                    messages, tools, system, _emit
                )
            except ai_service.CircuitOpenError:
                fallback = "我现在网络不太好，稍后再试这个。"
                messages.append({"role": "assistant", "content": fallback})
                await _emit("text", {"content": fallback})
                break
            except RuntimeError as e:
                await _emit("error", {"message": str(e)})
                break

            # reasoning 仅在 _stream_llm_turn 里服务端累积，不作为事件暴露
            if role == "student" and profile_sid and business_actor != "hobby":
                forced_tool = _forced_profile_onboarding_tool(messages, db, profile_sid)
                if forced_tool:
                    tool_uses = [
                        {
                            "id": f"forced-{forced_tool['name']}-{_turn}",
                            "name": forced_tool["name"],
                            "arguments": json.dumps(forced_tool["args"], ensure_ascii=False),
                        }
                    ]
        if forced_tool:
            reasoning_text = ""
        has_tool_use = bool(tool_uses)

        # P1 修复兜底：试卷路由约束已注入但 LLM 本轮未调 create_practice_exam（仍被轻练/追问带偏）
        # → 强制补调一次（只留建卷工具 + tool_choice 强制 + 强纠正提示），保证「做卷子」必建卷。
        if route_hint_injected and not any(
            tu.get("name") == "create_practice_exam" for tu in tool_uses
        ):
            logger.info("agent_run_practice_route_retry turn=%d 试卷意图未建卷，强制补调一次", _turn)
            retry_text, retry_tool_uses, retry_reasoning = await _create_practice_exam_force_retry(
                messages, tools, system, _emit
            )
            if retry_tool_uses:
                assistant_text, tool_uses = retry_text or assistant_text, retry_tool_uses
                reasoning_text = retry_reasoning
                has_tool_use = True

        _user_msg = _latest_user_content(messages)
        logger.info(
            "agent_run turn=%d user=%s assistant=%s tools=%s reasoning_len=%d",
            _turn,
            (_user_msg or "")[:200],
            (assistant_text or "")[:200],
            [(tu["name"], tu["arguments"][:100]) for tu in tool_uses] if tool_uses else [],
            len(reasoning_text),
        )

        # reasoning 兜底：MiMo 偶尔把完整答案放进 reasoning_content 而 content 为空，
        # 此时把 reasoning 当正文（守卫按同一文本判定，避免漏拦）。
        reasoning_used = False
        if not has_tool_use and not assistant_text and reasoning_text:
            assistant_text = reasoning_text
            reasoning_used = True

        # M0 草案硬边界：主会话 + 无工具调用 + 文字草案形状 -> 丢弃正文、自动补调一次。
        # 已成功调 draft_study_plan 的轮次按现有工具链继续，守卫不介入。
        plan_guard_applies = (
            not is_task and business_actor != "channel_guardian" and not has_tool_use
        )
        if plan_guard_applies and looks_like_plaintext_draft(assistant_text):
            logger.info("plan_guard_hit turn=%d 文字草案被拒，自动补调一次", _turn)
            retry_text, retry_tool_uses, retry_reasoning = await _plan_guard_auto_retry(
                messages, tools, system, _emit
            )
            if retry_tool_uses:
                logger.info("plan_guard_retry_success turn=%d 补调出 draft_study_plan", _turn)
                assistant_text = retry_text
                reasoning_text = retry_reasoning
                reasoning_used = False
                tool_uses = retry_tool_uses
                has_tool_use = True
                plan_negotiation = True  # 补调正文是缓冲的，需校验后一次性发送
            else:
                logger.info("plan_guard_hard_failure turn=%d 固定失败文案", _turn)
                assistant_text = PLAN_GUARD_FAILURE_TEXT
                reasoning_text = ""
                reasoning_used = False
                messages.append({"role": "assistant", "content": assistant_text})
                await _emit("text", {"content": assistant_text})
                break

        # M2 教材诚实边界：教材敏感轮 + 无有效来源的确定性断言 -> 丢弃正文、纠正重试一次，
        # 仍违规返回固定诚实回复（方案 2.4.5.4）。只拦截断言句式，不拦诚实/疑问句。
        textbook_guard_applies = (
            not is_task
            and business_actor != "channel_guardian"
            and not has_tool_use
            and is_textbook_sensitive_round(messages)
        )
        if textbook_guard_applies:
            textbook_evidence = build_textbook_evidence(messages, textbook_profile_versions)
            if textbook_body_reply_blocked(assistant_text, textbook_evidence.level):
                logger.info("textbook_guard_hit turn=%d 教材确定性断言被拒，纠正重试一次", _turn)
                retry_text, retry_tool_uses, retry_reasoning = await _textbook_guard_retry(
                    messages, tools, system, _emit
                )
                if retry_tool_uses:
                    logger.info("textbook_guard_retry_tool turn=%d 重试转向工具调用", _turn)
                    assistant_text = retry_text
                    reasoning_text = retry_reasoning
                    reasoning_used = False
                    tool_uses = retry_tool_uses
                    has_tool_use = True
                    plan_negotiation = True  # 重试正文是缓冲的，需校验后一次性发送
                elif retry_text and not textbook_body_reply_blocked(retry_text, textbook_evidence.level):
                    logger.info("textbook_guard_retry_ok turn=%d 纠正重试产出诚实回答", _turn)
                    assistant_text = retry_text
                    reasoning_text = retry_reasoning
                    reasoning_used = True  # 缓冲轮未流式 emit，下面一次性发送
                else:
                    logger.info("textbook_guard_hard_failure turn=%d 固定诚实回复", _turn)
                    lesson_no = extract_lesson_no(_latest_user_content(messages))
                    assistant_text = textbook_honesty_fixed_reply(lesson_no)
                    reasoning_text = ""
                    reasoning_used = False
                    messages.append({"role": "assistant", "content": assistant_text})
                    await _emit("text", {"content": assistant_text})
                    break

        # ===== 结构化终态协议（AI 回复格式根治）=====
        # present_response 与业务工具混用时：拒绝终态工具，只执行业务工具，
        # 下一轮再要求终态响应（不重复执行业务工具）。
        present_tool_uses = [tu for tu in tool_uses if _is_present_response_tool(tu)]
        business_tool_uses = [tu for tu in tool_uses if not _is_present_response_tool(tu)]
        if present_tool_uses and business_tool_uses:
            logger.info(
                "agent_run present_response 与业务工具混用 turn=%d，仅执行业务工具", _turn
            )
            tool_uses = business_tool_uses
            has_tool_use = True
            present_tool_uses = []

        if present_tool_uses:
            # 终态工具轮：解析 → 校验 → 确定性渲染 → emit text → append assistant
            # （只落渲染后 content，不落 tool_calls，防刷新历史出现工具卡）→ 结束本轮。
            raw_arguments = present_tool_uses[0].get("arguments") or ""
            rendered = _render_present_response(raw_arguments)
            if rendered is None:
                # MiMo 偶发把 blocks 序列化成坏格式/截断（如 arguments 被截断的 JSON），
                # 先强制补调一次（模型已热，成功率更高）；补调也失败才 fail-closed。
                logger.info(
                    "agent_run_present_response_invalid turn=%d，强制补调一次", _turn
                )
                retry_text, retry_tool_uses, retry_reasoning = await _present_response_force_retry(
                    messages, tools, system, _emit
                )
                valid_present = [tu for tu in retry_tool_uses if _is_present_response_tool(tu)]
                if valid_present:
                    retry_rendered = _render_present_response(valid_present[0].get("arguments") or "")
                    if retry_rendered is not None:
                        rendered = retry_rendered
                if rendered is None:
                    # fail-closed：原始正文作安全段落（转义块级标记），坏 markdown 不出现。
                    # 模型在 arguments 里给了完整内容（即使格式不规范），优先转义使用，
                    # 而不是丢成固定失败文案/空回复。
                    fallback_source = (
                        _extract_present_arguments_text(raw_arguments)
                        or _extract_present_arguments_text(
                            valid_present[0].get("arguments") if valid_present else ""
                        )
                        or assistant_text
                        or retry_text
                        or ""
                    )
                    fallback_text = safe_paragraph_text(fallback_source) or PRESENT_RESPONSE_FAILURE_TEXT
                    rendered = _render_fail_closed_paragraph(fallback_text)
                    logger.warning(
                        "agent_run_present_response_fail_closed turn=%d，降级安全段落 len=%d",
                        _turn,
                        len(rendered),
                    )
            await _emit("text", {"content": rendered})
            messages.append({"role": "assistant", "content": rendered})
            logger.info(
                "agent_run_present_response_ok turn=%d len=%d （终态协议成功）", _turn, len(rendered)
            )
            break

        if not has_tool_use:
            # 纯文本回复：结构化终态协议下，模型直接输出的自由正文一律视为违规
            # （无法保证换行/结构一致性）→ 不 emit、不落库，强制补调 present_response。
            if is_free_text_violation(assistant_text):
                logger.info(
                    "agent_run_present_response_free_text_violation turn=%d，强制补调 present_response", _turn
                )
                retry_text, retry_tool_uses, retry_reasoning = await _present_response_force_retry(
                    messages, tools, system, _emit
                )
                valid_present = [tu for tu in retry_tool_uses if _is_present_response_tool(tu)]
                if valid_present:
                    rendered = _render_present_response(valid_present[0].get("arguments") or "")
                    if rendered is None:
                        fallback_text = safe_paragraph_text(
                            _extract_present_arguments_text(valid_present[0].get("arguments") or "")
                            or retry_text
                            or assistant_text
                            or ""
                        ) or PRESENT_RESPONSE_FAILURE_TEXT
                        rendered = _render_fail_closed_paragraph(fallback_text)
                    await _emit("text", {"content": rendered})
                    messages.append({"role": "assistant", "content": rendered})
                    logger.info(
                        "agent_run_present_response_forced_ok turn=%d len=%d （强制补调成功）", _turn, len(rendered)
                    )
                    break
                # 强制补调仍失败：fail-closed，只落安全 paragraph，坏 markdown 不出现。
                # 模型可能把 blocks JSON 当正文输出（content 是 {"blocks": ...}），
                # 先尝试从 JSON 提取可读文本，提取不到才用原文。
                fallback_source = (
                    _extract_present_arguments_text(assistant_text)
                    or _extract_present_arguments_text(retry_text)
                    or assistant_text
                    or retry_text
                    or ""
                )
                fallback_text = safe_paragraph_text(
                    fallback_source
                ) or PRESENT_RESPONSE_FAILURE_TEXT
                rendered = _render_fail_closed_paragraph(fallback_text)
                logger.warning(
                    "agent_run_present_response_forced_fail turn=%d，降级安全段落 len=%d", _turn, len(rendered)
                )
                await _emit("text", {"content": rendered})
                messages.append({"role": "assistant", "content": rendered})
                break

            # 空正文（reasoning 兜底后仍为空）：保持原行为 append 空消息
            if assistant_text or reasoning_used:
                if (plan_negotiation or reasoning_used) and assistant_text:
                    await _emit("text", {"content": assistant_text})
            messages.append({"role": "assistant", "content": assistant_text})
            break

        # 工具调用路径：缓冲轮的中间说明在工具执行前一次性发送。
        # 协议兜底（审查 P1-1）：这是模型自由正文，丢换行时坏格式可直接展示，
        # emit 前过 safe_paragraph_text 转义块级标记，坏 markdown 不出现。
        if plan_negotiation and assistant_text:
            safe_narrative = safe_paragraph_text(assistant_text) or PRESENT_RESPONSE_FAILURE_TEXT
            await _emit("text", {"content": safe_narrative})
            assistant_text = safe_narrative
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_text or None,
            "tool_calls": [{"id": tu["id"], "type": "function", "function": {"name": tu["name"], "arguments": tu["arguments"]}} for tu in tool_uses],
        }
        messages.append(assistant_msg)

        # 逐个执行工具。计划创建校验失败属于流程边界，必须立即结束本轮，
        # 不能把失败结果交回模型后继续出题或开始学习。
        blocked_flow_message: str | None = None
        for tu in tool_uses:
            name = tu["name"]
            # Tool Gateway 前置：白名单 + 严格 JSON + schema 校验 + 熔断（防 AI 幻觉硬机制）
            gate = parse_arguments(name, tu["arguments"], allowed_tool_names)
            args: dict[str, Any] = {}
            gateway_blocked: str | None = None
            gateway_retryable = False
            if not gate.ok:
                gateway_blocked = gate.error
                gateway_retryable = gate.retryable
            else:
                args = gate.data
                gate2 = validate_args(name, args)
                if not gate2.ok:
                    gateway_blocked = gate2.error
                    gateway_retryable = True
                elif _breaker.is_open(name):
                    gateway_blocked = f"「{name}」连续失败已暂停，请先做别的，不要再调用它"
                else:
                    # 循环检测增强：同工具+同参数重复调用 >=3 次 -> 熔断（防 AI 死循环无进展）
                    args_digest = json.dumps(args, sort_keys=True, ensure_ascii=False)
                    _tool_history.append({"name": name, "digest": args_digest})
                    repeat_count = sum(
                        1 for h in _tool_history if h["name"] == name and h["digest"] == args_digest
                    )
                    if repeat_count >= 3:
                        gateway_blocked = f"你已重复调用「{name}」{repeat_count} 次且无进展，请换一种方式或停止，不要重复执行"
                        gateway_retryable = False

            # 空消息轮（新会话首轮/注册后自动触发）：用户还没说过话，拦掉会创建或
            # 推进学习数据的工具，避免 LLM 编造学习事实落库（复现：841 首轮假报背单词）
            if not (_user_msg or "").strip() and name in EMPTY_MESSAGE_BLOCKED_TOOLS:
                gateway_blocked = (
                    f"用户尚未发言（新会话首轮），不能调用「{name}」。"
                    "请先按冷启动流程用 1.2.3. 编号向用户提问年级/想提升的科目，不要编造学习事实。"
                )
                gateway_retryable = False

            # P2 修复：轻练轮禁止 record_feedback 落库（轻练不沉淀，AI 不得把推断当事实写入正式反馈表）
            if name == "record_feedback" and in_light_practice_round(messages):
                gateway_blocked = (
                    "轻练轮不能调用 record_feedback：轻练是随手练习，不沉淀任何正式反馈/统计。"
                    "把当前对话的判分和讲解用正文说清楚即可，不要写学习反馈。"
                )
                gateway_retryable = False

            tool_started_at = time.time()
            tool_status = "succeeded"  # RunOutcome：结构化终态，前端消费不靠 output 猜
            await _emit("tool_call", {"name": name, "input": args, "id": tu["id"], "started_at": int(tool_started_at * 1000)})

            try:
                if gateway_blocked:
                    raise ToolCallError(gateway_blocked, retryable=gateway_retryable)
                if business_actor == "channel_guardian" and name not in {
                    tool["name"] for tool in CHANNEL_GUARDIAN_TOOLS
                }:
                    raise PermissionError("渠道家长只能查询学习情况")
                if business_actor == "channel_guardian" and int(
                    args.get("student_id") or 0
                ) != student_id:
                    raise PermissionError("只能查询当前选择的孩子")
                confirmation = validate_study_plan_confirmation(messages) if name == "create_study_plan" else None
                if name == "create_study_plan" and (not args.get("confirmed") or not confirmation or not confirmation.allowed):
                    reason = (
                        confirmation.reason
                        if confirmation
                        else "学习计划需要先给学生确认草案，用户明确确认后才能创建。"
                    )
                    next_step = (
                        confirmation.next_step
                        if confirmation
                        else "请先询问学习目标、可用时长、内容偏好，给出计划草案并等待用户确认。"
                    )
                    output = {"error": reason, "saved": False, "next_step": next_step}
                    blocked_flow_message = (
                        f"还没有创建计划：{reason}{next_step}"
                        "计划创建成功后，再进入具体计划开始学习。"
                    )
                elif name == "create_practice_exam" and not is_task and args.get("plan_item_id"):
                    output = {
                        "error": "关联计划项的练习不能在主会话生成。",
                        "saved": False,
                        "next_step": "请先点击顶部的继续学习，进入具体计划任务后再生成练习。",
                    }
                    blocked_flow_message = (
                        "这项练习属于已创建的具体计划，不能在主规划会话直接开始。"
                        "请点击顶部的继续学习，进入具体计划任务后再生成练习。"
                    )
                else:
                    # M1：draft_study_plan 的会话归属由服务端注入，模型参数不可信
                    # （tool schema 不暴露该字段，模型即使伪造也会被覆盖）。
                    # M2 C：draft 执行前校验教材来源，服务端覆盖 context_refs.textbook_source
                    # （方案 2.4.5.5/2.4.5.6）：无来源具体课名/作者断言以 retryable error 拦截，
                    # 不写 StudyPlanDraft；中性「课本第 X 课」放行并追加「尚未核验」说明。
                    if name == "draft_study_plan":
                        args["chat_session_id"] = chat_session_id
                        draft_evidence = build_textbook_evidence(messages, textbook_profile_versions)
                        source_block = check_draft_plan_textbook_source(args, draft_evidence)
                        if source_block:
                            raise ToolCallError(source_block, retryable=True)
                        annotate_draft_textbook_source(args, draft_evidence)
                    tool_task = asyncio.create_task(run_tool(name, args, role, db, teacher_id, _dispatch, _breaker))
                    while not tool_task.done():
                        try:
                            gresult = await asyncio.wait_for(asyncio.shield(tool_task), timeout=settings.config.agent.tool_timeout_seconds)
                            break
                        except TimeoutError:
                            elapsed_ms = int((time.time() - tool_started_at) * 1000)
                            await _emit(
                                "tool_progress",
                                {
                                    "name": name,
                                    "id": tu["id"],
                                    "elapsed_ms": elapsed_ms,
                                    "message": _tool_progress_message(name, elapsed_ms),
                                },
                            )
                    else:
                        gresult = tool_task.result()
                    if not gresult.ok:
                        raise ToolCallError(gresult.error, retryable=gresult.retryable)
                    output = gresult.data
                output_str = json.dumps(output, ensure_ascii=False) if not isinstance(output, str) else output
                _breaker.record_success(name)
            except ToolCallError as e:
                # 网关失败（白名单/JSON/schema/熔断）：blocked，交 AI 修正
                output_str = str(e)
                tool_status = "blocked"
                if e.retryable:
                    output_str += "（结果未生效，修正后可重试，不要重复执行未生效的操作）"
                _breaker.record_failure(name)
            except PermissionError as e:
                output_str = f"权限不足：{e}"
                tool_status = "failed"
                _breaker.record_failure(name)
            except Exception as e:  # noqa: BLE001
                logger.warning("agent 工具执行失败：tool=%s", name, exc_info=True)
                output_str = f"工具执行失败：{e}"
                tool_status = "failed"
                _breaker.record_failure(name)

            elapsed_ms = int((time.time() - tool_started_at) * 1000)
            # RunOutcome：业务失败（error/saved:false）统一标 failed，前端消费 status 不猜
            _failed = ('"error"' in output_str or '"saved": false' in output_str
                       or '未生效' in output_str
                       or output_str.startswith('工具执行失败') or output_str.startswith('权限不足'))
            if tool_status == "succeeded" and _failed:
                tool_status = "failed"
            logger.info(
                "agent_run tool=%s elapsed_ms=%d status=%s result=%s",
                name, elapsed_ms, tool_status, output_str[:300],
            )
            await _emit("tool_result", {"name": name, "output": output_str, "status": tool_status, "id": tu["id"], "elapsed_ms": elapsed_ms})

            # 回灌给 LLM 前截断（防爆参数 400）
            llm_content = _truncate_for_llm(name, output_str)
            if _failed:
                llm_content = (llm_content + "\n\n【系统纠正】本次工具调用失败，结果未生效。"
                               "你必须如实告诉用户失败了，绝对不能声称已成功/已建好/已保存/在跑。"
                               "以本工具结果为准；如果之前说过'已成功'，那是错的，要纠正过来。")
            messages.append({"role": "tool", "tool_call_id": tu["id"], "content": llm_content})

            if blocked_flow_message:
                break

        if blocked_flow_message:
            messages.append({"role": "assistant", "content": blocked_flow_message})
            await _emit("text", {"content": blocked_flow_message})
            break

    _total_ms = int((time.time() - _run_started_at) * 1000)
    logger.info("agent_run 结束 turns=%d total_ms=%d", _turn + 1, _total_ms)
    # 协议兜底（审查 P2-4）：15 轮工具循环耗尽自然结束时，最后一条可能仍是工具轮
    # （无终态正文）。补一个安全段落，保证本轮总有合规的最终 assistant 正文。
    last_message = messages[-1] if messages else None
    last_is_terminal = bool(
        last_message
        and last_message.get("role") == "assistant"
        and isinstance(last_message.get("content"), str)
        and last_message.get("content")
        and not last_message.get("tool_calls")
    )
    if not last_is_terminal:
        fallback = _render_fail_closed_paragraph(PRESENT_RESPONSE_FAILURE_TEXT)
        messages.append({"role": "assistant", "content": fallback})
        await _emit("text", {"content": fallback})
        logger.warning("agent_run 循环耗尽无终态回复，降级安全段落")
    return messages


def _tool_progress_message(tool_name: str, elapsed_ms: int) -> str:
    seconds = max(1, round(elapsed_ms / 1000))
    if tool_name == "recognize_homework_photo_markdown":
        return f"正在把图片识别成 Markdown，已等待 {seconds} 秒"
    if tool_name == "grade_homework_photo":
        return f"正在识别图片并逐题批改，已等待 {seconds} 秒"
    return f"工具还在执行，已等待 {seconds} 秒"


def _truncate_for_llm(tool_name: str, output: str) -> str:
    """工具结果超长时截断，只回灌预览给 LLM（防爆参数 400）。

    移植 learn-claude-code s08:332 persist_large_output。
    前端拿到的是完整 output_str（SSE 推送），只有回灌给 LLM 的截断。
    """
    if len(output) <= TOOL_RESULT_PERSIST_THRESHOLD:
        return output
    preview = output[:TOOL_RESULT_PREVIEW_LEN]
    logger.info("工具 %s 结果截断: %d→%d 字符", tool_name, len(output), len(preview))
    return f"<truncated-output>\nPreview:\n{preview}\n...\n(完整结果已截断，共 {len(output)} 字符)\n</truncated-output>"


async def _dispatch(name: str, args: dict[str, Any], role: str, db: Session, teacher_id: int) -> Any:
    handler = _HANDLERS.get(name)
    if not handler:
        return f"未知工具：{name}"
    return await handler(args, role, db, teacher_id)
