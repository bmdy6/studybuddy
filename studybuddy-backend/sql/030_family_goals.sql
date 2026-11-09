-- 030 家庭目标与任务激励（目标 -> 任务 -> 实例 -> 图片证据 -> 奖励记录）
-- 说明：金额只记在目标/任务/奖励记录上，不建钱包与余额字段；累计奖励由 SUM(amount) 得出。
CREATE TABLE IF NOT EXISTS family_goals (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  mode VARCHAR(16) NOT NULL DEFAULT 'study',
  title VARCHAR(128) NOT NULL,
  description TEXT NULL,
  reward_amount DECIMAL(10,2) NULL COMMENT '目标级默认奖励，任务级为空时继承',
  created_by BIGINT NULL,
  creator_role ENUM('student','parent') NOT NULL,
  status ENUM('active','completed','archived') NOT NULL DEFAULT 'active',
  start_date DATE NULL,
  end_date DATE NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_family_goals_student (student_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS family_goal_tasks (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  goal_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  mode VARCHAR(16) NOT NULL DEFAULT 'study',
  title VARCHAR(160) NOT NULL,
  description TEXT NULL,
  repeat_type ENUM('once','daily') NOT NULL DEFAULT 'once',
  reward_amount DECIMAL(10,2) NULL COMMENT '为空则继承目标级',
  status ENUM('active','archived') NOT NULL DEFAULT 'active',
  sort_order INT NOT NULL DEFAULT 0,
  created_by BIGINT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_family_goal_tasks_goal (goal_id, status),
  INDEX idx_family_goal_tasks_student (student_id, repeat_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS family_task_occurrences (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  task_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  occurrence_date DATE NOT NULL,
  status ENUM('pending','submitted','approved','rejected') NOT NULL DEFAULT 'pending',
  submit_note TEXT NULL,
  submitted_at DATETIME NULL,
  reviewed_by BIGINT NULL,
  reviewed_at DATETIME NULL,
  reject_reason VARCHAR(500) NULL,
  reward_amount_snapshot DECIMAL(10,2) NULL COMMENT '审核确认时的金额快照',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_family_task_occurrences_task_date (task_id, occurrence_date),
  INDEX idx_family_task_occurrences_student_status (student_id, status, submitted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS family_task_evidence (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  occurrence_id BIGINT NOT NULL,
  content_ref VARCHAR(512) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  uploaded_by BIGINT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_family_task_evidence_occurrence (occurrence_id, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS family_reward_records (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  occurrence_id BIGINT NOT NULL,
  task_title VARCHAR(160) NOT NULL,
  goal_title VARCHAR(128) NULL,
  amount DECIMAL(10,2) NOT NULL,
  confirmed_by BIGINT NULL,
  confirmed_at DATETIME NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_family_reward_records_occurrence (occurrence_id),
  INDEX idx_family_reward_records_student (student_id, confirmed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
