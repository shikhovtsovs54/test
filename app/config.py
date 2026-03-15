"""
Константы матричного маркетинга (90% в сеть, 10% проекту).
Все суммы в долларах. Проверка: для каждого уровня
  MATRIX_BONUS_PER_PLACE[L] * 4 == MATRIX_INCOME[L] - REINVEST_CONFIG[L]['cost']
"""
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

import os

MATRIX_PRICES = {
    1: 10,
    2: 20,
    3: 40,
    4: 80,
}

MATRIX_INCOME = {  # Валовой доход при полном заполнении (4 места в последней линии)
    1: 36,
    2: 72,
    3: 144,
    4: 288,
}

# Чистая выплата за 1 место (доход минус реинвест): владелец получает уже за вычетом реинвеста
# M1: 36 - 10 = 26 → 26/4 = 6.50
# M2: 72 - 20 = 52 → 52/4 = 13
# M3: 144 - 40 = 104 → 104/4 = 26
# M4: 288 - 80 = 208 → 208/4 = 52
MATRIX_BONUS_PER_PLACE = {
    1: 6.50,   # (36 - 10) / 4
    2: 13.0,   # (72 - 20) / 4
    3: 26.0,   # (144 - 40) / 4
    4: 52.0,   # (288 - 80) / 4
}

REINVEST_CONFIG = {
    1: {"cost": 10, "matrices": [1]},
    2: {"cost": 20, "matrices": [1, 2]},
    3: {"cost": 40, "matrices": [1, 2, 3]},
    4: {"cost": 80, "matrices": [1, 2, 3, 4]},
}

FULL_PACK_PRICE = 150  # 10+20+40+80
ADMIN_FEE_PERCENT = 10  # 10% проекту
NETWORK_PERCENT = 90    # 90% в сеть

# ID системного пользователя для комиссии проекта
SYSTEM_USER_ID = 1

# Авторизация и реферальные ссылки
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production-matrix-app")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7  # 7 дней

# Тестовый пользователь root (логин/пароль для проверки кабинета)
ROOT_USERNAME = "root"
ROOT_PASSWORD = "root"

# USDT (TRC20) кошелёк для пополнения (показывается в кабинете)
USDT_WALLET_TRC20 = os.environ.get("USDT_WALLET_TRC20", "TYourTRC20WalletAddressHere")

# Telegram Bot (для проверки initData и диплинков)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "YourBot")  # без @, для ссылки t.me/BotUsername
BOT_ON_START_SECRET = os.environ.get("BOT_ON_START_SECRET", "")  # секрет для вызова /api/bot/on-start (бот передаёт в заголовке)
# На Railway подставляется RAILWAY_PUBLIC_DOMAIN (например web-production-5046e.up.railway.app)
# На Render — RENDER_EXTERNAL_URL. Явно задать: WEBAPP_BASE_URL
_def = "https://your-domain.com"
_railway = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
if _railway:
    _def = "https://" + _railway.rstrip("/").replace("https://", "").replace("http://", "")
WEBAPP_BASE_URL = os.environ.get("WEBAPP_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or _def

# CryptoCloud (https://docs.cryptocloud.plus)
CRYPTOCLOUD_API_KEY = os.environ.get("CRYPTOCLOUD_API_KEY", "")
CRYPTOCLOUD_SHOP_ID = os.environ.get("CRYPTOCLOUD_SHOP_ID", "")
CRYPTOCLOUD_SECRET = os.environ.get("CRYPTOCLOUD_SECRET", "")  # для проверки JWT в postback
# Постоянная страница оплаты (тестовый режим): https://pay.cryptocloud.plus/pos/<id>
# Если задана — ссылка на пополнение формируется через неё (amount, order_id в URL), без вызова API.
CRYPTOCLOUD_POS_LINK = os.environ.get("CRYPTOCLOUD_POS_LINK", "").rstrip("/")


def _verify_math() -> None:
    """Проверка: чистая выплата за 4 места = доход минус реинвест."""
    for level in (1, 2, 3, 4):
        cost = REINVEST_CONFIG[level]["cost"]
        expected_bonus_total = MATRIX_INCOME[level] - cost
        actual_bonus_total = MATRIX_BONUS_PER_PLACE[level] * 4
        assert abs(actual_bonus_total - expected_bonus_total) < 0.01, (
            f"M{level}: 4*BONUS={actual_bonus_total} != INCOME-cost={expected_bonus_total}"
        )


_verify_math()
