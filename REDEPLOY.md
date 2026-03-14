# Деплой и повторный деплой (Railway)

- **Первый раз:** выполни шаги 1–2 (переменные и домен), затем 4 (пуш кода). **Бот на Railway запускается автоматически** вместе с бэкендом — с ПК запускать не нужно.
- **Повторно (обновление кода):** достаточно шага 4 (пуш в GitHub). Переменные и домен уже заданы.

---

## 1. Переменные окружения на Railway

В **Railway** → твой проект → сервис → вкладка **Variables** должны быть заданы:

| Переменная | Описание |
|------------|----------|
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather |
| `TELEGRAM_BOT_USERNAME` | Имя бота без @ (для ссылки t.me/BotName?start=...) |
| `WEBAPP_BASE_URL` | Публичный URL приложения, например `https://web-production-5046e.up.railway.app` (без слэша в конце) |
| `BOT_ON_START_SECRET` | Нужен только если запускаешь бота с ПК. На Railway бот работает в том же процессе и пишет в БД напрямую — секрет не используется. |
| `USDT_WALLET_TRC20` | (по желанию) Кошелёк USDT TRC20 для пополнения |
| `JWT_SECRET` | (по желанию) Секрет для JWT; если не задан, используется значение по умолчанию |

**На Railway:** бот стартует вместе с приложением и при `/start` пишет пользователя в БД напрямую (без HTTP). Переменная `BOT_ON_START_SECRET` на Railway не обязательна. С ПК бота можно не запускать.

---

## 2. Публичный домен

Если домен ещё не создан:

1. Railway → сервис → **Settings** → **Networking**
2. **Generate Domain** — скопируй URL (например `https://web-production-5046e.up.railway.app`)
3. В **Variables** добавь или измени `WEBAPP_BASE_URL` на этот URL (без `/` в конце)

---

## 3. Локальный .env для бота

В папке проекта создай или отредактируй `.env` (файл не коммитить):

```env
TELEGRAM_BOT_TOKEN=твой_токен_от_BotFather
TELEGRAM_BOT_USERNAME=имя_бота_без_собаки
WEBAPP_BASE_URL=https://твой-домен.up.railway.app
BOT_ON_START_SECRET=такая_же_строка_как_на_Railway
```

Сгенерировать секрет в терминале:
```bash
openssl rand -hex 32
```

---

## 4. Повторный деплой (обновление кода)

Из папки проекта:

```bash
cd /Users/semensihovcov/matrix_marketing

# Все изменения
git add .
git status

# Коммит
git commit -m "Update"

# Пуш в GitHub (Railway сам подхватит и пересоберёт)
git push origin main
```

Если используешь токен GitHub вместо SSH:
```bash
git push https://shikhovtsovs54:ТВОЙ_GITHUB_TOKEN@github.com/shikhovtsovs54/test.git main
```

После пуша Railway автоматически пересоберёт и задеплоит приложение. Статус смотри в Railway → Deployments.

---

## 5. Запуск бота с ПК (необязательно)

На Railway бот уже запущен вместе с бэкендом — при `/start` пользователь сразу пишется в БД. Запускать бота с компьютера нужно только для отладки или если бэкенд не на Railway.

```bash
cd /Users/semensihovcov/matrix_marketing
pip install -r requirements.txt
python3 bot.py
```

В логе: `Бот запущен: t.me/YourBot`. Для записи в БД с ПК нужны `WEBAPP_BASE_URL` и `BOT_ON_START_SECRET` в `.env`.

---

## 6. Проверка

1. В Telegram открой бота и нажми **Start** (или отправь `/start`).
2. Нажми кнопку **«Открыть веб-приложение»** — должен открыться личный кабинет (пользователь создаётся при `/start`, при открытии веб-приложения авторизуется по Telegram).
3. Если что-то не работает — проверь переменные на Railway и в `.env`, совпадение `BOT_ON_START_SECRET`, а также логи деплоя в Railway.

---

## Кратко: что куда

| Где | Что |
|-----|-----|
| **Railway** | Бэкенд (FastAPI) + раздача статики (веб-приложение). Переменные: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `WEBAPP_BASE_URL`, `BOT_ON_START_SECRET`, при желании `USDT_WALLET_TRC20`, `JWT_SECRET`. |
| **Локально** | Запуск бота (`python3 bot.py`). В `.env` те же `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `WEBAPP_BASE_URL`, `BOT_ON_START_SECRET`. |
| **GitHub** | Код. После `git push origin main` Railway сам делает повторный деплой. |
