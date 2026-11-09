"""幂等迁移：study_plan_items.status 加 in_progress + study_plan_item_attempts 表（U-044 任务完成判定）。

MySQL 5.7 不支持 ADD COLUMN IF NOT EXISTS，用 SHOW 判断后 ALTER/CREATE。
部署时 deploy_backend.sh 调用，可重复执行。
"""
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal


def main() -> None:
    with SessionLocal() as db:
        # 1. status Enum 加 in_progress（MODIFY COLUMN 幂等：新枚举值不影响已有数据）
        row = db.execute(text("SHOW COLUMNS FROM study_plan_items LIKE 'status'")).first()
        if row and "in_progress" not in (row[1] or ""):
            db.execute(
                text(
                    "ALTER TABLE study_plan_items "
                    "MODIFY COLUMN status ENUM('todo','in_progress','done','skipped') NOT NULL DEFAULT 'todo'"
                )
            )
            print("ensure_task_completion: study_plan_items.status added in_progress")
        else:
            print("ensure_task_completion: study_plan_items.status already has in_progress")

        # 2. study_plan_item_attempts 表
        exists = db.execute(text("SHOW TABLES LIKE 'study_plan_item_attempts'")).first()
        if not exists:
            db.execute(
                text(
                    """CREATE TABLE study_plan_item_attempts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  plan_item_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  assessment ENUM('passed','needs_retry','blocked') NOT NULL COMMENT 'AI 评估结果',
  evidence_summary TEXT NULL COMMENT '证据摘录（对话中学生作答内容或提交答案）',
  reason TEXT NULL COMMENT 'AI 判定理由',
  confidence DECIMAL(3,2) NULL COMMENT '置信度 0-1',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (plan_item_id) REFERENCES study_plan_items(id) ON DELETE CASCADE,
  INDEX idx_attempts_plan_item (plan_item_id),
  INDEX idx_attempts_student (student_id)
)"""
                )
            )
            print("ensure_task_completion: created study_plan_item_attempts")
        else:
            print("ensure_task_completion: study_plan_item_attempts exists, skip")
        db.commit()


if __name__ == "__main__":
    main()
