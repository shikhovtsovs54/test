#!/usr/bin/env python3
"""
Симуляция на 10 000 пользователей: полная имитация реальных действий.
- Регистрации только по реферальным ссылкам (кроме корня).
- Каждый пользователь рандомно приглашает 0–5 человек.
- Покупка матриц: рандомно 1, 2, 3 или 4 матрицы.
- Все циклы закрытий и реинвеста выполняются логикой приложения.
В конце: суммарный заработок пользователей, топ-10, заработок организатора (комиссия).

Запуск:
  cd matrix_marketing && python scripts/simulate_10k.py          # 10 000 пользователей (несколько минут)
  SIM_USERS=500 python scripts/simulate_10k.py                  # быстрый тест на 500
БД симуляции: matrix_marketing_simulation.db (отдельно от основной).
"""
import os
import random
import sys
from collections import deque

# Корень проекта — родитель каталога app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models  # noqa: F401 — регистрация моделей
from app.config import SYSTEM_USER_ID
from app import services


# Отдельная БД для симуляции
SIMULATION_DB = os.path.join(os.path.dirname(__file__), "..", "matrix_marketing_simulation.db")
TOTAL_USERS = int(os.environ.get("SIM_USERS", 10_000))  # Быстрый тест: SIM_USERS=500 python scripts/simulate_10k.py
MIN_REFERRALS = 0
MAX_REFERRALS = 5
LEVELS_OPTIONS = [
    [1],
    [1, 2],
    [1, 2, 3],
    [1, 2, 3, 4],
]


def ensure_system_user(db):
    if db.query(models.User).filter(models.User.id == SYSTEM_USER_ID).first() is None:
        db.add(
            models.User(
                id=SYSTEM_USER_ID,
                username="__SYSTEM__",
                referrer_id=None,
                balance=0.0,
                is_active=True,
            )
        )
        db.commit()


def run_simulation():
    if os.path.exists(SIMULATION_DB):
        os.remove(SIMULATION_DB)
    engine = create_engine(
        f"sqlite:///{SIMULATION_DB}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()

    try:
        ensure_system_user(db)
        # Корень — один пользователь без реферера, 4 матрицы
        root = services.register_user(db, "root", "root", None, [1, 2, 3, 4])
        root_id = root.id
        count = 1
        queue = deque([root_id])
        print(f"Старт симуляции: цель {TOTAL_USERS} пользователей. Корень id={root_id}")

        while count < TOTAL_USERS and queue:
            referrer_id = queue.popleft()
            remaining = TOTAL_USERS - count
            k = min(random.randint(MIN_REFERRALS, MAX_REFERRALS), remaining)
            if k <= 0:
                continue
            for _ in range(k):
                count += 1
                username = f"u{count}"
                levels = random.choice(LEVELS_OPTIONS)
                try:
                    user = services.register_user(db, username, "sim", referrer_id, levels)
                    queue.append(user.id)
                except Exception as e:
                    print(f"Ошибка регистрации {username}: {e}")
                    count -= 1
                    continue
            if count % 1000 == 0:
                print(f"  Зарегистрировано: {count}")

        print(f"Регистрации завершены: {count} пользователей.")

        # Обработка пула ожидания до стабилизации
        for _ in range(10):
            processed = services.process_holding_pool(db)
            if processed == 0:
                break
            print(f"  Обработан пул ожидания: {processed} записей.")

        # --- Статистика ---
        User = models.User
        Transaction = models.Transaction

        total_earned_users = (
            db.query(func.sum(User.balance))
            .filter(User.id != SYSTEM_USER_ID)
            .scalar()
            or 0
        )
        organizer_total = (
            db.query(User.balance).filter(User.id == SYSTEM_USER_ID).scalar() or 0
        )
        admin_fee_from_tx = (
            db.query(func.sum(Transaction.amount))
            .filter(
                Transaction.user_id == SYSTEM_USER_ID,
                Transaction.type == "admin_fee",
            )
            .scalar()
            or 0
        )
        total_matrix_bonus = (
            db.query(func.sum(Transaction.amount))
            .filter(Transaction.type == "matrix_bonus")
            .scalar()
            or 0
        )
        total_users_final = db.query(User).filter(User.id != SYSTEM_USER_ID).count()

        # Оборот = все платежи пользователей (из комиссии 10%: оборот = admin_fee / 0.10)
        total_turnover = (admin_fee_from_tx or 0) / 0.10
        expected_90_percent = total_turnover * 0.90  # сколько должно уйти в сеть по плану

        top10 = (
            db.query(User.id, User.username, User.balance)
            .filter(User.id != SYSTEM_USER_ID)
            .order_by(User.balance.desc())
            .limit(10)
            .all()
        )

        print()
        print("=" * 60)
        print("РЕЗУЛЬТАТЫ СИМУЛЯЦИИ")
        print("=" * 60)
        print(f"Пользователей в системе: {total_users_final}")
        print()
        print("Оборот и распределение (100% = оборот):")
        print(f"  Оборот (все платежи за матрицы): ${total_turnover:,.2f}")
        print(f"  Комиссия организатора (10%):     ${organizer_total:,.2f}")
        print(f"  В сеть по плану (90%):            ${expected_90_percent:,.2f}")
        print(f"  Фактически выплачено в сеть:      ${total_matrix_bonus:,.2f}")
        in_pipeline = expected_90_percent - total_matrix_bonus
        print(f"  В пути (ещё не выплачено):        ${in_pipeline:,.2f}")
        print()
        print("Пояснение: 10% комиссии считаются от оборота при каждой покупке.")
        print("90% зачисляются в сеть по мере заполнения позиций 4–7 в матрицах.")
        print("Пока не все места заполнены, часть 90% остаётся «в пути».")
        print()
        print("Топ-10 пользователей по сумме заработка:")
        print("-" * 60)
        for i, (uid, name, bal) in enumerate(top10, 1):
            print(f"  {i:2}. {name:12} (id={uid:5})  ${bal:,.2f}")
        print("-" * 60)
        print(f"Заработок организатора (комиссия 10%): ${organizer_total:,.2f}")
        print("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    run_simulation()
