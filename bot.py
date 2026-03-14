"""
Telegram-бот проекта MATRIX.
При /start берём telegram_id пользователя и записываем в БД через /api/bot/on-start.
Приветственное сообщение и кнопка перехода в веб-приложение.
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

WELCOME = (
    "Вас приветствует проект MATRIX.\n\n"
    "Для использования сервиса перейдите в наше веб-приложение по кнопке ниже."
)


def build_webapp_url(ref: str | None) -> str:
    """URL веб-приложения; ref — telegram_id реферера из диплинка ?start=ref."""
    base = (WEBAPP_BASE_URL or "https://your-domain.com").rstrip("/")
    if ref and ref.strip():
        return f"{base}?ref={ref.strip()}"
    return base


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

    # Сразу записываем пользователя в БД (или пропускаем, если уже есть)
    base_url = (WEBAPP_BASE_URL or "").rstrip("/")
    if not base_url or "your-domain" in base_url:
        print("[bot] /start — WEBAPP_BASE_URL не задан или заглушка, запись в БД пропущена")
    elif not BOT_ON_START_SECRET:
        print("[bot] /start — BOT_ON_START_SECRET не задан, запись в БД пропущена")
    else:
        payload = {
            "telegram_id": telegram_id,
            "username": from_user.username,
            "first_name": from_user.first_name,
            "last_name": from_user.last_name,
            "referrer_telegram_id": referrer_telegram_id,
            "bot_secret": BOT_ON_START_SECRET,  # и в теле — если прокси режет заголовок
        }
        print(f"[bot] /start — отправляю в БД: telegram_id={telegram_id} username={payload.get('username')}")
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

    url = build_webapp_url(start_param)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Открыть веб-приложение", web_app=WebAppInfo(url=url))],
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


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("Укажите TELEGRAM_BOT_TOKEN в .env или переменных окружения.")
        sys.exit(1)
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_on_startup)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
