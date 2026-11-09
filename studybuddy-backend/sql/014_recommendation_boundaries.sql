-- 014 家长推荐边界配置

USE studybuddy;

CREATE TABLE IF NOT EXISTS recommendation_boundaries (
  id                             BIGINT AUTO_INCREMENT PRIMARY KEY,
  student_id                     BIGINT NOT NULL,
  allowed_platforms              JSON NOT NULL,
  blocked_keywords               JSON NOT NULL,
  daily_limit                    INT NOT NULL DEFAULT 3,
  allow_entertainment_interests  TINYINT(1) NOT NULL DEFAULT 0,
  updated_by                     BIGINT NULL,
  created_at                     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uk_recommendation_boundary_student (student_id),
  KEY idx_recommendation_boundaries_updated_by (updated_by),
  CONSTRAINT fk_recommendation_boundaries_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_recommendation_boundaries_updated_by FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='家长推荐边界配置';
