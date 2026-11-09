-- 013 项目级题库题目表：候选来源解析后进入待确认题库

USE studybuddy;

CREATE TABLE IF NOT EXISTS question_bank_items (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  subject         VARCHAR(50) NULL,
  grade           VARCHAR(50) NULL,
  semester        VARCHAR(50) NULL,
  question_type   VARCHAR(50) NOT NULL DEFAULT 'unknown',
  stem            TEXT NOT NULL,
  options         JSON NULL,
  answer          TEXT NULL,
  explanation     TEXT NULL,
  knowledge_tags  JSON NULL,
  difficulty      VARCHAR(20) NULL,
  status          ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  duplicate_key   VARCHAR(64) NOT NULL,
  raw_meta        JSON NULL,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uk_qb_item_duplicate_key (duplicate_key),
  KEY idx_qb_item_scope (grade, semester, subject, status),
  KEY idx_qb_item_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='项目级题库题目';

CREATE TABLE IF NOT EXISTS question_bank_sources (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  item_id       BIGINT NOT NULL,
  paper_id      BIGINT NOT NULL,
  question_no   VARCHAR(40) NULL,
  source_url    TEXT NOT NULL,
  source_title  VARCHAR(300) NULL,
  raw_text      TEXT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE KEY uk_qb_source_item_paper_no (item_id, paper_id, question_no),
  KEY idx_qb_source_paper (paper_id),
  CONSTRAINT fk_qb_source_item FOREIGN KEY (item_id) REFERENCES question_bank_items(id) ON DELETE CASCADE,
  CONSTRAINT fk_qb_source_paper FOREIGN KEY (paper_id) REFERENCES question_bank_papers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='项目级题库题目来源';
