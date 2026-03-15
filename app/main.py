"""
FastAPI приложение: симуляция матричного маркетинга.
90% в сеть, 10% проекту. Авторизация, личный кабинет, реферальные ссылки.
"""

import os
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
                if "duplicate column name" in str(e).lower():
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
        print(f"[api] /api/auth/telegram — 403: пользователь telegram_id={telegram_id} не найден в БД (сначала нажми Start в боте)")
        raise HTTPException(403, "User not registered. Open the app from the bot (press Start).")
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
        # Пользователь открыл ссылку, но не нажимал /start — создаём с теми данными, что есть (tg_id + ref)
        user = services.ensure_telegram_user(
            db,
            telegram_id=data.telegram_id,
            username_from_tg=None,
            referrer_telegram_id=data.referrer_telegram_id,
        )
        print(f"[api] /api/auth/telegram-id — создан пользователь telegram_id={data.telegram_id} user_id={user.id}")
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
    return {
        "user": UserResponse.model_validate(current_user),
        "referral_link": ref_link,
        "referral_code": current_user.referral_code,
        "referrer_username": referrer_username,
        "usdt_wallet_trc20": USDT_WALLET_TRC20,
        "is_root": current_user.username == ROOT_USERNAME,
        "deposit_cryptocloud_enabled": bool(_resolve_pos_link() or (_env_get("CRYPTOCLOUD_API_KEY") or CRYPTOCLOUD_API_KEY) and (_env_get("CRYPTOCLOUD_SHOP_ID") or CRYPTOCLOUD_SHOP_ID)),
        "cryptocloud_pos_link": ( _resolve_pos_link() or "" ).strip() or None,
        "cryptocloud_pos_id": _pos_id_from_link(_resolve_pos_link()),
    }


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
            positions_out.append({"position": p.position, "username": name})
        result_matrices.append({"level": level, "matrix_id": m.id, "positions": positions_out})
    return {"user": {"id": user.id, "username": user.username, "balance": user.balance}, "matrices": result_matrices}


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
    return {"transactions": [{"id": t.id, "amount": t.amount, "type": t.type, "description": t.description, "created_at": t.created_at.isoformat()} for t in txs]}


@app.get("/api/me/referrals")
def me_referrals(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Пользователи, зарегистрированные по моей реферальной ссылке."""
    refs = db.query(User).filter(User.referrer_id == current_user.id, User.id != SYSTEM_USER_ID).order_by(User.created_at.desc()).all()
    return {"referrals": [{"id": u.id, "username": u.username, "created_at": u.created_at.isoformat()} for u in refs]}


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
    """Ссылка на постоянную страницу оплаты (POS) с параметрами amount, order_id, currency."""
    from urllib.parse import urlencode
    params = {"amount": amount_usd, "order_id": order_id, "currency": "USD"}
    return f"{pos_link}?{urlencode(params)}"


# Допустимый префикс для POS-ссылки (без доверия к клиенту не редиректим на левые домены)
CRYPTOCLOUD_POS_ALLOWED_PREFIX = "https://pay.cryptocloud.plus/"


def _env_get(key: str, alt_keys: list[str] | None = None) -> str:
    """Читаем переменную окружения: точный ключ, затем альтернативы, затем поиск по всем ключам (без учёта регистра и пробелов)."""
    v = (os.environ.get(key) or "").strip()
    if v:
        return v
    for k in alt_keys or []:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    key_upper = key.strip().upper().replace(" ", "")
    for env_key, env_val in os.environ.items():
        if env_key.strip().upper().replace(" ", "") == key_upper and (env_val or "").strip():
            return (env_val or "").strip()
    return ""


def _get_pos_link_from_env() -> str:
    """POS-ссылка только из переменных окружения (при каждом запросе). Поддерживает CRYPTOCLOUD_POS_LINK, CRYPTOCLOUD_POS_ID, CRYPTOCLOUD_POS_URL."""
    link = _env_get("CRYPTOCLOUD_POS_LINK", ["CRYPTOCLOUD_POS_URL"]).rstrip("/")
    if link and link.startswith(CRYPTOCLOUD_POS_ALLOWED_PREFIX):
        return link
    pos_id = _env_get("CRYPTOCLOUD_POS_ID")
    if pos_id:
        safe = "".join(c for c in pos_id if c.isalnum() or c in "-_")
        if safe:
            return f"https://pay.cryptocloud.plus/pos/{safe}"
    return ""


def _pos_id_from_link(link: str) -> str | None:
    """Извлекает id страницы из ссылки https://pay.cryptocloud.plus/pos/XXX."""
    if not link or "/pos/" not in link:
        return None
    part = link.split("/pos/")[-1].split("?")[0].strip()
    return part if part else None


def _resolve_pos_link() -> str:
    """POS-ссылка: при каждом запросе из os.environ (гибкий поиск ключей), иначе из config (загрузка при старте)."""
    link = _get_pos_link_from_env()
    if link:
        return link
    return (CRYPTOCLOUD_POS_LINK or "").strip().rstrip("/")


@app.post("/api/me/deposit/create", response_model=DepositCreateResponse)
def me_deposit_create(data: DepositCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Создать заявку на пополнение через CryptoCloud.
    Конфиг только из переменных окружения: CRYPTOCLOUD_POS_LINK или CRYPTOCLOUD_POS_ID (тест), либо CRYPTOCLOUD_API_KEY и CRYPTOCLOUD_SHOP_ID.
    """
    pos_link = _resolve_pos_link()
    use_pos = bool(pos_link)
    api_key = _env_get("CRYPTOCLOUD_API_KEY") or CRYPTOCLOUD_API_KEY
    shop_id = _env_get("CRYPTOCLOUD_SHOP_ID") or CRYPTOCLOUD_SHOP_ID
    use_api = bool(api_key and shop_id)
    print(f"[deposit] use_pos={use_pos} use_api={use_api} (env keys present: CRYPTOCLOUD_POS_LINK={bool(_env_get('CRYPTOCLOUD_POS_LINK'))} CRYPTOCLOUD_POS_ID={bool(_env_get('CRYPTOCLOUD_POS_ID'))})")
    if not use_pos and not use_api:
        raise HTTPException(
            503,
            "Пополнение не настроено. Задайте в переменных окружения: CRYPTOCLOUD_POS_LINK или CRYPTOCLOUD_POS_ID (тест), либо CRYPTOCLOUD_API_KEY и CRYPTOCLOUD_SHOP_ID.",
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
    order_id = str(invoice.id)

    if use_pos:
        link = _build_pos_deposit_link(amount_usd, order_id, pos_link=pos_link)
        return DepositCreateResponse(
            invoice_id=invoice.id,
            uuid="",
            link=link,
            amount_usd=amount_usd,
        )

    payload = {
        "shop_id": shop_id,
        "amount": amount_usd,
        "currency": "USD",
        "order_id": order_id,
    }
    headers = {
        "Authorization": f"Token {api_key}",
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


@app.post("/api/payments/cryptocloud/postback")
async def cryptocloud_postback(request: Request, db: Session = Depends(get_db)):
    """
    Webhook от CryptoCloud после успешной оплаты инвойса.
    В настройках проекта CryptoCloud укажите URL: {WEBAPP_BASE_URL}/api/payments/cryptocloud/postback
    и формат POSTBACK: JSON.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(data, dict):
        raise HTTPException(400, "Invalid body")
    status = data.get("status")
    invoice_id_raw = data.get("invoice_id")
    order_id = data.get("order_id")
    token = data.get("token")
    if not order_id:
        raise HTTPException(400, "Missing order_id")
    if CRYPTOCLOUD_SECRET and not _cryptocloud_verify_token(token):
        raise HTTPException(401, "Invalid token")
    try:
        our_invoice_id = int(order_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid order_id")
    invoice = db.query(DepositInvoice).filter(DepositInvoice.id == our_invoice_id).first()
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if invoice.status == "paid":
        return {"ok": True, "message": "Already processed"}
    if status != "success":
        return {"ok": True, "message": "Status not success, ignored"}
    amount_usd = float(invoice.amount_usd)
    ok = services.add_funds(db, invoice.user_id, amount_usd, description="Пополнение CryptoCloud")
    if not ok:
        raise HTTPException(500, "User not found")
    invoice.status = "paid"
    invoice.paid_at = datetime.utcnow()
    db.commit()
    event_log(f"Deposit CryptoCloud: user_id={invoice.user_id} amount={amount_usd} invoice_id={invoice.id}")
    return {"ok": True, "message": "Payment credited"}


@app.get("/api/deposit-config-check")
def deposit_config_check():
    """Проверка, видит ли сервер переменные для пополнения (без вывода секретов). Для отладки на Railway."""
    pos_from_env = bool(_get_pos_link_from_env())
    pos_from_config = bool((CRYPTOCLOUD_POS_LINK or "").strip())
    api_key_set = bool(_env_get("CRYPTOCLOUD_API_KEY") or CRYPTOCLOUD_API_KEY)
    shop_id_set = bool(_env_get("CRYPTOCLOUD_SHOP_ID") or CRYPTOCLOUD_SHOP_ID)
    return {
        "deposit_configured": pos_from_env or pos_from_config or (api_key_set and shop_id_set),
        "pos_from_env": pos_from_env,
        "pos_from_config": pos_from_config,
        "api_configured": api_key_set and shop_id_set,
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


