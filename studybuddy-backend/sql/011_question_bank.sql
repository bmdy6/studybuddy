-- 011 项目级题库：候选试卷来源表

USE studybuddy;

CREATE TABLE IF NOT EXISTS question_bank_papers (
  id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
  title               VARCHAR(300) NOT NULL,
  source_url          TEXT NOT NULL,
  source_url_hash     VARCHAR(64) NOT NULL,
  snippet             TEXT NULL,

  province            VARCHAR(50) NULL,
  city                VARCHAR(50) NULL,
  district            VARCHAR(80) NULL,
  school              VARCHAR(120) NULL,
  grade               VARCHAR(50) NULL,
  semester            VARCHAR(50) NULL,
  subject             VARCHAR(50) NULL,
  textbook_version    VARCHAR(80) NULL,
  year                INT NULL,
  exam_type           VARCHAR(50) NULL,

  source_type         ENUM('school_paper','district_paper','web_paper','paid_or_unclear','ai_generated','search_result') NOT NULL DEFAULT 'search_result',
  availability_level  ENUM('A','B','C','D') NOT NULL DEFAULT 'B',
  risk_level          ENUM('low','medium','high') NOT NULL DEFAULT 'medium',
  status              ENUM('candidate','confirmed','rejected','internal_style') NOT NULL DEFAULT 'candidate',
  confidence          INT NOT NULL DEFAULT 50,

  created_by          BIGINT NULL,
  raw_meta            JSON NULL,
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uk_qb_paper_source_hash (source_url_hash),
  KEY idx_qb_paper_scope (city, district, school, grade, subject),
  KEY idx_qb_paper_status (status, availability_level, risk_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='项目级题库候选试卷来源';
