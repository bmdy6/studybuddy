from pydantic import BaseModel


class WeakPoint(BaseModel):
    tag: str
    wrong_count: int
    error_rate: float
    total_attempts: int
    mastered: bool


class DiagnosisResponse(BaseModel):
    student_id: int
    student_name: str
    weak_points: list[WeakPoint]
    mastered_tags: list[str]
    generated_at: str
