"""素材 feature：上传 / 归属 / 去重 / 访问边界 / 列表（service）+ 识别指纹归一（extraction_service）+ OCR/Markdown 提取。

依赖方向：materials -> app.core.auth.access_service（归属与访问边界，稳定底层）、
materials -> app.core.ai_service（视觉）、materials -> app.utils.cos（文件存储）。
materials 不反向依赖 exams：拍题作答核对解析（answer_review_parser）已迁 exams 域，
markdown_extraction_service 不再 import exams schema（§1 单向）。
exams 单向复用 materials 的 markdown_extraction 共享 helper（is_unclear_student_answer 等）。
"""
