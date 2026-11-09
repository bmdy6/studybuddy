"""每日学习记录 schemas：只读响应契约（spec 3.1）。

本 PR 不开放任何写入接口，因此只有响应 schema。证据聚合、摘要生成、对齐状态
更新等写入由 service 内部触发（PR-03/04/11），对应请求 schema 随那些 PR 一并补充。
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class DailyLearningRecordItem(BaseModel):
    """每日学习记录响应项，覆盖 spec 3.1 全部字段。"""

    id: int
    student_id: int
    record_date: date
    facts_snapshot: dict[str, Any]
    summary_text: str | None = None
    evidence_hash: str | None = None
    generation_status: str = Field(pattern="^(pending|generating|ready|failed)$")
    summary_source: str | None = Field(default=None, pattern="^(ai|deterministic)$")
    checkin_status: str | None = Field(default=None, pattern="^(pending|done)$")
    checkin_response: str | None = None
    checked_in_at: datetime | None = None
    generated_at: datetime | None = None
    finalized_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
