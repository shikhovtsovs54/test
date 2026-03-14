# Деплой на Railway (без верификации телефона)

Вход через GitHub, номер не нужен.

---

## 1. Зайти на Railway

1. Открой **https://railway.app**
2. Нажми **Login** → **Login with GitHub**
3. Разреши доступ к аккаунту GitHub (можно только репозиторию test)

---

## 2. Новый проект из GitHub

1. На главной нажми **New Project**
2. Выбери **Deploy from GitHub repo**
3. Если репо не видно — **Configure GitHub App** и дай доступ к **shikhovtsovs54/test**
4. Выбери репозиторий **test**
5. Railway сам подхватит код и начнёт сборку

---

## 3. Переменные окружения

1. Открой свой сервис (карточка с названием репо)
2. Вкладка **Variables** (или **Settings** → Variables)
3. Нажми **Add Variable** и добавь:
   - **TELEGRAM_BOT_TOKEN** = твой токен от @BotFather
   - **TELEGRAM_BOT_USERNAME** = имя бота без @
   - **WEBAPP_BASE_URL** = публичный URL этого же сервиса (из шага 4), без слэша в конце, например `https://test-production-xxxx.up.railway.app`
   - **BOT_ON_START_SECRET** = любая длинная случайная строка (например сгенерируй: `openssl rand -hex 32`). Ту же строку пропиши в локальном `.env` для бота
   - **USDT_WALLET_TRC20** = (по желанию) кошелёк для пополнения

Сохрани. Railway перезапустит сервис с новыми переменными.

---

## 4. Публичный URL

1. В сервисе открой вкладку **Settings**
2. Блок **Networking** → **Generate Domain**
3. Скопируй ссылку вида **https://test-production-xxxx.up.railway.app**

---

## 5. У себя в .env

В папке проекта в файле **.env** пропиши (подставь свои значения):

```
TELEGRAM_BOT_TOKEN=твой_токен
TELEGRAM_BOT_USERNAME=имя_бота_без_собаки
WEBAPP_BASE_URL=https://твой-домен.up.railway.app
BOT_ON_START_SECRET=такая_же_строка_как_в_Railway
```

Без слэша в конце у URL. Дальше запускай бота: `python3 bot.py`.

---

## Обновление кода (повторный деплой)

Пушишь в GitHub — Railway сам пересоберёт и задеплоит:

```bash
cd /Users/semensihovcov/matrix_marketing
git add .
git commit -m "Update"
git push origin main
```

Если просит логин/пароль, используй токен GitHub:
```bash
git push https://shikhovtsovs54:ТВОЙ_GITHUB_TOKEN@github.com/shikhovtsovs54/test.git main
```

Подробная инструкция по повторному деплою и переменным — в файле **REDEPLOY.md**.
