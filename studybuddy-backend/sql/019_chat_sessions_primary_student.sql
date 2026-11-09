-- 019: 学生长期主会话（每日教练与自动学习记忆 spec 3.5 / PR-05）
-- 在 chat_sessions 上增加可持久化、可被唯一约束保护的主会话标识 primary_student_id。
-- 只有学生自己的主会话写入对应学生 ID；辅导者会话和其他学生旧会话保持 NULL。
-- MySQL 5.7 唯一索引允许多个 NULL，但保证每个学生最多一个主会话。
-- 幂等：先检查 information_schema，列/索引已存在则跳过。

USE studybuddy;

-- 增量加列：primary_student_id BIGINT NULL（指向 users.id，但不加外键，避免和现有 student_id FK 冗余且影响 ondelete 行为）
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'chat_sessions'
    AND COLUMN_NAME = 'primary_student_id'
);
SET @ddl_col := IF(@col_exists = 0,
  'ALTER TABLE chat_sessions ADD COLUMN primary_student_id BIGINT NULL COMMENT ''学生主会话标识：仅学生自己的主会话写入学生 id，其余为 NULL''',
  'SELECT ''primary_student_id already exists'' AS msg');
PREPARE stmt FROM @ddl_col;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 增量加唯一索引：uk_chat_sessions_primary_student(primary_student_id)
-- MySQL 5.7 UNIQUE 索引允许多个 NULL，保证一名学生最多一个主会话。
SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'chat_sessions'
    AND INDEX_NAME = 'uk_chat_sessions_primary_student'
);
SET @ddl_idx := IF(@idx_exists = 0,
  'ALTER TABLE chat_sessions ADD UNIQUE KEY uk_chat_sessions_primary_student (primary_student_id)',
  'SELECT ''uk_chat_sessions_primary_student already exists'' AS msg');
PREPARE stmt FROM @ddl_idx;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
