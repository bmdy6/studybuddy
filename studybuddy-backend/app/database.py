from sqlalchemy import URL, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import reveal_secret, settings

SQLALCHEMY_DATABASE_URL = URL.create(
    "mysql+pymysql",
    username=settings.DB_USER,
    password=reveal_secret(settings.DB_PASSWORD),
    host=settings.DB_HOST,
    port=settings.DB_PORT,
    database=settings.DB_NAME,
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
