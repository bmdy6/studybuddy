"""微信渠道特性包。

依赖方向（单向无环，遵循架构约束 #1）::

    messaging  <-  guardian  <-  accounts
    messaging  <-  guardian  <-  inbound
    messaging  <-  guardian  <-  dispatch

messaging 为最底层（仅依赖 httpx/settings 等外部库）；
guardian 依赖 messaging 与 features.chat(sessions)/access_service/supervision_service；
inbound 依赖 guardian/messaging 与 features.chat(agent/sessions)；
accounts/dispatch 单向依赖 guardian + messaging。
各子模块直接引用目标文件，不做 facade 转发（约束 #11）。
"""
