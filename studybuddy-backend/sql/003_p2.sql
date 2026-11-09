-- 知了 P2.1 增量迁移：兴趣/反馈/推荐/属性面板
-- 执行：PYTHONPATH=. .venv/bin/python scripts/run_ddl.py sql/003_p2.sql

USE studybuddy;

-- 11. student_interests（学生兴趣标签）
CREATE TABLE IF NOT EXISTS student_interests (
  id          BIGINT       NOT NULL AUTO_INCREMENT,
  student_id  BIGINT       NOT NULL,
  tag         VARCHAR(64)  NOT NULL  COMMENT '兴趣标签如 篮球/天文',
  source      ENUM('manual','inferred') NOT NULL DEFAULT 'manual',
  approved    TINYINT(1)   NOT NULL DEFAULT 1  COMMENT '学生是否确认',
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_student (student_id),
  CONSTRAINT fk_interest_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='学生兴趣';

-- 12. learning_feedback（学习反馈）
CREATE TABLE IF NOT EXISTS learning_feedback (
  id                  BIGINT       NOT NULL AUTO_INCREMENT,
  student_id          BIGINT       NOT NULL,
  feedback_type       ENUM('duration','resource_view','self_assess','difficulty') NOT NULL,
  content             TEXT         NOT NULL,
  related_resource_id BIGINT       NULL,
  created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='学习反馈';

-- 13. resource_recommendations（资源推荐）
CREATE TABLE IF NOT EXISTS resource_recommendations (
  id                BIGINT       NOT NULL AUTO_INCREMENT,
  student_id        BIGINT       NOT NULL,
  title             VARCHAR(256) NOT NULL,
  platform          VARCHAR(32)  NOT NULL DEFAULT 'bilibili',
  url               VARCHAR(512) NOT NULL,
  reason            TEXT         NULL,
  related_interests JSON         NULL,
  related_tags      JSON         NULL,
  clicked           TINYINT(1)   NOT NULL DEFAULT 0,
  created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_student (student_id),
  CONSTRAINT fk_rec_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='资源推荐';

-- 14. student_attributes（属性快照，保留历史成长曲线）
CREATE TABLE IF NOT EXISTS student_attributes (
  id          BIGINT       NOT NULL AUTO_INCREMENT,
  student_id  BIGINT       NOT NULL,
  snapshot    JSON         NOT NULL  COMMENT '{chinese,math,english,pe,engagement,mastered_count}',
  source      ENUM('init','exam_graded','manual') NOT NULL,
  trigger_ref VARCHAR(64)  NULL  COMMENT '触发源如exam_record_id',
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_student (student_id),
  CONSTRAINT fk_attr_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='属性快照';
