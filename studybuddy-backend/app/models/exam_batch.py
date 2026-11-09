"""考试批次模型：一次考试一个批次，关联多张照片素材。

错题导入流程：弟弟拍照上传答题卡+试卷 → 存到批次子文件夹 → 视觉解析 → 判分 → 入错题本。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExamBatch(Base):
    __tablename__ = "exam_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject: Mapped[str] = mapped_column(String(20), nullable=False)  # 学科
    exam_name: Mapped[str] = mapped_column(String(100), nullable=False)  # 考试名（期中考试）
    exam_date: Mapped[str] = mapped_column(String(20), nullable=False)  # 考试日期 YYYY-MM-DD
    # 关联的素材 id 列表（照片）
    photo_material_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    # img2pdf 合成的 PDF 的 content_ref（留档预览用）
    parsed_pdf_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 视觉识别后的 Markdown 原文，用于学生逐题核对答案
    recognized_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 拍题逐题核对状态，保留识别答案和学生确认后的答案
    answer_review_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    answer_review_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 子文件夹名（{id}_{学科}_{考试名}_{日期}）
    folder_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 状态：uploaded(照片已存) / parsed(已解析) / graded(已判分)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
