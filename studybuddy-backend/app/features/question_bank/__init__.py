"""题库 feature：试卷搜索 / 来源审核 / 上传校验 / 题目 CRUD / B 站搜索。

对外门面是 ``service`` 子模块（re-export 各子模块公开函数），调用方写
``from app.features.question_bank import service as question_bank_service``
保持 ``question_bank_service.xxx`` 调用面不变（架构文档 §6）。
"""
