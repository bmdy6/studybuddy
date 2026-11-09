"""Agent 域：主循环、工具定义、上下文拼装、按域拆分的工具处理器。

主循环留在 agent_loop.py 子模块（而非本 __init__），故 `from app.features.agent import agent_loop`
返回模块对象，保留 `agent_loop.X` 属性访问与 `patch.object(agent_loop, X)` 语义。

依赖方向（DAG 单向无环）：handlers -> context（context 不反向依赖 handlers）；
agent_loop 门面依赖全部子模块。agent 域历史上位于 app/core，因 core 反向依赖 features
（违反单向依赖 #1、稳定依赖 #2）迁移至此。
"""
