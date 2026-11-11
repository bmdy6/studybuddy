"""hobbybuddy 数据库连接：独立库（DB_NAME=hobbybuddy）。

模仿底座 app/database.py，但连 hobbybuddy 自己的库，用自己的 config。
"""

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from hobby.config import settings

SQLALCHEMY_DATABASE_URL = URL.create(
    "mysql+pymysql",
    username=settings.secrets.DB_USER,
    password=settings.secrets.DB_PASSWORD,
    host=settings.secrets.DB_HOST,
    port=settings.secrets.DB_PORT,
    database=settings.secrets.DB_NAME,
    query={"charset": "utf8mb4"},
)

engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
