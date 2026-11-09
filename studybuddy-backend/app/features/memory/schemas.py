from pydantic import BaseModel

class RelationIn(BaseModel):
    source_type: str
    source_id: int
    target_type: str
    target_id: int
    relation: str = "related_to"

class RelationOut(RelationIn):
    id: int
    student_id: int

class SearchHit(BaseModel):
    type: str
    id: int
    title: str
    snippet: str
    score: float
    source: str
