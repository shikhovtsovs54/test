#!/bin/bash
# Вставь эту команду в свой терминал — получишь ссылку в этом же окне.

cd "$(dirname "$0")"
echo "Приложение на 8000..."
lsof -i :8000 | grep -q LISTEN || ( python3 run.py & sleep 4 )
echo "Туннель Cloudflare..."
CFLOG=/tmp/cf_getlink.log; rm -f "$CFLOG"
cloudflared tunnel --url http://127.0.0.1:8000 2>&1 | tee "$CFLOG" &
CFPID=$!
for i in $(seq 1 25); do
  sleep 1
  URL=$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "$CFLOG" 2>/dev/null | head -1)
  if [ -n "$URL" ]; then
    python3 -c "import re; s=open('.env').read(); open('.env','w').write(re.sub(r'WEBAPP_BASE_URL=.*','WEBAPP_BASE_URL=$URL',s))"
    echo ""
    echo "=========================================="
    echo "  ССЫЛКА: $URL"
    echo "=========================================="
    echo "  (записана в .env). Запусти бота в другом окне: python3 bot.py"
    echo "  Это окно не закрывай."
    wait $CFPID 2>/dev/null
    exit 0
  fi
done
kill $CFPID 2>/dev/null
echo "Не удалось. Попробуй ngrok: ngrok config add-authtoken ТВОЙ_ТОКЕН && bash start_with_tunnel.sh"
