#!/bin/bash
# Запуск Telegram-бота MATRIX
# Настройки берутся из .env (токен и URL веб-приложения)

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Создайте файл .env (скопируйте .env.example и заполните TELEGRAM_BOT_TOKEN и WEBAPP_BASE_URL)."
  exit 1
fi

python3 bot.py
