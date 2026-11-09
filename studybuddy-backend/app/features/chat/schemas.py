"""对话相关 Pydantic schemas（P2 agent 化）。"""

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    student_id: int  # 关联学生（teacher 发起时为当前孩子；student 发起时为自己）


class RenameSessionRequest(BaseModel):
    title: str


class SessionItem(BaseModel):
    id: int
    user_id: int
    student_id: int
    title: str
    created_at: str
    session_type: str = "main"
    mode: str = "study"
    plan_id: int | None = None
    plan_item_id: int | None = None
    status: str = "active"


class MessageItem(BaseModel):
    id: int
    role: str  # user/assistant/tool
    content: str | None = None
    tool_calls: list | None = None
    tool_result: dict | None = None
    created_at: str


class SendMessageRequest(BaseModel):
    """发消息请求体。

    前端使用 fetch + ReadableStream 读取 SSE，因此正文放 JSON body，避免 query 泄漏到日志/历史。
    """

    content: str
    display_content: str | None = None
