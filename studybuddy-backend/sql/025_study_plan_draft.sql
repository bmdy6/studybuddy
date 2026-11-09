-- 025_study_plan_draft.sql
-- 计划草案表：AI 生成、学生点卡片确认后原子创建正式计划
-- 靠 draft_id/revision/expires_at/created_plan_id 做硬状态，替代聊天关键词猜确认
CREATE TABLE IF NOT EXISTS study_plan_draft (
  id BIGINT NOT NULL AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  created_by BIGINT NULL,
  chat_session_id BIGINT NULL,
  draft_data JSON NOT NULL,
  revision INT NOT NULL DEFAULT 1,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  expires_at DATETIME NULL,
  created_plan_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_draft_student (student_id),
  KEY idx_draft_session (chat_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
