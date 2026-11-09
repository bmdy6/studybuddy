-- U-044 任务完成判定：study_plan_items.status 加 in_progress + study_plan_item_attempts 表
ALTER TABLE study_plan_items MODIFY COLUMN status ENUM('todo','in_progress','done','skipped') NOT NULL DEFAULT 'todo';
CREATE TABLE study_plan_item_attempts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  plan_item_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  assessment ENUM('passed','needs_retry','blocked') NOT NULL COMMENT 'AI 评估结果',
  evidence_summary TEXT NULL COMMENT '证据摘录（对话中学生作答内容或提交答案）',
  reason TEXT NULL COMMENT 'AI 判定理由',
  confidence DECIMAL(3,2) NULL COMMENT '置信度 0-1',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (plan_item_id) REFERENCES study_plan_items(id) ON DELETE CASCADE,
  INDEX idx_attempts_plan_item (plan_item_id),
  INDEX idx_attempts_student (student_id)
);
