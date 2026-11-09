"""幂等：为 study_plan_item_attempts 补 taught_scope / next_start 列。"""
import pymysql
from app.config import settings, reveal_secret

def run():
    conn = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=reveal_secret(settings.DB_PASSWORD),
        database=settings.DB_NAME,
    )
    cur = conn.cursor()
    cur.execute("SHOW COLUMNS FROM study_plan_item_attempts LIKE 'taught_scope'")
    if not cur.fetchone():
        cur.execute("ALTER TABLE study_plan_item_attempts ADD COLUMN taught_scope TEXT NULL COMMENT '讲解范围' AFTER reason")
        print("added taught_scope")
    cur.execute("SHOW COLUMNS FROM study_plan_item_attempts LIKE 'next_start'")
    if not cur.fetchone():
        cur.execute("ALTER TABLE study_plan_item_attempts ADD COLUMN next_start TEXT NULL COMMENT '续学位置' AFTER taught_scope")
        print("added next_start")
    conn.commit()
    conn.close()
    print("ensure_task_progress done")

if __name__ == "__main__":
    run()
