# Постоянная ссылка без туннелей (Render)

Никакого ngrok и cloudflare — приложение живёт на сервере Render, ссылка одна и та же всегда. Работает из любой страны.

---

## 1. Репозиторий на GitHub

Если проекта ещё нет на GitHub:

```bash
cd /Users/semensihovcov/matrix_marketing
git init
git add .
git commit -m "Deploy"
```

Создайте репозиторий на https://github.com/new (например `matrix-marketing`), затем:

```bash
git remote add origin https://github.com/ВАШ_ЛОГИН/matrix-marketing.git
git branch -M main
git push -u origin main
```

---

## 2. Деплой на Render

1. Зайдите на **https://render.com** и войдите (через GitHub).
2. **New** → **Web Service**.
3. Подключите репозиторий **matrix-marketing** (или как назвали).
4. Render подхватит настройки из `render.yaml`. Если нет:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. В **Environment** добавьте переменные:
   - `TELEGRAM_BOT_TOKEN` — токен бота от @BotFather
   - `TELEGRAM_BOT_USERNAME` — имя бота без @
   - `USDT_WALLET_TRC20` — при необходимости
6. Нажмите **Create Web Service**. Дождитесь деплоя.

После деплоя получите ссылку вида: **https://matrix-marketing-xxxx.onrender.com**

---

## 3. Настройка бота у себя на компьютере

В папке проекта в файле **.env** укажите эту ссылку (без слэша в конце):

```
WEBAPP_BASE_URL=https://matrix-marketing-xxxx.onrender.com
TELEGRAM_BOT_TOKEN=ваш_токен
TELEGRAM_BOT_USERNAME=имя_бота
```

Сохраните файл. Дальше запускайте бота как обычно:

```bash
python3 bot.py
```

Кнопка в боте будет открывать постоянную ссылку на Render. Туннели и ngrok не нужны.

---

## Важно

- На бесплатном тарифе Render приложение «засыпает» после ~15 минут без запросов. Первый переход по ссылке может занять 30–60 секунд (просыпание).
- База SQLite на Render при перезапуске сервиса сбрасывается (эпиhemeral диск). Для постоянных данных потом можно перейти на БД Render или другую облачную БД.
