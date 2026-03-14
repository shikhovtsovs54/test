# Если с бота не открывается сайт (открывается как в браузере)

## 1. Настройка кнопки меню в BotFather

Чтобы Telegram открывал ваше приложение **внутри приложения** (а не в Safari/Chrome):

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram.
2. Отправьте **/mybots** → выберите своего бота.
3. Нажмите **Bot Settings** → **Menu Button** → **Configure menu button**.
4. Выберите **Configure menu button URL**.
5. Введите URL вашего приложения (без слэша в конце):
   ```
   https://web-production-5046e.up.railway.app
   ```
6. Сохраните.

После этого у бота появится кнопка меню (слева от поля ввода), которая открывает приложение во встроенном окне Telegram.

## 2. Как открывать приложение

- Нажимайте кнопку **«Открыть веб-приложение»** **под сообщением бота** (после /start),  
  **или** кнопку меню (иконка слева от поля ввода).
- **Не копируйте** ссылку в Safari или Chrome — тогда Telegram не передаёт данные для входа, и сайт покажет «откройте из бота».

## 3. Обновить код на Railway

После изменений в коде выполните:

```bash
cd /Users/semensihovcov/matrix_marketing
git add .
git commit -m "Fix Web App open in Telegram"
git push https://shikhovtsovs54:ВАШ_ТОКЕН@github.com/shikhovtsovs54/test.git main
```

Подставьте свой GitHub-токен. Railway сам пересоберёт и задеплоит приложение.
