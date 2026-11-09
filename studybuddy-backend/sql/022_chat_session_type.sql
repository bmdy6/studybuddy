-- U-042 chat_sessions 加 session_type/plan_id/plan_item_id/status/context_version
-- task session：每个计划项最多一个（plan_item_id 唯一索引，MySQL 5.7 UNIQUE 允许多 NULL，main session 不冲突）
ALTER TABLE chat_sessions ADD COLUMN session_type VARCHAR(16) NOT NULL DEFAULT 'main' COMMENT 'main|task';
ALTER TABLE chat_sessions ADD COLUMN plan_id BIGINT NULL COMMENT 'task 关联的学习计划';
ALTER TABLE chat_sessions ADD COLUMN plan_item_id BIGINT NULL COMMENT 'task 关联的计划项';
ALTER TABLE chat_sessions ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'active|archived';
ALTER TABLE chat_sessions ADD COLUMN context_version INT NOT NULL DEFAULT 0 COMMENT 'task 上下文版本';
CREATE UNIQUE INDEX uq_chat_sessions_plan_item_id ON chat_sessions (plan_item_id);
