"""
Telegram-бот проекта MATRIX.
Приветственное сообщение и кнопка перехода в веб-приложение.
Диплинк: t.me/BotUsername?start=TELEGRAM_ID — реферер; при открытии веб-приложения передаётся ref=TELEGRAM_ID.
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

from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_USERNAME, WEBAPP_BASE_URL

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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    # При переходе по t.me/Bot?start=12345 в context.args будет ["12345"] — telegram_id реферера
    start_param = context.args[0] if context.args else None
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
    base = (WEBAPP_BASE_URL or "").strip()
    if not base or "your-domain" in base or not base.startswith("https://"):
        print()
        print("  [!] Страница в боте не откроется: нужен реальный HTTPS-адрес в .env")
        print("      Задайте WEBAPP_BASE_URL=https://ВАШ_АДРЕС (например от ngrok).")
        print("      Локально: запустите 'ngrok http 8000', скопируйте https://... в .env и перезапустите бота.")
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
