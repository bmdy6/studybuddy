from typing import Literal

from pydantic import BaseModel, Field


LearningMapStatus = Literal["weak", "reviewing", "stable", "unknown"]
LearningMapResourceType = Literal["error", "note", "material", "plan_item"]


class LearningMapResource(BaseModel):
    id: int
    title: str
    type: LearningMapResourceType
    status: str | None = None
    summary: str = ""
    url: str | None = None


class LearningMapNode(BaseModel):
    tag: str
    status: LearningMapStatus
    error_count: int = 0
    note_count: int = 0
    material_count: int = 0
    plan_item_count: int = 0
    last_wrong_at: str | None = None
    next_actions: list[str] = Field(default_factory=list)
    resources: list[LearningMapResource] = Field(default_factory=list)


class LearningMapResponse(BaseModel):
    student_id: int
    generated_at: str
    nodes: list[LearningMapNode] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    total_count: int = 0
    has_more: bool = False
