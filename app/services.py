"""
Бизнес-логика матричного маркетинга.
90% платежа в сеть (выплаты), 10% проекту.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import (
    MATRIX_PRICES,
    MATRIX_INCOME,
    MATRIX_BONUS_PER_PLACE,
    REINVEST_CONFIG,
    ADMIN_FEE_PERCENT,
    SYSTEM_USER_ID,
)
from app.models import User, UserMatrix, MatrixPosition, Transaction, HoldingPool
from app.events import log as event_log
from app.auth import generate_referral_code, hash_password

# Округление денежных сумм до центов (избегаем накопления ошибки float)
def _round_money(x: float) -> float:
    return round(float(x), 2)


# --- Вспомогательные функции баланса и транзакций ---

def add_to_balance(db: Session, user_id: int, amount: float, tx_type: str, description: str, matrix_id: Optional[int] = None) -> None:
    """Зачислить на баланс и создать транзакцию. Суммы округляются до 2 знаков."""
    amount = _round_money(amount)
    if amount <= 0:
        return
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return
    user.balance = _round_money(user.balance + amount)
    db.add(Transaction(user_id=user_id, amount=amount, type=tx_type, description=description, matrix_id=matrix_id))
    db.commit()


def withdraw_from_balance(db: Session, user_id: int, amount: float, tx_type: str, description: str, matrix_id: Optional[int] = None) -> bool:
    """Списать с баланса. Возвращает True если хватало средств. Суммы округляются до 2 знаков."""
    amount = _round_money(amount)
    if amount <= 0:
        return True
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or user.balance < amount:
        return False
    user.balance = _round_money(user.balance - amount)
    db.add(Transaction(user_id=user_id, amount=-amount, type=tx_type, description=description, matrix_id=matrix_id))
    db.commit()
    return True


def get_balance(db: Session, user_id: int) -> float:
    """Текущий баланс пользователя (округлён до центов)."""
    user = db.query(User).filter(User.id == user_id).first()
    return _round_money(user.balance) if user else 0.0


def has_active_matrix(db: Session, user_id: int, matrix_level: int) -> bool:
    """Есть ли у пользователя активная матрица данного уровня."""
    return db.query(UserMatrix).filter(
        UserMatrix.user_id == user_id,
        UserMatrix.matrix_level == matrix_level,
        UserMatrix.status == "active",
    ).first() is not None


def get_active_matrix(db: Session, user_id: int, matrix_level: int) -> Optional[UserMatrix]:
    """Получить активную матрицу пользователя по уровню."""
    return db.query(UserMatrix).filter(
        UserMatrix.user_id == user_id,
        UserMatrix.matrix_level == matrix_level,
        UserMatrix.status == "active",
    ).first()


def create_user_matrix(db: Session, user_id: int, matrix_level: int) -> UserMatrix:
    """Создать новую матрицу пользователя (владельца). Позиция 1 = владелец."""
    m = UserMatrix(user_id=user_id, matrix_level=matrix_level, status="active")
    db.add(m)
    db.flush()
    pos1 = MatrixPosition(matrix_id=m.id, user_id=user_id, position=1, parent_position_id=None)
    db.add(pos1)
    db.commit()
    db.refresh(m)
    return m


def get_occupied_positions(db: Session, matrix_id: int) -> set:
    """Множество занятых позиций в матрице (1-7)."""
    positions = db.query(MatrixPosition.position).filter(MatrixPosition.matrix_id == matrix_id).all()
    return {p[0] for p in positions}


# --- Размещение в матрице (ядро) ---

def _user_already_in_matrix(db: Session, matrix_id: int, user_id: int) -> bool:
    """Проверка: один человек — одна позиция в матрице."""
    return db.query(MatrixPosition).filter(
        MatrixPosition.matrix_id == matrix_id,
        MatrixPosition.user_id == user_id,
    ).first() is not None


def place_in_matrix(
    db: Session, owner_id: int, new_user_id: int, matrix_level: int,
    on_bonus_callback=None,
) -> bool:
    """
    Размещает new_user_id в матрице владельца owner_id уровня matrix_level.
    Правило: 1 человек = 1 позиция в матрице. Владелец только на месте 1 (при создании).
    Приоритет: 2, 3, затем 4, 5 (под левым), затем 6, 7 (под правым).
    При постановке на 4,5,6,7: ставим владельцу на это место И перелив — того же человека в матрицу того, кто на 2 (для 4–5) или на 3 (для 6–7).
    """
    if new_user_id == owner_id:
        return False
    matrix = get_active_matrix(db, owner_id, matrix_level)
    if matrix is None:
        return False
    if _user_already_in_matrix(db, matrix.id, new_user_id):
        return False

    occupied = get_occupied_positions(db, matrix.id)

    # ШАГ 1: Позиции 2, 3
    if 2 not in occupied:
        pos = MatrixPosition(matrix_id=matrix.id, user_id=new_user_id, position=2, parent_position_id=None)
        db.add(pos)
        db.commit()
        return True
    if 3 not in occupied:
        pos = MatrixPosition(matrix_id=matrix.id, user_id=new_user_id, position=3, parent_position_id=None)
        db.add(pos)
        db.commit()
        return True

    # ШАГ 2: Позиции 4, 5, 6, 7 — parent для связей
    pos2 = db.query(MatrixPosition).filter(MatrixPosition.matrix_id == matrix.id, MatrixPosition.position == 2).first()
    pos3 = db.query(MatrixPosition).filter(MatrixPosition.matrix_id == matrix.id, MatrixPosition.position == 3).first()
    user_in_pos2 = pos2.user_id if pos2 else None
    user_in_pos3 = pos3.user_id if pos3 else None
    parent_2_id = pos2.id if pos2 else None
    parent_3_id = pos3.id if pos3 else None

    # ШАГ 3: Позиции 4, 5 (под левым) — владельцу на 4/5, затем перелив в матрицу того, кто на месте 2
    if 4 not in occupied:
        pos = MatrixPosition(matrix_id=matrix.id, user_id=new_user_id, position=4, parent_position_id=parent_2_id)
        db.add(pos)
        db.commit()
        _pay_bonus_and_check_completion(db, owner_id, matrix.id, matrix_level, on_bonus_callback)
        if user_in_pos2 and user_in_pos2 != new_user_id and user_in_pos2 != owner_id:
            place_in_matrix(db, user_in_pos2, new_user_id, matrix_level, on_bonus_callback)
        return True
    if 5 not in occupied:
        pos = MatrixPosition(matrix_id=matrix.id, user_id=new_user_id, position=5, parent_position_id=parent_2_id)
        db.add(pos)
        db.commit()
        _pay_bonus_and_check_completion(db, owner_id, matrix.id, matrix_level, on_bonus_callback)
        if user_in_pos2 and user_in_pos2 != new_user_id and user_in_pos2 != owner_id:
            place_in_matrix(db, user_in_pos2, new_user_id, matrix_level, on_bonus_callback)
        return True

    # ШАГ 4: Позиции 6, 7 (под правым) — владельцу на 6/7, затем перелив в матрицу того, кто на месте 3
    if 6 not in occupied:
        pos = MatrixPosition(matrix_id=matrix.id, user_id=new_user_id, position=6, parent_position_id=parent_3_id)
        db.add(pos)
        db.commit()
        _pay_bonus_and_check_completion(db, owner_id, matrix.id, matrix_level, on_bonus_callback)
        if user_in_pos3 and user_in_pos3 != new_user_id and user_in_pos3 != owner_id:
            place_in_matrix(db, user_in_pos3, new_user_id, matrix_level, on_bonus_callback)
        return True
    if 7 not in occupied:
        pos = MatrixPosition(matrix_id=matrix.id, user_id=new_user_id, position=7, parent_position_id=parent_3_id)
        db.add(pos)
        db.commit()
        _pay_bonus_and_check_completion(db, owner_id, matrix.id, matrix_level, on_bonus_callback)
        if user_in_pos3 and user_in_pos3 != new_user_id and user_in_pos3 != owner_id:
            place_in_matrix(db, user_in_pos3, new_user_id, matrix_level, on_bonus_callback)
        return True

    return False


def _pay_bonus_and_check_completion(db: Session, owner_id: int, matrix_id: int, matrix_level: int, on_bonus_callback=None) -> None:
    """Начислить бонус за место в последней линии и проверить закрытие матрицы."""
    bonus = _round_money(MATRIX_BONUS_PER_PLACE[matrix_level])
    add_to_balance(
        db, owner_id, bonus, "matrix_bonus",
        f"Место в M{matrix_level} (матрица id={matrix_id})",
        matrix_id=matrix_id,
    )
    owner = db.query(User).filter(User.id == owner_id).first()
    owner_name = owner.username if owner else str(owner_id)
    event_log(f"User {owner_name} (id={owner_id}) получил ${bonus} за место в M{matrix_level}")
    if on_bonus_callback:
        on_bonus_callback(owner_id, matrix_level, bonus, matrix_id)
    check_matrix_completion(db, matrix_id, owner_id, matrix_level, on_bonus_callback)


def check_matrix_completion(
    db: Session, matrix_id: int, owner_id: int, matrix_level: int,
    on_bonus_callback=None,
) -> bool:
    """Если все позиции 4,5,6,7 заняты — закрыть матрицу и запустить реинвест."""
    occupied = get_occupied_positions(db, matrix_id)
    if not ({4, 5, 6, 7} <= occupied):
        return False

    matrix = db.query(UserMatrix).filter(UserMatrix.id == matrix_id).first()
    if not matrix or matrix.status != "active":
        return False

    matrix.status = "closed"
    matrix.closed_at = datetime.utcnow()
    db.commit()
    owner = db.query(User).filter(User.id == owner_id).first()
    owner_name = owner.username if owner else str(owner_id)
    event_log(f"Матрица M{matrix_level} пользователя {owner_name} (id={owner_id}) закрылась, реинвест по конфигу")

    auto_reinvest(db, owner_id, matrix_level, on_bonus_callback)
    return True


def auto_reinvest(
    db: Session, user_id: int, closed_matrix_level: int,
    on_bonus_callback=None,
) -> None:
    """
    При закрытии матрицы:
    1. Открыть новые матрицы по REINVEST_CONFIG (уровень 2 реинвест и т.д.).
    2. Разместить этого пользователя у первого вышестоящего по каждому открытому уровню
       на первое свободное место (как только нижестоящий перешёл на уровень 2 или выше —
       он автоматически встаёт к первому вышестоящему с таким же или большим уровнем).
    Сохраняется логика: при постановке на 4–7 человек считается в 2 матрицах (владелец + перелив).
    """
    config = REINVEST_CONFIG[closed_matrix_level]
    matrices_to_open = config["matrices"]

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return

    for level in matrices_to_open:
        if not has_active_matrix(db, user_id, level):
            create_user_matrix(db, user_id, level)
    db.commit()

    # Разместить пользователя у первого вышестоящего с активной матрицей этого уровня на первое свободное место
    if user.referrer_id:
        for level in matrices_to_open:
            if find_placement_in_chain(db, user.referrer_id, user_id, level, on_bonus_callback):
                event_log(f"После реинвеста: {user.username} (id={user_id}) размещён у вышестоящих по уровню M{level}")


def find_placement_in_chain(
    db: Session, start_sponsor_id: Optional[int], new_user_id: int, matrix_level: int,
    on_bonus_callback=None,
) -> bool:
    """
    Ищет место для new_user_id в матрице уровня matrix_level, поднимаясь от start_sponsor вверх.
    """
    if start_sponsor_id is None:
        db.add(HoldingPool(user_id=new_user_id, matrix_level=matrix_level, referrer_id=new_user_id))
        db.commit()
        return False

    current_id = start_sponsor_id
    while current_id is not None:
        sponsor = db.query(User).filter(User.id == current_id).first()
        if current_id == new_user_id:
            current_id = sponsor.referrer_id if sponsor else None
            continue
        if sponsor and has_active_matrix(db, current_id, matrix_level):
            if place_in_matrix(db, current_id, new_user_id, matrix_level, on_bonus_callback):
                return True
        current_id = sponsor.referrer_id if sponsor else None

    db.add(HoldingPool(user_id=new_user_id, matrix_level=matrix_level, referrer_id=start_sponsor_id))
    db.commit()
    return False


def _unique_referral_code(db: Session) -> str:
    """Генерирует уникальный реферальный код."""
    for _ in range(20):
        code = generate_referral_code()
        if db.query(User).filter(User.referral_code == code).first() is None:
            return code
    raise RuntimeError("Could not generate unique referral code")


def get_user_by_referral_code(db: Session, code: str) -> Optional[User]:
    """Найти пользователя по реферальному коду."""
    return db.query(User).filter(User.referral_code == code).first()


def get_user_by_telegram_id(db: Session, telegram_id: int) -> Optional[User]:
    """Найти пользователя по Telegram ID."""
    return db.query(User).filter(User.telegram_id == telegram_id).first()


def create_telegram_user(
    db: Session,
    telegram_id: int,
    username_from_tg: Optional[str] = None,
    referrer_telegram_id: Optional[int] = None,
) -> User:
    """
    Создать пользователя по данным из Telegram (без матриц).
    Реферер задаётся по telegram_id; сам на себя ссылаться нельзя (referrer_telegram_id == telegram_id игнорируется).
    """
    if referrer_telegram_id is not None and referrer_telegram_id == telegram_id:
        referrer_telegram_id = None
    referrer_id = None
    if referrer_telegram_id is not None:
        ref_user = get_user_by_telegram_id(db, referrer_telegram_id)
        if ref_user and ref_user.id != SYSTEM_USER_ID:
            referrer_id = ref_user.id
    username = (username_from_tg or "").strip() or f"tg{telegram_id}"
    if len(username) > 64:
        username = username[:64]
    ref_code = _unique_referral_code(db)
    user = User(
        username=username,
        telegram_id=telegram_id,
        password_hash=None,
        referral_code=ref_code,
        referrer_id=referrer_id,
        balance=0.0,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    event_log(f"Telegram user {username} (tg_id={telegram_id}) создан в БД")
    return user


def ensure_telegram_user(
    db: Session,
    telegram_id: int,
    username_from_tg: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    referrer_telegram_id: Optional[int] = None,
) -> User:
    """
    Найти пользователя по telegram_id или создать. При /start бот вызывает это —
    пользователь сразу оказывается в БД; при открытии веб-приложения ищем по telegram_id и открываем ЛК.
    """
    user = get_user_by_telegram_id(db, telegram_id)
    if user:
        print(f"[services] ensure_telegram_user: telegram_id={telegram_id} — уже в БД user_id={user.id}")
        return user
    user = create_telegram_user(
        db,
        telegram_id=telegram_id,
        username_from_tg=username_from_tg,
        referrer_telegram_id=referrer_telegram_id,
    )
    print(f"[services] ensure_telegram_user: telegram_id={telegram_id} — создан в БД user_id={user.id}")
    return user


# --- Регистрация ---

def register_user(
    db: Session,
    username: str,
    password: str,
    referrer_id: Optional[int],
    purchased_levels: List[int],
    on_bonus_callback=None,
    on_reinvest_callback=None,
) -> User:
    """
    1. Создать пользователя
    2. Стоимость = sum(MATRIX_PRICES[l] for l in purchased_levels)
    3. 10% — admin_fee (проекту), 90% распределяется через выплаты при размещении
    4. Создать собственные матрицы пользователя для каждого уровня
    5. Для каждого уровня разместить в цепочке реферера (find_placement_in_chain)
    """
    # Только уровни 1–4, без дубликатов
    levels_ok = sorted(set(int(l) for l in purchased_levels if l in (1, 2, 3, 4)))
    if not levels_ok:
        raise ValueError("levels must be 1, 2, 3 or 4")
    total_cost = _round_money(sum(MATRIX_PRICES[l] for l in levels_ok))
    admin_fee = _round_money(total_cost * (ADMIN_FEE_PERCENT / 100))

    ref_code = _unique_referral_code(db)
    user = User(
        username=username,
        password_hash=hash_password(password),
        referrer_id=referrer_id,
        balance=0.0,
        referral_code=ref_code,
    )
    db.add(user)
    db.flush()

    # 10% проекту (записываем как списание у системного пользователя или просто транзакция)
    sys_user = db.query(User).filter(User.id == SYSTEM_USER_ID).first()
    if sys_user:
        sys_user.balance = _round_money(sys_user.balance + admin_fee)
    db.add(Transaction(user_id=SYSTEM_USER_ID, amount=admin_fee, type="admin_fee", description=f"10% от регистрации {username} (${total_cost})"))
    event_log(f"User {username} зарегистрирован с матрицами M{','.join(map(str, levels_ok))}")

    for level in levels_ok:
        create_user_matrix(db, user.id, level)

    for level in levels_ok:
        find_placement_in_chain(db, referrer_id, user.id, level, on_bonus_callback)

    db.commit()
    db.refresh(user)
    return user


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def get_all_users(db: Session) -> List[User]:
    return db.query(User).order_by(User.id).all()


def get_user_matrices(db: Session, user_id: int, active_only: bool = False):
    q = db.query(UserMatrix).filter(UserMatrix.user_id == user_id)
    if active_only:
        q = q.filter(UserMatrix.status == "active")
    return q.order_by(UserMatrix.matrix_level).all()


def get_matrix_with_positions(db: Session, matrix_id: int):
    """Матрица и все позиции с пользователями."""
    matrix = db.query(UserMatrix).filter(UserMatrix.id == matrix_id).first()
    if not matrix:
        return None
    positions = db.query(MatrixPosition).filter(MatrixPosition.matrix_id == matrix_id).order_by(MatrixPosition.position).all()
    return {"matrix": matrix, "positions": positions}


def get_referral_tree(db: Session, user_id: int, depth: int = 10) -> dict:
    """Дерево рефералов (рекурсивно)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {}
    refs = db.query(User).filter(User.referrer_id == user_id).all()
    return {
        "id": user.id,
        "username": user.username,
        "referrals": [get_referral_tree(db, r.id, depth - 1) for r in refs[:20]] if depth > 0 else [],
    }


def _can_purchase_levels(db: Session, user_id: int, levels_ok: List[int]) -> bool:
    """
    Проверка последовательности докупки: чтобы купить уровень L, должны быть куплены 1..L-1.
    Матрицы докупаются строго по порядку: нельзя купить M3 без M1 и M2, M4 — без M1,M2,M3.
    """
    owned = {lv for lv in (1, 2, 3, 4) if has_active_matrix(db, user_id, lv)}
    for L in levels_ok:
        for k in range(1, L):
            if k not in owned:
                return False
        owned.add(L)
    return True


def purchase_matrices(db: Session, user_id: int, levels: List[int], on_bonus_callback=None) -> bool:
    """
    Докупка матриц: списание с баланса, создание матриц, размещение в цепочке реферера.
    Уровни 1–4, без дубликатов. Докупка только по порядку: M2 требует M1, M3 — M1+M2, M4 — M1+M2+M3.
    При докупке пользователь размещается в матрицах вышестоящих по каждому докупленному уровню
    (алгоритм тот же, что при регистрации; матрицы по уровням независимы — можно быть в разных ветках).
    """
    levels_ok = sorted(set(int(l) for l in levels if l in (1, 2, 3, 4)))
    if not levels_ok:
        return False
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    if not _can_purchase_levels(db, user_id, levels_ok):
        return False
    total = _round_money(sum(MATRIX_PRICES[l] for l in levels_ok))
    if user.balance < total:
        return False

    admin_fee = _round_money(total * (ADMIN_FEE_PERCENT / 100))
    sys_user = db.query(User).filter(User.id == SYSTEM_USER_ID).first()
    if sys_user:
        sys_user.balance = _round_money(sys_user.balance + admin_fee)
    db.add(Transaction(user_id=SYSTEM_USER_ID, amount=admin_fee, type="admin_fee", description=f"10% от покупки M{levels_ok}"))
    withdraw_from_balance(db, user_id, total, "purchase", f"Покупка матриц {levels_ok}", matrix_id=None)

    for level in levels_ok:
        if not has_active_matrix(db, user_id, level):
            create_user_matrix(db, user_id, level)

    # Размещение в цепочке реферера по каждому докупленному уровню (как при регистрации)
    for level in levels_ok:
        if find_placement_in_chain(db, user.referrer_id, user_id, level, on_bonus_callback):
            event_log(f"После докупки: {user.username} (id={user_id}) размещён в цепочке по уровню M{level}")
        # иначе попал в holding_pool по этому уровню — обработается позже

    db.commit()
    return True


def add_funds(db: Session, user_id: int, amount: float, description: str | None = None) -> bool:
    """Пополнение баланса. description — описание для транзакции (по умолчанию «Ручное пополнение»)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    desc = description or "Ручное пополнение (тест)"
    add_to_balance(db, user_id, amount, "credit", desc, matrix_id=None)
    event_log(f"User {user.username} (id={user_id}) пополнен на ${amount}")
    return True


def process_holding_pool(db: Session, on_bonus_callback=None) -> int:
    """Обработать пул ожидания: попытаться разместить снова по referrer_id."""
    count = 0
    entry_ids = [e.id for e in db.query(HoldingPool).all()]
    for eid in entry_ids:
        entry = db.query(HoldingPool).filter(HoldingPool.id == eid).first()
        if not entry:
            continue
        if find_placement_in_chain(db, entry.referrer_id, entry.user_id, entry.matrix_level, on_bonus_callback):
            db.query(HoldingPool).filter(HoldingPool.id == eid).delete()
            count += 1
        db.commit()
    return count
