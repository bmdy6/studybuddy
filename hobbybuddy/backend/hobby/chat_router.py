"""兴趣空间对话路由（第一版：非流式 POST，返回完整回复）。

用极简 agent 骨架：兴趣提示词 + HOBBY_TOOLS + 工具 handlers。
消息暂不落库（第一版最小跑通），后续接入底座 ChatSession/ChatMessage 复用。
"""

import asyncio
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.features.agent.agent_core import run_agent
from hobby.database import get_db
from hobby.deps import get_current_user
from hobby.hobby_tools import HOBBY_TOOLS, TOOL_HANDLERS
from hobby.models import User
from hobby.prompts_loader import render

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


@router.post("/", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    message = (req.message or "").strip()
    if not message:
        return ChatResponse(reply="说点什么吧，比如：我想学唱歌。")

    user_name = user.display_name or user.username
    system = render("agent/system_hobby", user_name=user_name)

    messages = [{"role": "user", "content": message}]
    try:
        updated = await run_agent(
            messages,
            system=system,
            tools=HOBBY_TOOLS,
            handlers=TOOL_HANDLERS,
            db=db,
            user_id=user.id,
        )
    except (RuntimeError, asyncio.TimeoutError) as exc:
        # LLM 重试耗尽/熔断/超时：降级提示，不让用户面对 500（外部调用失败必须能回人工流程）
        logger.warning("LLM 调用失败，降级提示：%s", exc)
        return ChatResponse(
            reply="AI 暂时不可用，请稍后再试，或直接描述你今天的练习内容。"
        )

    # 取最后一个 assistant 正文作为回复
    reply = ""
    for msg in reversed(updated):
        if msg.get("role") == "assistant" and msg.get("content"):
            reply = msg["content"]
            break
    return ChatResponse(reply=reply or "（没有收到回复，请再试一次）")
