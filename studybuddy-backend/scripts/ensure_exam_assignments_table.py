import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS exam_assignments (
  id BIGINT NOT NULL AUTO_INCREMENT,
  exam_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  assigned_by BIGINT NOT NULL,
  status ENUM('assigned','started','submitted','cancelled') NOT NULL DEFAULT 'assigned',
  due_at DATETIME NULL,
  note VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_exam_assignment_exam_student (exam_id, student_id),
  KEY idx_exam_assignments_student_status (student_id, status),
  CONSTRAINT fk_exam_assignments_exam FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
  CONSTRAINT fk_exam_assignments_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_exam_assignments_assigned_by FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='试卷定向分发表'
"""


def ensure_exam_assignments_table(session_factory=SessionLocal) -> bool:
    with session_factory() as db:
        exists = db.execute(text("SHOW TABLES LIKE 'exam_assignments'")).first() is not None
        db.execute(text(CREATE_TABLE_SQL))
        db.commit()
        return not exists


def main() -> None:
    created = ensure_exam_assignments_table()
    if created:
        print("已创建 exam_assignments 表")
    else:
        print("exam_assignments 表已存在，无需修改")


if __name__ == "__main__":
    main()
