"""笔记 schemas：学习记录 + 盲区（concept 概念卡已废弃）。"""

from pydantic import BaseModel, Field


class NoteItem(BaseModel):
    """笔记列表/详情项。"""

    id: int
    student_id: int
    type: str  # study_record（concept 已废弃）
    title: str
    subject: str
    category: str | None = None  # 学科下细分分类，agent 判断
    content: str
    knowledge_tags: list[str] = []
    source: str
    source_ref: list = []
    status: str
    created_at: str
    updated_at: str


class CreateNoteRequest(BaseModel):
    """创建笔记（agent save_note 工具用）。"""

    student_id: int
    title: str = Field(max_length=200)
    subject: str = Field(default="其他", max_length=20)
    category: str | None = Field(default=None, max_length=50, description="学科下细分分类，agent判断")
    content: str = ""
    knowledge_tags: list[str] = []
    source: str = Field(default="其他", max_length=20)
    source_ref: list = []
    status: str = Field(default="draft", pattern="^(draft|confirmed)$")


class UpdateNoteRequest(BaseModel):
    """更新笔记（弟弟编辑/确认）。"""

    title: str | None = Field(default=None, max_length=200)
    content: str | None = None
    knowledge_tags: list[str] | None = None
    category: str | None = None
    status: str | None = Field(default=None, pattern="^(draft|confirmed)$")


class BlindSpotItem(BaseModel):
    """盲区项：高频错题知识点 + 关联笔记数 + 错题数。"""

    tag: str
    error_count: int
    last_wrong_at: str
    note_count: int  # 该知识点有多少篇笔记
