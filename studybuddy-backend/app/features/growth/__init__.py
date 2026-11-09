"""growth 域：家长成长摘要生成与定时推送编排。

子模块依赖方向（单向 #1，无环）::

    intent_service          独立，无内部依赖
    facts                   -> app.models
    evidence                -> facts
    summary                 -> evidence
    guardian_today          -> evidence
    dispatch                -> facts, summary

调用方按需直接 import 子模块（no-facade #11）。
"""
