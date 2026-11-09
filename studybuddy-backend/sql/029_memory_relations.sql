-- 029 记忆关系边
CREATE TABLE IF NOT EXISTS memory_relations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  source_type VARCHAR(20) NOT NULL,
  source_id BIGINT NOT NULL,
  target_type VARCHAR(20) NOT NULL,
  target_id BIGINT NOT NULL,
  relation VARCHAR(20) NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_memory_student_source (student_id, source_type, source_id),
  INDEX idx_memory_student_target (student_id, target_type, target_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
