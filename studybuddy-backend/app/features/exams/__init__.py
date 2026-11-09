"""试卷与考试 feature：试卷 CRUD / 批次（含拍题批改）/ 答题批改 / 错题回写。

依赖方向：exams -> error_book（批改落错题）、exams -> materials（markdown_extraction 视觉）。
"""
