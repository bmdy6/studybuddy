-- 018: 每日学习记录（每日教练与自动学习记忆 spec 3.1）
-- 一名学生一天一条的事实容器；本 PR 只建表 + 只读 API，证据聚合/摘要生成见 PR-03/04。

CREATE TABLE IF NOT EXISTS daily_learning_records (
  id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
  student_id          BIGINT NOT NULL,
  record_date         DATE NOT NULL,
  facts_snapshot      JSON NOT NULL,
  summary_text        TEXT NULL,
  evidence_hash       VARCHAR(64) NULL,
  generation_status   ENUM('pending','generating','ready','failed') NOT NULL DEFAULT 'pending',
  summary_source      ENUM('ai','deterministic') NULL,
  checkin_status      ENUM('pending','done') NULL,
  checkin_response    VARCHAR(50) NULL,
  checked_in_at       DATETIME NULL,
  generated_at        DATETIME NULL,
  finalized_at        DATETIME NULL,
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uk_daily_learning_records_student_date (student_id, record_date),
  KEY idx_daily_learning_records_student_date (student_id, record_date),
  CONSTRAINT fk_daily_learning_records_student
    FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='每日学习记录：学生+本地日期唯一的事实与摘要容器';
