"""幂等添加 users.mode（study=学习默认 / hobby=兴趣爱好，同账号模式切换）。

MySQL 5.7 不支持 ADD COLUMN IF NOT EXISTS，用 SHOW COLUMNS 判断后 ALTER。
部署时 deploy_backend.sh 调用，可重复执行（存量数据自动获得 study 默认值）。
"""
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal

COLUMN = "mode VARCHAR(16) NOT NULL DEFAULT 'study' COMMENT '模式：study=学习(默认) / hobby=兴趣爱好'"


def main() -> None:
    with SessionLocal() as db:
        existing = {row[0] for row in db.execute(text("SHOW COLUMNS FROM users")).all()}
        if "mode" in existing:
            print("ensure_user_mode: column exists, skip")
            return
        db.execute(text(f"ALTER TABLE users ADD COLUMN {COLUMN}"))
        db.commit()
        print("ensure_user_mode: added users.mode (default study)")


if __name__ == "__main__":
    main()
