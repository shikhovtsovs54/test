#!/bin/bash
# Только uvicorn + только ngrok. Один раз настройте ngrok — дальше всё поднимется само.

set -e
cd "$(dirname "$0")"
PORT=8000

echo "=== Туннель для бота MATRIX ==="
echo ""

# 1. Проверка ngrok
if ! command -v ngrok >/dev/null 2>&1; then
  echo "Установите ngrok:  brew install ngrok"
  exit 1
fi

# 2. Запуск приложения (uvicorn)
if ! lsof -i :$PORT 2>/dev/null | grep -q LISTEN; then
  echo "[1] Запуск приложения на порту $PORT (uvicorn)..."
  python3 run.py &
  APP_PID=$!
  sleep 4
else
  echo "[1] Приложение уже запущено на порту $PORT."
  APP_PID=""
fi

# 3. Запуск ngrok
echo "[2] Запуск ngrok..."
NGROK_LOG=/tmp/ngrok_matrix.log
rm -f "$NGROK_LOG"
ngrok http $PORT --log=stdout > "$NGROK_LOG" 2>&1 &
NGROK_PID=$!

# 4. Ждём ссылку (до 40 сек)
echo "[3] Ожидание ссылки..."
URL=""
for i in $(seq 1 40); do
  sleep 1
  URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for t in d.get('tunnels', []):
        u = t.get('public_url', '')
        if u.startswith('https://'):
            print(u.strip())
            break
except: pass
" 2>/dev/null)
  if [ -n "$URL" ]; then
    break
  fi
  [ $((i % 8)) -eq 0 ] && echo "    ... ещё $((40-i)) сек"
done

if [ -z "$URL" ]; then
  echo ""
  echo "Ngrok не выдал ссылку. Сделайте один раз:"
  echo ""
  echo "  1. Откройте:  https://dashboard.ngrok.com/get-started/your-authtoken"
  echo "  2. Скопируйте свой authtoken (нужна бесплатная регистрация)."
  echo "  3. В терминале выполните:"
  echo "     ngrok config add-authtoken ВАШ_ТОКЕН"
  echo "  4. Запустите этот скрипт снова:  bash start_with_tunnel.sh"
  echo ""
  kill $NGROK_PID 2>/dev/null
  [ -n "$APP_PID" ] && kill $APP_PID 2>/dev/null
  exit 1
fi

# 5. Пишем ссылку в .env
if [ -f .env ]; then
  python3 -c "
import re, sys
url = sys.argv[1]
with open('.env', 'r') as f:
    s = f.read()
s = re.sub(r'WEBAPP_BASE_URL=.*', 'WEBAPP_BASE_URL=' + url, s)
with open('.env', 'w') as f:
    f.write(s)
" "$URL"
fi

echo ""
echo "=============================================="
echo "  Ссылка для бота: $URL"
echo "  (записана в .env)"
echo "=============================================="
echo ""
echo "  В другом терминале запустите бота:"
echo "    cd $(pwd)"
echo "    python3 bot.py"
echo ""
echo "  Это окно не закрывайте — иначе ссылка перестанет работать."
echo "  Остановка: Ctrl+C"
echo ""

wait $NGROK_PID 2>/dev/null
