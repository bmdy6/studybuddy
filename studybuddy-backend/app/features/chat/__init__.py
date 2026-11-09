"""对话域 (chat)。

按 21 约束 §7 拆自 app/services/chat_service.py (626L 上帝模块, 超 #13 门槛)。
no-facade (#11): 调用方直接 from app.features.chat.<sub> import fn, 不经本 __init__ 再导出。

DAG 单向无环:
    sessions    context
        \\       /
         agent
- agent -> context (load_history_as_llm_messages)
- agent -> sessions (maybe_auto_title)
- agent -> app.features.agent.agent_loop (单向, chat 依赖 agent 域主循环)
- context / sessions 互不依赖
"""
