"""
Тестовый сценарий: root + 8 пользователей под ним.
Проверка баланса root ($540 при полном заполнении 4 матриц) и реинвеста.
Запуск: из корня проекта
  python -m tests.test_scenario
"""
import sys
from pathlib import Path

# Добавляем корень проекта в path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, Base, engine
from app.models import User
from app.config import SYSTEM_USER_ID
from app import services


def get_db():
    return SessionLocal()


def run():
    Base.metadata.create_all(bind=engine)
    db = get_db()
    try:
        # Системный пользователь
        if db.query(User).filter(User.id == SYSTEM_USER_ID).first() is None:
            db.add(User(id=SYSTEM_USER_ID, username="__SYSTEM__", referrer_id=None, balance=0.0, is_active=True))
            db.commit()

        # 1. Root с полным комплектом
        root = services.register_user(db, "root", "root", None, [1, 2, 3, 4])
        print(f"Root создан: id={root.id}, username={root.username}")

        # 2. 8 пользователей под root (заполнят все 4 матрицы root: 2 на первую линию, 6 на вторую = 4 места в последней линии)
        for i in range(1, 9):
            u = services.register_user(db, f"user{i}", "test", root.id, [1, 2, 3, 4])
            print(f"  user{i} id={u.id} зарегистрирован под root")

        db.refresh(root)
        root_balance = services.get_balance(db, root.id)
        print(f"\nБаланс root: ${root_balance}")
        print("Ожидаем: ~$390 (доход $540 минус реинвест $150 за 4 матрицы)")

        root_matrices = services.get_user_matrices(db, root.id, active_only=True)
        print(f"Активные матрицы root после реинвеста: {[f'M{m.matrix_level}' for m in root_matrices]}")
        print("Ожидаем: M1, M2, M3, M4 (новые после реинвеста)")

        # Проверка: после реинвеста остаётся 390
        assert root_balance >= 380, f"Баланс root после реинвеста ~390, получено {root_balance}"
        assert len(root_matrices) == 4, f"У root должны быть 4 активные матрицы, получено {len(root_matrices)}"
        print("\n✓ Тестовый сценарий пройден.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
