"""p2 域：兴趣/学习计划/反馈/推荐/属性/画像的持久化与查询。

子模块依赖方向（单向 #1，无环）::

    interests      -> app.models.p2
    study_plan     -> app.models.p2
    feedback       -> app.models.p2
    recommendation -> app.models.p2
    attribute      -> app.constants, app.models.p2
    profile        -> interests, attribute

调用方按需直接 import 子模块（no-facade #11）。app.models.p2 保留原位
（多域共用 ORM 层，属稳定底层 #5）。
"""
