"""
FastAPI приложение: симуляция матричного маркетинга.
90% в сеть, 10% проекту. Авторизация, личный кабинет, реферальные ссылки.
"""

import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db, engine, Base, SessionLocal
from sqlalchemy import text
from app.models import User, UserMatrix, MatrixPosition, Transaction, HoldingPool, WithdrawalRequest, SupportRequest, DepositInvoice
from app.config import (
    SYSTEM_USER_ID,
    MATRIX_PRICES,
    ROOT_USERNAME,
    ROOT_PASSWORD,
    USDT_WALLET_TRC20,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_BOT_USERNAME,
    BOT_ON_START_SECRET,
    WEBAPP_BASE_URL,
    CRYPTOCLOUD_API_KEY,
    CRYPTOCLOUD_SHOP_ID,
    CRYPTOCLOUD_SECRET,
    CRYPTOCLOUD_POS_LINK,
    ALLOWED_REGISTER_WITHOUT_REF_TELEGRAM_ID,
)
from app.auth import verify_password, create_access_token, decode_access_token, hash_password
from app.telegram_webapp import get_telegram_user
from app import services
from app.schemas import (
    RegisterRequest,
    LoginRequest,
    TelegramAuthRequest,
    TelegramIdAuthRequest,
    BotOnStartRequest,
    UserResponse,
    UserMatrixResponse,
    MatrixDetailResponse,
    PurchaseRequest,
    AddFundsRequest,
    DepositCreateRequest,
    DepositCreateResponse,
    TreeResponse,
    StatsResponse,
    SupportCreateRequest,
    WithdrawalCreateRequest,
)
from app.events import get_recent_events, log as event_log
from app.services import ReferralRequiredError
import httpx
import jwt as pyjwt

security = HTTPBearer(auto_error=False)

CRYPTOCLOUD_API_URL = "https://api.cryptocloud.plus/v2/invoice/create"

app = FastAPI(title="Matrix Marketing Simulator", version="1.0")

# CORS: фронт может быть на другом домене (например Beget)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Монтируем статику для фронтенда
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _migrate_users_table():
    """Добавить колонки в users при необходимости (миграция со старых БД)."""
    with engine.connect() as conn:
        for col, spec in [
            ("password_hash", "VARCHAR(255)"),
            ("referral_code", "VARCHAR(32)"),
            ("telegram_id", "INTEGER"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {spec}"))
                conn.commit()
            except Exception as e:
                msg = str(e).lower()
                # SQLite: duplicate column name / PostgreSQL: duplicate column
                if "duplicate column" in msg:
                    conn.rollback()
                else:
                    raise


def _ensure_system_user(db: Session) -> None:
    """Создать системного пользователя для комиссии проекта, если ещё нет."""
    if db.query(User).filter(User.id == SYSTEM_USER_ID).first() is None:
        sys_user = User(
            id=SYSTEM_USER_ID,
            username="__SYSTEM__",
            referrer_id=None,
            balance=0.0,
            is_active=True,
        )
        db.add(sys_user)
        db.commit()


def _ensure_root_user(db: Session) -> None:
    """Создать или обновить тестового пользователя root/root с реферальным кодом."""
    root = db.query(User).filter(User.username == ROOT_USERNAME).first()
    if root is not None:
        if root.password_hash is None or root.referral_code is None:
            if root.password_hash is None:
                root.password_hash = hash_password(ROOT_PASSWORD)
            if root.referral_code is None:
                root.referral_code = services._unique_referral_code(db)
            db.commit()
        return
    ref_code = services._unique_referral_code(db)
    root = User(
        username=ROOT_USERNAME,
        password_hash=hash_password(ROOT_PASSWORD),
        referral_code=ref_code,
        referrer_id=None,
        balance=0.0,
        is_active=True,
    )
    db.add(root)
    db.commit()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    subject = decode_access_token(credentials.credentials)
    if not subject:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    try:
        user_id = int(subject)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = services.get_user_by_id(db, user_id)
    if not user or user.id == SYSTEM_USER_ID or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def require_root(current_user: User) -> None:
    if current_user.username != ROOT_USERNAME:
        raise HTTPException(status_code=403, detail="Admin only")


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    _migrate_users_table()
    db = SessionLocal()
    try:
        _ensure_system_user(db)
        _ensure_root_user(db)
    finally:
        db.close()

    # Запуск бота в том же процессе (на Railway): при /start запись в БД напрямую, без HTTP
    if TELEGRAM_BOT_TOKEN:
        try:
            import bot
            def _bot_on_start(telegram_id, username, first_name, last_name, referrer_telegram_id):
                db_session = SessionLocal()
                try:
                    _ensure_system_user(db_session)
                    services.ensure_telegram_user(
                        db_session,
                        telegram_id=telegram_id,
                        username_from_tg=username,
                        referrer_telegram_id=referrer_telegram_id,
                    )
                finally:
                    db_session.close()
            bot.set_on_start_db_callback(_bot_on_start)
            t = threading.Thread(target=bot.run_bot, daemon=True)
            t.start()
            print("[startup] Telegram bot started (same process, DB write on /start)")
        except Exception as e:
            import traceback
            print(f"[startup] Telegram bot failed to start: {e}")
            traceback.print_exc()
    else:
        print("[startup] Telegram bot NOT started: TELEGRAM_BOT_TOKEN not set in Variables")


@app.get("/")
def index():
    """Главная страница — фронтенд."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Matrix Marketing API", "docs": "/docs"}


@app.get("/config.js")
def serve_config_js():
    """Отдаёт config.js с корня (для относительного script src="config.js")."""
    path = static_dir / "config.js"
    if path.exists():
        return FileResponse(path, media_type="application/javascript")
    raise HTTPException(404)


# --- API ---

@app.post("/api/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    _ensure_system_user(db)
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Username already exists")
    referrer_id = data.referrer_id if (data.referrer_id and data.referrer_id != 0) else None
    if data.referral_code:
        ref_user = services.get_user_by_referral_code(db, data.referral_code.strip())
        if not ref_user or ref_user.id == SYSTEM_USER_ID:
            raise HTTPException(400, "Invalid referral code")
        referrer_id = ref_user.id
    if referrer_id and (referrer_id == SYSTEM_USER_ID or not db.query(User).filter(User.id == referrer_id).first()):
        raise HTTPException(400, "Referrer not found")
    if not data.levels:
        raise HTTPException(400, "At least one level required")
    for level in data.levels:
        if level not in (1, 2, 3, 4):
            raise HTTPException(400, "Level must be 1, 2, 3 or 4")
    try:
        user = services.register_user(db, data.username, data.password, referrer_id, data.levels)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return UserResponse.model_validate(user)


# --- Авторизация и личный кабинет ---

@app.post("/api/auth/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """Логин по паролю (для root в браузере). Основная авторизация — через Telegram."""
    user = db.query(User).filter(User.username == data.username).first()
    if not user or user.id == SYSTEM_USER_ID or not user.password_hash:
        raise HTTPException(401, "Invalid username or password")
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    token = create_access_token(str(user.id))
    return {"access_token": token, "token_type": "bearer", "user": UserResponse.model_validate(user)}


@app.post("/api/auth/telegram")
def auth_telegram(data: TelegramAuthRequest, db: Session = Depends(get_db)):
    """
    Авторизация по Telegram Web App initData.
    Пускаем только если пользователь уже есть в БД (записан при /start в боте).
    Если telegram_id нет в БД — не создаём, не пускаем (403).
    """
    print("[api] /api/auth/telegram — запрос (init_data длина:", len(data.init_data or ""), ")")
    if not TELEGRAM_BOT_TOKEN:
        print("[api] /api/auth/telegram — 503: TELEGRAM_BOT_TOKEN не задан")
        raise HTTPException(503, "Telegram auth is not configured")
    tg_user = get_telegram_user(data.init_data, TELEGRAM_BOT_TOKEN)
    if not tg_user:
        print("[api] /api/auth/telegram — 401: невалидный или просроченный initData")
        raise HTTPException(401, "Invalid or expired Telegram initData")
    telegram_id = tg_user.get("id")
    if not telegram_id:
        print("[api] /api/auth/telegram — 401: в initData нет id пользователя")
        raise HTTPException(401, "Telegram user id missing")
    print(f"[api] /api/auth/telegram — из initData telegram_id={telegram_id}")
    user = services.get_user_by_telegram_id(db, telegram_id)
    if not user:
        print(f"[api] /api/auth/telegram — 403: пользователь telegram_id={telegram_id} не найден в БД (нужна реферальная ссылка или нажми Start в боте)")
        raise HTTPException(
            403,
            detail={
                "code": "referral_required",
                "message": "Для входа нужна реферальная ссылка. Перейдите по ссылке пригласившего вас человека, затем нажмите «Старт» в боте и откройте приложение.",
            },
        )
    if not user.is_active:
        print(f"[api] /api/auth/telegram — 403: пользователь id={user.id} отключён")
        raise HTTPException(403, "Account disabled")
    token = create_access_token(str(user.id))
    print(f"[api] /api/auth/telegram — успех: user_id={user.id} telegram_id={telegram_id}")
    return {"access_token": token, "token_type": "bearer", "user": UserResponse.model_validate(user)}


@app.post("/api/auth/telegram-id")
def auth_telegram_id(data: TelegramIdAuthRequest, db: Session = Depends(get_db)):
    """
    Авторизация по telegram_id из URL (?tg_id=...&ref=...).
    Если пользователь уже есть в БД — выдаём JWT. Если нет — создаём (как при /start): telegram_id,
    referrer по ref, проверка на самозапись; затем выдаём JWT.
    """
    _ensure_system_user(db)
    user = services.get_user_by_telegram_id(db, data.telegram_id)
    if not user:
        try:
            user = services.ensure_telegram_user(
                db,
                telegram_id=data.telegram_id,
                username_from_tg=None,
                referrer_telegram_id=data.referrer_telegram_id,
            )
            print(f"[api] /api/auth/telegram-id — создан пользователь telegram_id={data.telegram_id} user_id={user.id}")
        except ReferralRequiredError as e:
            print(f"[api] /api/auth/telegram-id — 403: регистрация без реферальной ссылки (telegram_id={data.telegram_id})")
            raise HTTPException(403, detail={"code": "referral_required", "message": str(e)})
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    token = create_access_token(str(user.id))
    return {"access_token": token, "token_type": "bearer", "user": UserResponse.model_validate(user)}


@app.post("/api/bot/on-start")
def bot_on_start(
    data: BotOnStartRequest,
    db: Session = Depends(get_db),
    x_bot_secret: str | None = Header(None, alias="X-Bot-Secret"),
):
    """
    Вызывается ботом при /start: записываем пользователя в БД по telegram_id.
    Если такой telegram_id уже есть — ничего не делаем, просто пропускаем.
    При открытии веб-приложения пользователь авторизуется по initData (telegram_id уже в БД).
    """
    # Секрет принимаем из заголовка X-Bot-Secret или из тела bot_secret (если прокси режет заголовки)
    secret_from_header = x_bot_secret
    secret_from_body = getattr(data, "bot_secret", None) or (data.model_dump().get("bot_secret") if data else None)
    received_secret = secret_from_header or secret_from_body
    if not BOT_ON_START_SECRET:
        print("[api] /api/bot/on-start — отказ: на сервере не задан BOT_ON_START_SECRET")
        raise HTTPException(401, "Invalid or missing X-Bot-Secret")
    if not received_secret or received_secret != BOT_ON_START_SECRET:
        print("[api] /api/bot/on-start — отказ: неверный или отсутствующий секрет (header=%s, body=%s)" % (bool(secret_from_header), bool(secret_from_body)))
        raise HTTPException(401, "Invalid or missing X-Bot-Secret")
    print(f"[api] /api/bot/on-start — получен telegram_id={data.telegram_id} username={data.username}")
    _ensure_system_user(db)
    username_from_tg = (data.username or "").strip() or None
    try:
        user = services.ensure_telegram_user(
            db,
            telegram_id=data.telegram_id,
            username_from_tg=username_from_tg,
            referrer_telegram_id=data.referrer_telegram_id,
        )
        print(f"[api] /api/bot/on-start — успех: пользователь в БД id={user.id} telegram_id={user.telegram_id}")
    except ReferralRequiredError as e:
        print(f"[api] /api/bot/on-start — 403: регистрация без реферальной ссылки (telegram_id={data.telegram_id})")
        raise HTTPException(403, detail={"code": "referral_required", "message": str(e)})
    except Exception as e:
        import traceback
        print(f"[api] /api/bot/on-start — исключение при записи в БД: {e}")
        traceback.print_exc()
        raise HTTPException(500, f"Database error: {e}")
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Текущий пользователь, реферальная ссылка (диплинк в бота), кто пригласил и кошелёк для пополнения."""
    if current_user.telegram_id is not None:
        ref_link = f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={current_user.telegram_id}"
    else:
        ref_link = f"https://t.me/{TELEGRAM_BOT_USERNAME}?start=ref_{current_user.referral_code}" if current_user.referral_code else None
    referrer_username = None
    if current_user.referrer_id:
        referrer = db.query(User).filter(User.id == current_user.referrer_id).first()
        if referrer:
            referrer_username = referrer.username
    response = {
        "user": UserResponse.model_validate(current_user),
        "referral_link": ref_link,
        "referral_code": current_user.referral_code,
        "referrer_username": referrer_username,
        "usdt_wallet_trc20": USDT_WALLET_TRC20,
        "is_root": current_user.username == ROOT_USERNAME,
        "deposit_cryptocloud_enabled": bool(CRYPTOCLOUD_POS_LINK or (CRYPTOCLOUD_API_KEY and CRYPTOCLOUD_SHOP_ID)),
        "cryptocloud_pos_link": (CRYPTOCLOUD_POS_LINK or "").strip() or None,
        "cryptocloud_pos_id": _pos_id_from_link(CRYPTOCLOUD_POS_LINK),
    }
    # Для специального пользователя из ALLOWED_REGISTER_WITHOUT_REF_TELEGRAM_ID добавляем агрегированную статистику
    if (
        ALLOWED_REGISTER_WITHOUT_REF_TELEGRAM_ID is not None
        and current_user.telegram_id is not None
        and int(current_user.telegram_id) == int(ALLOWED_REGISTER_WITHOUT_REF_TELEGRAM_ID)
    ):
        response["admin_summary"] = _get_admin_summary(db)
    return response


@app.get("/api/me/matrices-full")
def me_matrices_full(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Матрицы текущего пользователя."""
    return _get_matrices_full_response(db, current_user.id)


def _get_matrices_full_response(db: Session, user_id: int):
    user = services.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    matrices = services.get_user_matrices(db, user_id, active_only=True)
    by_level = {m.matrix_level: m for m in matrices}
    result_matrices = []
    for level in (1, 2, 3, 4):
        # Уровень по конкретной матрице: 1 + количество закрытых матриц этого уровня
        closed_count_level = (
            db.query(func.count(UserMatrix.id))
            .filter(
                UserMatrix.user_id == user.id,
                UserMatrix.matrix_level == level,
                UserMatrix.status == "closed",
            )
            .scalar()
            or 0
        )
        user_level_for_matrix = 1 + int(closed_count_level)
        m = by_level.get(level)
        if not m:
            result_matrices.append({
                "level": level,
                "matrix_id": None,
                "positions": [{"position": p, "username": None} for p in range(1, 8)],
                "user_level": user_level_for_matrix,
            })
            continue
        data = services.get_matrix_with_positions(db, m.id)
        if not data:
            result_matrices.append({"level": level, "matrix_id": m.id, "positions": [], "user_level": user_level_for_matrix})
            continue
        owner_id = data["matrix"].user_id
        positions_out = []
        for p in data["positions"]:
            if p.position >= 2 and p.user_id == owner_id:
                positions_out.append({"position": p.position, "username": None})
                continue
            u = db.query(User).filter(User.id == p.user_id).first()
            name = (u.username if u else None) or f"id:{p.user_id}"
            positions_out.append({"position": p.position, "username": name})
        result_matrices.append({"level": level, "matrix_id": m.id, "positions": positions_out, "user_level": user_level_for_matrix})

    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "balance": user.balance,
            "total_earned": getattr(user, "total_earned", 0.0),
        },
        "matrices": result_matrices,
    }


def _get_admin_summary(db: Session):
    """Агрегированная статистика по проекту для владельца (по telegram_id из ALLOWED_REGISTER_WITHOUT_REF_TELEGRAM_ID)."""
    # Всего пользователей (без системного)
    total_users = (
        db.query(func.count(User.id))
        .filter(User.id != SYSTEM_USER_ID)
        .scalar()
        or 0
    )
    # Активные пользователи: есть хотя бы одна купленная матрица
    active_users = (
        db.query(func.count(func.distinct(UserMatrix.user_id)))
        .filter(UserMatrix.user_id != SYSTEM_USER_ID)
        .scalar()
        or 0
    )
    # Сколько всего поступило средств от пользователей: суммарный положительный приход по транзакциям (кроме системного пользователя)
    total_incoming = (
        db.query(func.coalesce(func.sum(Transaction.amount), 0.0))
        .filter(
            Transaction.amount > 0,
            Transaction.user_id != SYSTEM_USER_ID,
        )
        .scalar()
        or 0.0
    )
    # Сумма, которую нужно будет выплатить, если все пользователи выведут всё: суммарный текущий баланс всех обычных пользователей
    total_liability = (
        db.query(func.coalesce(func.sum(User.balance), 0.0))
        .filter(User.id != SYSTEM_USER_ID)
        .scalar()
        or 0.0
    )
    return {
        "total_incoming": float(total_incoming),
        "total_users": int(total_users),
        "active_users": int(active_users),
        "total_liability": float(total_liability),
    }


@app.post("/api/me/purchase")
def me_purchase(data: PurchaseRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_id = current_user.id
    user = services.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if not data.levels:
        raise HTTPException(400, "At least one level required")
    for level in data.levels:
        if level not in (1, 2, 3, 4):
            raise HTTPException(400, "Level must be 1, 2, 3 or 4")
    levels_sorted = sorted(set(l for l in data.levels if l in (1, 2, 3, 4)))
    if not levels_sorted or not services._can_purchase_levels(db, user_id, levels_sorted):
        raise HTTPException(400, "Purchase order required: M2 needs M1, M3 needs M1+M2, M4 needs M1+M2+M3")
    total = sum(MATRIX_PRICES.get(l, 0) for l in data.levels)
    if user.balance < total:
        raise HTTPException(400, f"Insufficient balance. Need ${total}, have ${user.balance}")
    ok = services.purchase_matrices(db, user_id, data.levels)
    if not ok:
        raise HTTPException(400, "Purchase failed")
    event_log(f"User {user.username} (id={user_id}) докупил матрицы M{data.levels}")
    return {"ok": True, "user": UserResponse.model_validate(services.get_user_by_id(db, user_id))}


@app.get("/api/me/transactions")
def me_transactions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """История транзакций текущего пользователя."""
    txs = db.query(Transaction).filter(Transaction.user_id == current_user.id).order_by(Transaction.created_at.desc()).limit(200).all()
    return {"transactions": [{"id": t.id, "amount": t.amount, "type": t.type, "description": t.description, "created_at": (t.created_at.isoformat() if t.created_at else "")} for t in txs]}


@app.get("/api/me/referrals")
def me_referrals(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Пользователи, зарегистрированные по моей реферальной ссылке."""
    refs = db.query(User).filter(User.referrer_id == current_user.id, User.id != SYSTEM_USER_ID).order_by(User.created_at.desc()).all()
    return {"referrals": [{"id": u.id, "username": u.username, "created_at": (u.created_at.isoformat() if u.created_at else "")} for u in refs]}


@app.post("/api/me/support")
def me_support(data: SupportCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    req = SupportRequest(user_id=current_user.id, telegram_username=data.telegram_username.strip(), message=data.message)
    db.add(req)
    db.commit()
    return {"ok": True, "message": "Request sent"}


@app.post("/api/me/withdrawal")
def me_withdrawal(data: WithdrawalCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    amount = round(float(data.amount), 2)
    if amount < 10:
        raise HTTPException(400, "Минимальная сумма вывода — 10$")
    if current_user.balance < amount:
        raise HTTPException(400, f"Недостаточно средств. На балансе ${current_user.balance:.2f}")
    req = WithdrawalRequest(user_id=current_user.id, amount=amount, trc20_wallet=data.trc20_wallet.strip(), status="pending")
    db.add(req)
    db.commit()
    db.refresh(req)
    ok = services.withdraw_from_balance(
        db, current_user.id, amount, "withdrawal",
        f"Заявка на вывод #{req.id} (TRC20)",
    )
    if not ok:
        raise HTTPException(400, "Не удалось списать средства")
    return {"ok": True, "message": "Заявка создана", "id": req.id}


def _build_pos_deposit_link(amount_usd: float, order_id: str, pos_link: str) -> str:
    """Ссылка на постоянную страницу оплаты (POS): сумма из формы и order_id в URL для подстановки на странице оплаты."""
    from urllib.parse import urlencode
    amount_f = round(float(amount_usd), 2)
    amount_int = int(round(amount_usd, 0))
    params = {
        "order_id": order_id,
        "currency": "USD",
        "amount": amount_f,      # сумма как число (для подстановки в форму)
        "amount_usd": amount_f,
        "sum": amount_int if amount_int > 0 else amount_f,
    }
    return f"{pos_link}?{urlencode(params)}"


# Допустимый префикс для POS-ссылки (без доверия к клиенту не редиректим на левые домены)
CRYPTOCLOUD_POS_ALLOWED_PREFIX = "https://pay.cryptocloud.plus/"


def _pos_id_from_link(link: str) -> str | None:
    """Извлекает id страницы из ссылки https://pay.cryptocloud.plus/pos/XXX."""
    if not link or "/pos/" not in link:
        return None
    part = link.split("/pos/")[-1].split("?")[0].strip()
    return part if part else None


@app.post("/api/me/deposit/create", response_model=DepositCreateResponse)
def me_deposit_create(data: DepositCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Создать заявку на пополнение через CryptoCloud.
    Конфиг из переменных окружения (как TELEGRAM_BOT_TOKEN): CRYPTOCLOUD_POS_LINK или CRYPTOCLOUD_POS_ID, либо CRYPTOCLOUD_API_KEY и CRYPTOCLOUD_SHOP_ID.
    """
    use_pos = bool(CRYPTOCLOUD_POS_LINK)
    use_api = bool(CRYPTOCLOUD_API_KEY and CRYPTOCLOUD_SHOP_ID)
    if not use_pos and not use_api:
        raise HTTPException(
            503,
            "Пополнение не настроено. Задайте CRYPTOCLOUD_POS_LINK или CRYPTOCLOUD_POS_ID (тест), либо CRYPTOCLOUD_API_KEY и CRYPTOCLOUD_SHOP_ID в переменных окружения.",
        )
    amount_usd = round(float(data.amount), 2)
    if amount_usd < 1 or amount_usd > 10000:
        raise HTTPException(400, "Сумма от 1 до 10000 USD")
    invoice = DepositInvoice(
        user_id=current_user.id,
        amount_usd=amount_usd,
        status="pending",
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    # Шьём в order_id id счёта и Telegram ID пользователя: invoiceId:telegramId
    # Это даёт однозначную привязку к аккаунту Telegram и хорошо видно в кабинете CryptoCloud.
    tg_id = current_user.telegram_id or 0
    order_id = f"{invoice.id}:{int(tg_id)}"

    # При наличии API-ключей создаём счёт через API — тогда order_id гарантированно вернётся в postback.
    # POS не передаёт order_id в postback (CryptoCloud присылает order_id: null), поэтому приоритет у API.
    if use_api:
        payload = {
            "shop_id": CRYPTOCLOUD_SHOP_ID,
            "amount": amount_usd,
            "currency": "USD",
            "order_id": order_id,
        }
        headers = {
            "Authorization": f"Token {CRYPTOCLOUD_API_KEY}",
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(CRYPTOCLOUD_API_URL, json=payload, headers=headers, timeout=15.0)
            body = resp.json() if resp.content else {}
        except Exception as e:
            print(f"[deposit] CryptoCloud API error: {e}")
            raise HTTPException(502, "Ошибка платёжного провайдера")
        if resp.status_code != 200 or body.get("status") != "success":
            err = body.get("result") or body.get("error") or resp.text
            print(f"[deposit] CryptoCloud create failed: {resp.status_code} {err}")
            raise HTTPException(502, "Не удалось создать счёт на оплату")
        result = body.get("result", {})
        uuid_val = result.get("uuid") or ""
        link = result.get("link") or ""
        if not link and uuid_val:
            link = f"https://pay.cryptocloud.plus/{uuid_val.replace('INV-', '')}"
        invoice.invoice_uuid = uuid_val
        db.commit()
        return DepositCreateResponse(
            invoice_id=invoice.id,
            uuid=uuid_val,
            link=link,
            amount_usd=amount_usd,
        )

    if use_pos:
        link = _build_pos_deposit_link(amount_usd, order_id, pos_link=CRYPTOCLOUD_POS_LINK)
        return DepositCreateResponse(
            invoice_id=invoice.id,
            uuid="",
            link=link,
            amount_usd=amount_usd,
        )

    raise HTTPException(503, "Пополнение не настроено")


def _cryptocloud_verify_token(token: str | None) -> bool:
    """Проверка JWT от CryptoCloud (HS256, секрет CRYPTOCLOUD_SECRET)."""
    if not token or not isinstance(token, str):
        return False
    token = token.strip()
    if not token or not CRYPTOCLOUD_SECRET:
        return False
    try:
        pyjwt.decode(token, CRYPTOCLOUD_SECRET, algorithms=["HS256"])
        return True
    except pyjwt.PyJWTError:
        return False


async def _parse_postback_body(request: Request) -> dict:
    """Парсим тело: сначала пробуем JSON (часто приходит с некорректным Content-Type), затем form-urlencoded."""
    import json
    from urllib.parse import parse_qs
    try:
        body = await request.body()
    except Exception:
        return {}
    if not body:
        return {}
    # Сначала пробуем JSON (даже если Content-Type не application/json)
    try:
        data = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    # Иначе form-urlencoded
    try:
        parsed = parse_qs(body.decode("utf-8") if isinstance(body, bytes) else body, keep_blank_values=True)
        return {k: (v[0] if isinstance(v, list) and v else v) for k, v in parsed.items()}
    except Exception:
        return {}


@app.get("/api/payments/cryptocloud/postback")
def cryptocloud_postback_get():
    """
    При открытии ссылки в браузере (GET) — просто подтверждаем, что URL правильный.
    Уведомления от CryptoCloud приходят методом POST, не GET.
    """
    return {
        "ok": True,
        "message": "CryptoCloud postback endpoint. Notifications are sent here via POST after payment; opening this URL in a browser (GET) does nothing. URL is correct.",
    }


@app.post("/api/payments/cryptocloud/postback")
async def cryptocloud_postback(request: Request, db: Session = Depends(get_db)):
    """
    Webhook от CryptoCloud после успешной оплаты.
    CryptoCloud вызывает этот URL методом POST (не GET). При открытии в браузере сработает GET и вернётся подсказка.
    """
    print("[postback] POST request received from CryptoCloud")
    data = await _parse_postback_body(request)
    if not data:
        print("[postback] empty or invalid body — check Content-Type and request format")
        raise HTTPException(400, "Invalid body")
    status = (data.get("status") or "").strip().lower() if isinstance(data.get("status"), str) else data.get("status")
    order_id = data.get("order_id")
    # order_id теперь всегда в формате "<invoice_id>:<user_id>".
    # Если CryptoCloud присылает order_id только сверху — используем его, иначе пробуем взять из invoice_info.
    if (order_id is None or order_id in ("", "null")) and isinstance(data.get("invoice_info"), dict):
        order_id = data["invoice_info"].get("order_id")
    if (order_id is None or order_id in ("", "null")) and isinstance(data.get("invoice_info"), str):
        try:
            import json
            info = json.loads(data["invoice_info"])
            if isinstance(info, dict):
                order_id = info.get("order_id")
        except Exception:
            pass
    token = data.get("token")
    # Лог без токена для отладки (в Railway видно, что пришло)
    _log_data = {k: v for k, v in data.items() if k != "token"}
    print(f"[postback] received: status={status!r} order_id={order_id!r} keys={list(_log_data.keys())}")
    # Для отладки: что именно пришло (без token). Если в логах нет этой строки — POST от CryptoCloud не доходит.
    import json as _json
    try:
        _preview = _json.dumps(_log_data, ensure_ascii=False)[:500]
        print(f"[postback] payload preview: {_preview}")
    except Exception:
        print(f"[postback] payload keys: {list(_log_data.keys())}")
    if CRYPTOCLOUD_SECRET and token and not _cryptocloud_verify_token(token):
        print("[postback] invalid token")
        raise HTTPException(401, "Invalid token")

    if not order_id:
        print("[postback] order_id missing — без order_id невозможно однозначно определить пользователя")
        return {"ok": True, "message": "order_id missing, cannot credit"}

    # order_id должен быть в формате "<invoice_id>:<telegram_id>"
    raw_order_id = str(order_id).strip()
    try:
        invoice_part, user_part = raw_order_id.split(":", 1)
        our_invoice_id = int(invoice_part)
        expected_telegram_id = int(user_part)
    except Exception:
        print(f"[postback] invalid order_id format (expected 'invoiceId:telegramId'): {raw_order_id!r}")
        return {"ok": True, "message": "invalid order_id format"}

    invoice = db.query(DepositInvoice).filter(DepositInvoice.id == our_invoice_id).first()
    if not invoice:
        print(f"[postback] DepositInvoice id={our_invoice_id} not found in DB (from order_id={raw_order_id!r})")
        return {"ok": True, "message": "invoice not found"}

    # Дополнительная страховка: проверяем, что telegram_id владельца совпадает с тем, что был зашит в order_id
    owner = db.query(User).filter(User.id == invoice.user_id).first()
    owner_tg_id = int(owner.telegram_id or 0) if owner else 0
    if expected_telegram_id and owner_tg_id != expected_telegram_id:
        print(
            f"[postback] telegram_id mismatch for invoice id={our_invoice_id}: "
            f"invoice.user_id={invoice.user_id} owner.telegram_id={owner_tg_id} expected_tg_id={expected_telegram_id}"
        )
        return {"ok": True, "message": "user mismatch, not credited"}

    # Зачисление только владельцу счёта
    print(f"[postback] found invoice id={invoice.id} user_id={invoice.user_id} amount_usd={invoice.amount_usd}")
    if invoice.status == "paid":
        return {"ok": True, "message": "Already processed"}
    # Успех: status == "success" на верхнем уровне или invoice_info.invoice_status == "success" / invoice_info.status == "paid"
    def _norm(s):
        return (s or "").strip().lower() if isinstance(s, str) else s
    is_success = _norm(status) == "success"
    if not is_success and isinstance(data.get("invoice_info"), dict):
        inv_info = data["invoice_info"]
        if _norm(inv_info.get("invoice_status")) == "success" or _norm(inv_info.get("status")) == "paid":
            is_success = True
    if not is_success:
        return {"ok": True, "message": "Status not success, ignored"}
    amount_usd = float(invoice.amount_usd)
    if amount_usd <= 0:
        print(f"[postback] skip: amount_usd={amount_usd} <= 0")
        return {"ok": True, "message": "Invalid amount"}
    user_id = int(invoice.user_id)  # владелец счёта (тот, кто нажал «Создать счёт на оплату»)
    print(f"[postback] crediting invoice owner user_id={user_id} amount={amount_usd}")
    ok = services.add_funds(db, user_id, amount_usd, description="Пополнение CryptoCloud")
    if not ok:
        print(f"[postback] add_funds failed user_id={user_id}")
        raise HTTPException(500, "User not found")
    db.refresh(invoice)
    invoice.status = "paid"
    invoice.paid_at = datetime.utcnow()
    db.commit()
    event_log(f"Deposit CryptoCloud: user_id={user_id} amount={amount_usd} invoice_id={invoice.id}")
    print(f"[postback] credited user_id={user_id} amount={amount_usd}")
    return {"ok": True, "message": "Payment credited"}


@app.get("/api/deposit-config-check")
def deposit_config_check():
    """Проверка, видит ли сервер переменные для пополнения (как TELEGRAM_BOT_TOKEN). Без секретов."""
    return {
        "deposit_configured": bool(CRYPTOCLOUD_POS_LINK or (CRYPTOCLOUD_API_KEY and CRYPTOCLOUD_SHOP_ID)),
        "pos_configured": bool(CRYPTOCLOUD_POS_LINK),
        "api_configured": bool(CRYPTOCLOUD_API_KEY and CRYPTOCLOUD_SHOP_ID),
    }


@app.post("/api/admin/reset-db")
def admin_reset_db(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Полностью обнулить БД, оставив только системного пользователя и root (баланс root = 0)."""
    require_root(current_user)
    root = db.query(User).filter(User.username == ROOT_USERNAME).first()
    if not root:
        raise HTTPException(500, "Root user not found")
    root_id = root.id
    db.query(WithdrawalRequest).delete()
    db.query(SupportRequest).delete()
    db.query(DepositInvoice).delete()
    db.query(Transaction).delete()
    db.query(MatrixPosition).delete()
    db.query(UserMatrix).delete()
    db.query(HoldingPool).delete()
    db.query(User).filter(User.id.notin_([SYSTEM_USER_ID, root_id])).delete(synchronize_session=False)
    root.balance = 0.0
    db.commit()
    return {"ok": True, "message": "База обнулена, сохранён только root"}


@app.post("/api/admin/add-funds/{user_id}")
def admin_add_funds(user_id: int, data: AddFundsRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_root(current_user)
    if user_id <= 0 or user_id == SYSTEM_USER_ID:
        raise HTTPException(400, "Invalid user")
    if data.amount <= 0 or data.amount > 1_000_000:
        raise HTTPException(400, "Invalid amount")
    ok = services.add_funds(db, user_id, data.amount)
    if not ok:
        raise HTTPException(404, "User not found")
    return {"ok": True, "user": UserResponse.model_validate(services.get_user_by_id(db, user_id))}


@app.get("/api/user/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = services.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return UserResponse.model_validate(user)


@app.get("/api/users")
def list_users(db: Session = Depends(get_db)):
    users = services.get_all_users(db)
    return [UserResponse.model_validate(u) for u in users if u.id != SYSTEM_USER_ID]


@app.get("/api/user/{user_id}/matrices")
def get_user_matrices(user_id: int, active_only: bool = False, db: Session = Depends(get_db)):
    user = services.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    matrices = services.get_user_matrices(db, user_id, active_only=active_only)
    return [UserMatrixResponse.model_validate(m) for m in matrices]


@app.get("/api/user/{user_id}/matrices-full")
def get_user_matrices_full(user_id: int, db: Session = Depends(get_db)):
    """Все 4 матрицы пользователя с позициями и именами для отображения на фронте."""
    user = services.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    matrices = services.get_user_matrices(db, user_id, active_only=True)
    by_level = {m.matrix_level: m for m in matrices}
    result_matrices = []
    for level in (1, 2, 3, 4):
        m = by_level.get(level)
        if not m:
            result_matrices.append({
                "level": level,
                "matrix_id": None,
                "positions": [{"position": p, "username": None} for p in range(1, 8)],
            })
            continue
        data = services.get_matrix_with_positions(db, m.id)
        if not data:
            result_matrices.append({"level": level, "matrix_id": m.id, "positions": []})
            continue
        owner_id = data["matrix"].user_id
        positions_out = []
        for p in data["positions"]:
            if p.position >= 2 and p.user_id == owner_id:
                positions_out.append({"position": p.position, "username": None})
                continue
            u = db.query(User).filter(User.id == p.user_id).first()
            name = (u.username if u else None) or f"id:{p.user_id}"
            positions_out.append({
                "position": p.position,
                "username": name,
            })
        result_matrices.append({
            "level": level,
            "matrix_id": m.id,
            "positions": positions_out,
        })
    return {
        "user": {"id": user.id, "username": user.username, "balance": user.balance},
        "matrices": result_matrices,
    }


@app.get("/api/matrix/{matrix_id}", response_model=MatrixDetailResponse)
def get_matrix(matrix_id: int, db: Session = Depends(get_db)):
    data = services.get_matrix_with_positions(db, matrix_id)
    if not data:
        raise HTTPException(404, "Matrix not found")
    owner_id = data["matrix"].user_id
    positions_out = []
    for p in data["positions"]:
        if p.position >= 2 and p.user_id == owner_id:
            positions_out.append({
                "id": p.id,
                "matrix_id": p.matrix_id,
                "user_id": p.user_id,
                "position": p.position,
                "username": None,
                "created_at": p.created_at,
            })
            continue
        u = db.query(User).filter(User.id == p.user_id).first()
        positions_out.append({
            "id": p.id,
            "matrix_id": p.matrix_id,
            "user_id": p.user_id,
            "position": p.position,
            "username": u.username if u else None,
            "created_at": p.created_at,
        })
    return MatrixDetailResponse(
        matrix=UserMatrixResponse.model_validate(data["matrix"]),
        positions=[MatrixPositionResponse(**x) for x in positions_out],
    )


@app.get("/api/user/{user_id}/tree", response_model=TreeResponse)
def get_tree(user_id: int, db: Session = Depends(get_db)):
    tree = services.get_referral_tree(db, user_id)
    if not tree:
        raise HTTPException(404, "User not found")
    return TreeResponse(**tree)


@app.post("/api/user/{user_id}/purchase")
def purchase(user_id: int, data: PurchaseRequest, db: Session = Depends(get_db)):
    user = services.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if not data.levels:
        raise HTTPException(400, "At least one level required")
    for level in data.levels:
        if level not in (1, 2, 3, 4):
            raise HTTPException(400, "Level must be 1, 2, 3 or 4")
    levels_sorted = sorted(set(l for l in data.levels if l in (1, 2, 3, 4)))
    if not levels_sorted:
        raise HTTPException(400, "No valid levels (1-4)")
    if not services._can_purchase_levels(db, user_id, levels_sorted):
        raise HTTPException(
            400,
            "Purchase order required: M2 needs M1, M3 needs M1+M2, M4 needs M1+M2+M3. Buy lower levels first.",
        )
    total = sum(MATRIX_PRICES.get(l, 0) for l in data.levels)
    if user.balance < total:
        raise HTTPException(400, f"Insufficient balance. Need ${total}, have ${user.balance}")
    ok = services.purchase_matrices(db, user_id, data.levels)
    if not ok:
        raise HTTPException(400, "Purchase failed")
    event_log(f"User {user.username} (id={user_id}) докупил матрицы M{data.levels}")
    return {"ok": True, "user": UserResponse.model_validate(services.get_user_by_id(db, user_id))}


@app.post("/api/user/{user_id}/add-funds")
def add_funds(user_id: int, data: AddFundsRequest, db: Session = Depends(get_db)):
    if user_id <= 0 or user_id == SYSTEM_USER_ID:
        raise HTTPException(400, "Invalid user")
    if data.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    if data.amount > 1_000_000:
        raise HTTPException(400, "Amount too large (max 1_000_000 for safety)")
    ok = services.add_funds(db, user_id, data.amount)
    if not ok:
        raise HTTPException(404, "User not found")
    return {"ok": True, "user": UserResponse.model_validate(services.get_user_by_id(db, user_id))}


@app.get("/api/events")
def events(limit: int = 50):
    return {"events": get_recent_events(limit)}


@app.get("/api/admin/verify")
def admin_verify(db: Session = Depends(get_db)):
    """Проверка целостности: баланс каждого пользователя = сумма его транзакций (в т.ч. системный)."""
    issues = []
    users = db.query(User).all()
    for u in users:
        tx_sum = db.query(func.sum(Transaction.amount)).filter(Transaction.user_id == u.id).scalar() or 0
        tx_sum_f = float(tx_sum)
        balance = round(float(u.balance or 0), 2)
        if abs(balance - tx_sum_f) > 0.01:
            issues.append(f"User {u.id} {u.username}: balance={balance}, tx_sum={tx_sum_f}")
    return {"ok": len(issues) == 0, "issues": issues}


@app.post("/api/admin/process-holding-pool")
def process_holding_pool(db: Session = Depends(get_db)):
    count = services.process_holding_pool(db)
    event_log(f"Обработан пул ожидания: размещено {count} записей")
    return {"processed": count}


@app.get("/api/stats", response_model=StatsResponse)
def stats(db: Session = Depends(get_db)):
    total_users = db.query(User).filter(User.id != SYSTEM_USER_ID).count()
    total_tx = db.query(Transaction).count()
    bonus_sum = db.query(func.sum(Transaction.amount)).filter(
        Transaction.type == "matrix_bonus"
    ).scalar() or 0
    admin_sum = db.query(func.sum(Transaction.amount)).filter(
        Transaction.type == "admin_fee", Transaction.user_id == SYSTEM_USER_ID
    ).scalar() or 0
    pool_count = db.query(HoldingPool).count()
    return StatsResponse(
        total_users=total_users,
        total_transactions=total_tx,
        total_matrix_bonus_paid=float(bonus_sum),
        total_admin_fee=float(admin_sum),
        holding_pool_count=pool_count,
    )


