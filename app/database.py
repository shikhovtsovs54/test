"""Настройка БД и сессий SQLAlchemy."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# В боевой среде (Railway) БД всегда берём из DATABASE_URL.
# Если переменная не задана — явно падаем, чтобы не создать новую пустую SQLite.
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL")
if not SQLALCHEMY_DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Укажи строку подключения к PostgreSQL Railway в переменной окружения DATABASE_URL."
    )

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
