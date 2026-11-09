from pydantic import BaseModel, Field


class MaterialUploadResponse(BaseModel):
    material_id: int
    name: str
    type: str
    source: str
    cos_key: str
    uploaded_by: str
    created_at: str
    # 命中已有素材时为 True（同归属范围文件 SHA-256 命中），前端据此提示“素材已存在”。
    is_duplicate: bool = False
    # 命中重复时返回已有素材 id；未命中为 None。
    duplicate_of_material_id: int | None = None
    # 本次素材归属学生 id（家长上传=目标学生；学生上传=自己；未定=None）。
    student_id: int | None = None


class MaterialItem(BaseModel):
    id: int
    name: str
    type: str
    source: str
    knowledge_tags: list[str] = Field(default_factory=list)
    recognition_status: str = "pending"
    uploaded_by: str
    cos_url: str
    created_at: str
    # 素材归属学生 id（旧数据可能为 None）。
    student_id: int | None = None
    # 高置信非空识别结果自动可用。
    auto_ready: bool = False
    # 是否为内容指纹归一的重复素材（duplicate_of 非空）。
    is_duplicate: bool = False


class MaterialExtractionResponse(BaseModel):
    material_id: int
    name: str
    recognition_status: str
    raw_text: str | None = None
    recognized_markdown: str | None = None
    confirmed_markdown: str | None = None
    summary: str | None = None
    content_type: str | None = None
    recognition_provider: str | None = None
    recognition_confidence: str | None = None
    uncertain_points: list[str] = Field(default_factory=list)
    recognized_at: str | None = None
    confirmed_at: str | None = None
    # 是否自动可用（高置信非空）。
    auto_ready: bool = False
    # 内容指纹（识别成功后写入）。
    content_fingerprint: str | None = None
    # 内容指纹精确命中时指向规范素材。
    duplicate_of_material_id: int | None = None


class MaterialExtractionConfirmRequest(BaseModel):
    confirmed_markdown: str = Field(min_length=1)
# agg-1
