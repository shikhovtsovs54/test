# Деплой через командную строку

## 1. Отправка кода на GitHub

В терминале из папки проекта выполните (подставьте свой репозиторий):

```bash
cd /Users/semensihovcov/matrix_marketing

# Если git ещё не инициализирован
git init
git add .
git commit -m "Initial commit for deploy"

# Подключите свой репозиторий (замените ВАШ_ЛОГИН и ИМЯ_РЕПО на свои)
git remote add origin https://github.com/ВАШ_ЛОГИН/ИМЯ_РЕПО.git

# Отправка в GitHub
git branch -M main
git push -u origin main
```

Если репозиторий уже подключён и нужно только обновить код:

```bash
cd /Users/semensihovcov/matrix_marketing
git add .
git commit -m "Deploy"
git push origin main
```

---

## 2. Один раз: создать сервис на Render

Через браузер (один раз):

1. Зайдите на **https://dashboard.render.com**
2. **New** → **Web Service**
3. Выберите **Connect account** → GitHub → выберите репозиторий **matrix-marketing** (или как назвали)
4. Render подхватит настройки из `render.yaml`. Если спрашивает:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. В **Environment** добавьте:
   - `TELEGRAM_BOT_TOKEN` = ваш токен
   - `TELEGRAM_BOT_USERNAME` = имя бота без @
6. Нажмите **Create Web Service**

Сервис создан. Дальнейший деплой — только через команды.

---

## 3. Деплой (каждый раз когда нужно обновить)

Из папки проекта:

```bash
cd /Users/semensihovcov/matrix_marketing
git add .
git commit -m "Update"
git push origin main
```

Render сам подхватит push и пересоберёт проект. Статус смотрите в **Dashboard** → ваш сервис → **Events**.

Готовая ссылка будет вида: `https://matrix-marketing-xxxx.onrender.com` — её укажите в локальном `.env` как `WEBAPP_BASE_URL`.
