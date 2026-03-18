import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    User,
    UserMatrix,
    MatrixPosition,
    Transaction,
    HoldingPool,
    WithdrawalRequest,
    SupportRequest,
    DepositInvoice,
)


# Локальный SQLite, откуда забираем данные
SQLITE_URL = "sqlite:///./matrix_marketing.db"

# PostgreSQL на Railway, куда переносим данные.
# Перед запуском поставьте переменную окружения DATABASE_URL_PG
# равной вашему URL, например:
# export DATABASE_URL_PG="postgresql://postgres:...@postgres.railway.internal:5432/railway"
PG_URL = os.environ.get("DATABASE_URL_PG")

if not PG_URL:
    raise RuntimeError(
        "Установите переменную окружения DATABASE_URL_PG с URL PostgreSQL Railway"
    )


sqlite_engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
pg_engine = create_engine(PG_URL)

SQLiteSession = sessionmaker(bind=sqlite_engine)
PGSession = sessionmaker(bind=pg_engine)


def copy_table(src_sess, dst_sess, Model):
    rows = src_sess.query(Model).all()
    if not rows:
        return
    objs = []
    for row in rows:
        data = {c.name: getattr(row, c.name) for c in Model.__table__.columns}
        objs.append(Model(**data))
    dst_sess.bulk_save_objects(objs)
    dst_sess.commit()
    print(f"Copied {len(objs)} rows of {Model.__tablename__}")


def main():
    # Создаём схему в PostgreSQL, если её ещё нет
    Base.metadata.create_all(bind=pg_engine)

    src = SQLiteSession()
    dst = PGSession()

    try:
        # Порядок важен из‑за внешних ключей
        copy_table(src, dst, User)
        copy_table(src, dst, UserMatrix)
        copy_table(src, dst, MatrixPosition)
        copy_table(src, dst, Transaction)
        copy_table(src, dst, HoldingPool)
        copy_table(src, dst, WithdrawalRequest)
        copy_table(src, dst, SupportRequest)
        copy_table(src, dst, DepositInvoice)
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    main()

