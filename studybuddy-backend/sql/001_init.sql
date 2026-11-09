-- 知了 (XZ-StudyBuddy) 数据库初始化脚本
-- 数据库：MySQL 5.7（腾讯云，端口 3307，新库 studybuddy）
-- 字符集：utf8mb4 / utf8mb4_unicode_ci  存储引擎：InnoDB
-- 当前结构以本迁移和 ORM model 为准；历史数据模型文档见 docs/archive/2026-07-04/数据模型文档.md

CREATE DATABASE IF NOT EXISTS studybuddy
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE studybuddy;

-- 1. users（用户：teacher=老师 / student=学生）
CREATE TABLE users (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  username        VARCHAR(64)  NOT NULL,
  password_hash   VARCHAR(255) NOT NULL  COMMENT 'bcrypt 哈希',
  role            ENUM('teacher','student') NOT NULL,
  display_name    VARCHAR(64)  NULL,
  web_login_enabled TINYINT(1) NOT NULL DEFAULT 1,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户表：teacher=老师(我)，student=学生(弟弟)';

-- 2. materials（材料库）
CREATE TABLE materials (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  name            VARCHAR(128) NOT NULL,
  type            ENUM('vocab','grammar','image','other') NOT NULL,
  source          ENUM('teacher','student') NOT NULL  COMMENT '来源：老师导入 vs 弟弟上传',
  content_ref     VARCHAR(512) NULL  COMMENT 'COS key（图片）或文本内容',
  knowledge_tags  JSON         NULL  COMMENT '关联知识点 ["U5","过去时"]',
  uploaded_by     BIGINT       NOT NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_source (source),
  KEY idx_uploaded_by (uploaded_by),
  CONSTRAINT fk_materials_user FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='材料库：单词表/语法点/弟弟上传素材';

-- 3. exams（试卷）
CREATE TABLE exams (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  title           VARCHAR(200) NOT NULL,
  subject         VARCHAR(64)  NOT NULL  COMMENT 'english/math/chinese',
  feedback_mode   ENUM('immediate','after_submit','hidden') NOT NULL DEFAULT 'after_submit'
                  COMMENT '反馈门控：练习卷即时/考试卷交卷后/不显示',
  shuffle_groups BOOL         NOT NULL DEFAULT FALSE  COMMENT '题组随机抽题',
  status          ENUM('draft','published','archived') NOT NULL DEFAULT 'draft',
  published_at    DATETIME     NULL,
  created_by      BIGINT       NOT NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_status (status),
  KEY idx_created_by (created_by),
  CONSTRAINT fk_exams_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='试卷表';

-- 4. questions（题目：answer_json 严禁通过 GET /api/exam/{id} 下发）
CREATE TABLE questions (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  exam_id         BIGINT       NOT NULL,
  group_id        VARCHAR(64)  NULL  COMMENT '题组标识，配合 shuffle',
  type            ENUM('single_choice','multi_choice','fill_blank','transform',
                       'translation','essay','math_answer') NOT NULL,
  stem            TEXT         NOT NULL,
  options         JSON         NULL  COMMENT '选择题选项 ["A","B","C","D"]',
  answer_json     JSON         NOT NULL  COMMENT '★标准答案，永不下发客户端',
  score           DECIMAL(5,2) NOT NULL,
  knowledge_tags  JSON         NULL  COMMENT '考点标签，错题归类依据',
  PRIMARY KEY (id),
  KEY idx_exam_id (exam_id),
  KEY idx_group_id (group_id),
  CONSTRAINT fk_questions_exam FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='题目表：answer_json 严禁通过 GET /api/exam/{id} 下发';

-- 5. exam_assignments（试卷定向分发）
CREATE TABLE exam_assignments (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  exam_id         BIGINT       NOT NULL,
  student_id      BIGINT       NOT NULL,
  assigned_by     BIGINT       NOT NULL,
  status          ENUM('assigned','started','submitted','cancelled') NOT NULL DEFAULT 'assigned',
  due_at          DATETIME     NULL,
  note            VARCHAR(500) NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_exam_assignment_exam_student (exam_id, student_id),
  KEY idx_exam_assignments_student_status (student_id, status),
  CONSTRAINT fk_exam_assignments_exam FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
  CONSTRAINT fk_exam_assignments_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_exam_assignments_assigned_by FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='试卷定向分发表';

-- 6. exam_records（考试记录）
CREATE TABLE exam_records (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  exam_id         BIGINT       NOT NULL,
  student_id      BIGINT       NOT NULL,
  status          ENUM('in_progress','submitted','graded') NOT NULL DEFAULT 'in_progress',
  total_score     DECIMAL(6,2) NULL  COMMENT '总分，graded 后填',
  started_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  submitted_at    DATETIME     NULL,
  PRIMARY KEY (id),
  KEY idx_exam_student (exam_id, student_id),
  KEY idx_student_status (student_id, status),
  CONSTRAINT fk_records_exam FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
  CONSTRAINT fk_records_user FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='考试记录表';

-- 7. answers（作答）
CREATE TABLE answers (
  id                  BIGINT       NOT NULL AUTO_INCREMENT,
  exam_record_id      BIGINT       NOT NULL,
  question_id         BIGINT       NOT NULL,
  student_answer      TEXT         NULL  COMMENT '学生作答内容',
  score               DECIMAL(5,2) NULL  COMMENT '0-满分，支持部分分',
  is_correct          TINYINT      NULL  COMMENT '0=错,1=对,NULL=未判(manual)',
  is_manual_graded    TINYINT      NOT NULL DEFAULT 0  COMMENT '1=老师人工打分',
  manual_score        DECIMAL(5,2) NULL  COMMENT '老师给的分',
  manual_comment      TEXT         NULL  COMMENT '老师评语',
  graded_at           DATETIME     NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_record_question (exam_record_id, question_id),
  KEY idx_question (question_id),
  KEY idx_manual_pending (is_manual_graded, is_correct),
  CONSTRAINT fk_answers_record FOREIGN KEY (exam_record_id) REFERENCES exam_records(id) ON DELETE CASCADE,
  CONSTRAINT fk_answers_question FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='作答表';

-- 8. error_book（错题本：按 knowledge_tags 自动归类）
CREATE TABLE error_book (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  student_id      BIGINT       NOT NULL,
  question_id     BIGINT       NOT NULL,
  exam_record_id  BIGINT       NOT NULL,
  knowledge_tags  JSON         NULL  COMMENT '从 question 冗余，加速聚合',
  error_count     INT          NOT NULL DEFAULT 1,
  last_wrong_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_student_question (student_id, question_id)  COMMENT '同生同题只留一条，再错更新 count',
  KEY idx_student_tags (student_id),
  KEY idx_last_wrong (student_id, last_wrong_at),
  CONSTRAINT fk_error_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_error_question FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
  CONSTRAINT fk_error_record FOREIGN KEY (exam_record_id) REFERENCES exam_records(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='错题本：按 knowledge_tags 自动归类';

-- 9. grading_rules（判分规则：每题一条规则，规则即数据）
CREATE TABLE grading_rules (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  question_id     BIGINT       NOT NULL,
  rule_type       ENUM('auto_exact','auto_fuzzy','manual') NOT NULL,
  matcher         ENUM('exact','regex','float_tol','levenshtein') NOT NULL DEFAULT 'exact'
                  COMMENT '匹配器类型，开闭原则：新增走新枚举值',
  match_params    JSON         NULL  COMMENT '匹配参数 {tolerance,accept_aliases,float_eps,ignore_case,strip_punct}',
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_question (question_id),
  CONSTRAINT fk_grading_question FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='判分规则表：每题一条规则，规则即数据';

-- 诊断聚合：knowledge_tags 生成虚拟列索引（加速按标签聚合）
ALTER TABLE error_book
  ADD COLUMN tag_array VARCHAR(255) AS (JSON_UNQUOTE(JSON_EXTRACT(knowledge_tags, '$'))) VIRTUAL,
  ADD KEY idx_tag_array (tag_array);

-- 注意：初始用户 password_hash 需运行时通过脚本生成，不硬编码在 DDL 里（约束 #8）。
