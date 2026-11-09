"""幂等：创建 memory_relations 表，并补齐后加的 updated_at 列"""
from pathlib import Path
import pymysql
from app.config import settings, reveal_secret
def run():
    conn = pymysql.connect(host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER, password=reveal_secret(settings.DB_PASSWORD), database=settings.DB_NAME)
    cur = conn.cursor()
    sql_path = Path(__file__).resolve().parent.parent / "sql" / "029_memory_relations.sql"
    cur.execute(sql_path.read_text(encoding="utf-8"))
    # 建表语句是 IF NOT EXISTS：已经建过表的环境拿不到新列，这里幂等补
    cur.execute("SHOW COLUMNS FROM memory_relations LIKE 'updated_at'")
    if cur.fetchone() is None:
        cur.execute("ALTER TABLE memory_relations ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
    conn.commit()
    conn.close()
    print("ensure_memory_relations done")
if __name__ == "__main__":
    run()
