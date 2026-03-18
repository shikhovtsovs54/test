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

# Настройки пула и keepalive, чтобы избежать 'SSL SYSCALL error: EOF detected'
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,          # проверка соединения перед использованием
    pool_recycle=300,            # рецикл коннекта раз в 5 минут
    pool_size=5,
    max_overflow=10,
    connect_args={
        # Параметры TCP keepalive для psycopg2
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        # Если Railway требует SSL, можно раскомментировать:
        # "sslmode": "require",
    },
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
