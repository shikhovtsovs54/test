"""
Telegram-бот проекта MATRIX.
При /start берём telegram_id пользователя и записываем в БД.
Режимы: 1) Вместе с бэкендом (на Railway) — запись в БД напрямую, без HTTP.
        2) Отдельно с ПК — запись через POST /api/bot/on-start.
Диплинк: t.me/BotUsername?start=TELEGRAM_ID — реферер.
"""

import os
import sys

# Корень проекта и загрузка .env до импорта app.config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import httpx
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_USERNAME, WEBAPP_BASE_URL, BOT_ON_START_SECRET

# Если задан — при /start пишем в БД напрямую (бот запущен вместе с бэкендом на Railway)
_on_start_db_callback = None


def set_on_start_db_callback(callback):
    """Вызвать из main.py при старте приложения: запись пользователя в БД без HTTP."""
    global _on_start_db_callback
    _on_start_db_callback = callback

WELCOME = (
    "Вас приветствует проект MATRIX.\n\n"
    "Для использования сервиса перейдите в наше веб-приложение по кнопке ниже."
)


def build_webapp_url(telegram_id: int | None, ref: str | None) -> str:
    """URL веб-приложения; tg_id и ref — параметры в query (?tg_id=...&ref=...)."""
    base = (WEBAPP_BASE_URL or "https://your-domain.com").rstrip("/")
    params = []
    if telegram_id is not None:
        params.append(f"tg_id={telegram_id}")
    if ref and str(ref).strip():
        params.append(f"ref={str(ref).strip()}")
    if not params:
        return base
    return base + "?" + "&".join(params)


def _parse_referrer_telegram_id(start_param: str | None) -> int | None:
    """Из start_param (t.me/Bot?start=12345) извлекаем telegram_id реферера."""
    if not start_param or not start_param.strip():
        return None
    s = start_param.strip()
    if not s.isdigit():
        return None
    return int(s)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.from_user:
        print("[bot] /start: нет update.message или from_user")
        return
    from_user = update.message.from_user
    telegram_id = from_user.id
    # При переходе по t.me/Bot?start=12345 в context.args будет ["12345"] — telegram_id реферера
    start_param = context.args[0] if context.args else None
    referrer_telegram_id = _parse_referrer_telegram_id(start_param)

    print(f"[bot] /start — telegram_id={telegram_id} username={getattr(from_user, 'username', None)} first_name={getattr(from_user, 'first_name', None)} referrer_telegram_id={referrer_telegram_id}")

    # Запись в БД: напрямую (бот на Railway) или через HTTP (бот на ПК)
    if _on_start_db_callback:
        try:
            _on_start_db_callback(
                telegram_id=telegram_id,
                username=from_user.username,
                first_name=from_user.first_name,
                last_name=from_user.last_name,
                referrer_telegram_id=referrer_telegram_id,
            )
            print(f"[bot] /start — успех: пользователь записан в БД (напрямую)")
        except Exception as e:
            import traceback
            print(f"[bot] /start — ошибка записи в БД: {e}")
            traceback.print_exc()
    else:
        base_url = (WEBAPP_BASE_URL or "").rstrip("/")
        if not base_url or "your-domain" in base_url:
            print("[bot] /start — WEBAPP_BASE_URL не задан, запись в БД пропущена")
        elif not BOT_ON_START_SECRET:
            print("[bot] /start — BOT_ON_START_SECRET не задан, запись в БД пропущена")
        else:
            payload = {
                "telegram_id": telegram_id,
                "username": from_user.username,
                "first_name": from_user.first_name,
                "last_name": from_user.last_name,
                "referrer_telegram_id": referrer_telegram_id,
                "bot_secret": BOT_ON_START_SECRET,
            }
            print(f"[bot] /start — отправляю в БД по HTTP: telegram_id={telegram_id}")
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(
                        f"{base_url}/api/bot/on-start",
                        json=payload,
                        headers={"X-Bot-Secret": BOT_ON_START_SECRET},
                    )
                    r.raise_for_status()
                    print(f"[bot] /start — успех: пользователь записан в БД (ответ {r.status_code})")
            except httpx.HTTPStatusError as e:
                print(f"[bot] /start — ошибка HTTP: {e.response.status_code} body: {e.response.text}")
            except Exception as e:
                import traceback
                print(f"[bot] /start — исключение: {e}")
                traceback.print_exc()

    url = build_webapp_url(telegram_id, start_param)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Открыть веб-приложение", url=url)],
    ])
    await update.message.reply_text(WELCOME, reply_markup=keyboard)


async def _on_startup(app: Application) -> None:
    bot_info = await app.bot.get_me()
    username = bot_info.username if bot_info else None
    if username:
        print("Бот запущен: t.me/" + username)
        if not TELEGRAM_BOT_USERNAME or TELEGRAM_BOT_USERNAME == "YourBot":
            print("  Добавьте в .env: TELEGRAM_BOT_USERNAME=" + username)
    if not BOT_ON_START_SECRET:
        print()
        print("  [!] BOT_ON_START_SECRET не задан — пользователи НЕ записываются в БД, в ЛК не пустит.")
        print("      Добавьте в .env: BOT_ON_START_SECRET=любая_длинная_случайная_строка")
        print("      Сгенерировать: openssl rand -hex 32")
        print("      Ту же строку пропишите в переменных Railway (если бэкенд там).")
        print()
    base = (WEBAPP_BASE_URL or "").strip()
    if not base or "your-domain" in base or not base.startswith("https://"):
        print()
        print("  [!] WEBAPP_BASE_URL не задан — страница в боте не откроется. Задайте в .env HTTPS-адрес бэкенда.")
        print()


def build_app():
    """Создать Application бота (для запуска отдельно или из main.py)."""
    return (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_on_startup)
        .build()
    )


def run_bot() -> None:
    """Запуск бота (polling). Вызывается из main() или из потока при старте FastAPI."""
    if not TELEGRAM_BOT_TOKEN:
        print("[bot] TELEGRAM_BOT_TOKEN не задан, бот не запущен.")
        return
    app = build_app()
    app.add_handler(CommandHandler("start", start))
    # В отдельном потоке нельзя трогать сигнал-обработчики, поэтому отключаем stop_signals
    app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("Укажите TELEGRAM_BOT_TOKEN в .env или переменных окружения.")
        sys.exit(1)
    run_bot()


if __name__ == "__main__":
    main()
