from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        Index("idx_material_student", "student_id"),
        Index("idx_material_sha", "file_sha256"),
        Index("idx_material_fingerprint", "content_fingerprint"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="study", server_default="study")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(Enum("teacher", "student"), nullable=False)
    content_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    knowledge_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    recognized_markdown: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    confirmed_markdown: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recognition_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    recognition_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recognition_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    uncertain_points: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    recognized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    uploaded_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # 素材真实归属学生：学生上传=自己 id；家长上传=指定学生 id；旧数据=NULL（去重 fallback uploaded_by）。
    student_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # 上传时对原始文件字节算 SHA-256 hex，归属范围内文件层硬去重。
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 识别成功后对规范化 Markdown 算 SHA-256 hex，精确命中时归一。
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 高置信非空识别结果自动置 1，Agent 可直接读。
    auto_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # 内容指纹精确命中时指向同归属范围的规范素材；不删记录/文件，列表与读取归一。
    duplicate_of_material_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("materials.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
# agg-1
