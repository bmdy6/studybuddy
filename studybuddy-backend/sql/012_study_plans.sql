-- 012 学习计划与督促闭环：计划表 + 计划项表

USE studybuddy;

CREATE TABLE IF NOT EXISTS study_plans (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  student_id    BIGINT NOT NULL,
  title         VARCHAR(128) NOT NULL,
  focus         VARCHAR(256) NULL COMMENT '计划目标/关注点',
  status        ENUM('active','completed','archived') NOT NULL DEFAULT 'active',
  planned_date  DATE NULL,
  created_by    BIGINT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  KEY idx_study_plans_student_status (student_id, status, planned_date),
  KEY idx_study_plans_created_by (created_by),
  CONSTRAINT fk_study_plans_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_study_plans_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学习计划';

CREATE TABLE IF NOT EXISTS study_plan_items (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  plan_id       BIGINT NOT NULL,
  title         VARCHAR(160) NOT NULL,
  target        TEXT NULL,
  minutes       INT NOT NULL DEFAULT 20,
  status        ENUM('todo','done','skipped') NOT NULL DEFAULT 'todo',
  related_tags  JSON NULL,
  sort_order    INT NOT NULL DEFAULT 0,
  completed_at  DATETIME NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  KEY idx_study_plan_items_plan_status (plan_id, status, sort_order),
  CONSTRAINT fk_study_plan_items_plan FOREIGN KEY (plan_id) REFERENCES study_plans(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学习计划项';
