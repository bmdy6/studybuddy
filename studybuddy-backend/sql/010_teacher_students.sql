-- 010: 家长-学生绑定关系
-- 多家庭/开放前的权限边界：teacher 只能管理 teacher_students 里绑定的 student。

USE studybuddy;

CREATE TABLE IF NOT EXISTS teacher_students (
  teacher_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (teacher_id, student_id),
  KEY idx_teacher_students_student (student_id),
  CONSTRAINT fk_teacher_students_teacher FOREIGN KEY (teacher_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_teacher_students_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='家长可管理学生绑定关系';

-- 兼容当前两人自用数据：迁移时把现有老师和学生全部绑定一次，后续新增学生需显式绑定。
INSERT IGNORE INTO teacher_students (teacher_id, student_id)
SELECT t.id, s.id
FROM users t
JOIN users s ON t.role = 'teacher' AND s.role = 'student';
