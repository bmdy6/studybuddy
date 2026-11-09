"""模块化迁移前的旧引用样例（故意保留旧 import 路径）。

迁移后下方这行 import 应改为新模块路径（如 app.modules.question_bank）。
本文件故意保留旧引用，用于验证 old-path 子命令能抓到残留。
"""

from app.services.question_bank import search_public_paper_candidates


def use_old():
    return search_public_paper_candidates()
