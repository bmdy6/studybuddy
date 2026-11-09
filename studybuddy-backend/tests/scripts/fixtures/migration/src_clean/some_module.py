"""迁移后已切换到新模块路径的样例（无旧 import 残留）。"""

from app.modules.question_bank import search_public_paper_candidates


def use_new():
    return search_public_paper_candidates()
