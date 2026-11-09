from typing import Literal

from pydantic import BaseModel, Field


class LearningFlowEntry(BaseModel):
    kind: Literal["continue_plan", "review_error", "review_knowledge", "empty"]
    title: str
    description: str
    primary_label: str
    prompt: str
    source_type: Literal["study_plan", "error_book", "learning_map"] | None = None
    source_id: int | None = None
    item_id: int | None = None
    evidence: list[str] = Field(default_factory=list)
