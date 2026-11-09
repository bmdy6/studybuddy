-- 015 站内通知：学习计划提醒、后续批改/题库事件可复用

USE studybuddy;

CREATE TABLE IF NOT EXISTS notifications (
  id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
  recipient_id       BIGINT NOT NULL,
  student_id         BIGINT NULL,
  title              VARCHAR(160) NOT NULL,
  content            TEXT NOT NULL,
  notification_type  VARCHAR(50) NOT NULL DEFAULT 'study_plan_reminder',
  source_type        VARCHAR(50) NOT NULL,
  source_id          BIGINT NULL,
  dedupe_key         VARCHAR(120) NOT NULL,
  read_at            DATETIME NULL,
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uk_notification_dedupe (recipient_id, source_type, source_id, dedupe_key),
  KEY idx_notifications_recipient_created (recipient_id, created_at),
  KEY idx_notifications_recipient_read (recipient_id, read_at, created_at),
  KEY idx_notifications_student (student_id),
  CONSTRAINT fk_notifications_recipient FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_notifications_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='站内通知';
