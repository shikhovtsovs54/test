"""
Проверка initData от Telegram Web App (Mini App).
Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hmac
import hashlib
import json
from typing import Optional
from urllib.parse import parse_qs, unquote


def validate_init_data(init_data: str, bot_token: str) -> bool:
    """
    Проверяет подпись initData от Telegram Web App.
    secret_key = HMAC-SHA256("WebAppData", bot_token)
    hash = HMAC-SHA256(secret_key, data_check_string)
    """
    if not init_data or not bot_token:
        return False
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        received_hash = (parsed.get("hash") or [None])[0]
        if not received_hash:
            return False
        # data_check_string: все пары кроме hash, отсортированные по ключу, key=value через \n
        pairs = []
        for key, values in parsed.items():
            if key == "hash":
                continue
            value = values[0] if values else ""
            pairs.append((key, value))
        pairs.sort(key=lambda x: x[0])
        data_check_string = "\n".join(f"{k}={v}" for k, v in pairs)
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256,
        ).digest()
        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(computed_hash, received_hash)
    except Exception:
        return False


def parse_user_from_init_data(init_data: str) -> Optional[dict]:
    """
    Извлекает объект user из initData (после проверки подписи).
    user приходит в виде URL-encoded JSON в параметре 'user'.
    """
    if not init_data:
        return None
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        user_str = (parsed.get("user") or [None])[0]
        if not user_str:
            return None
        user_str = unquote(user_str)
        return json.loads(user_str)
    except Exception:
        return None


def get_telegram_user(init_data: str, bot_token: str) -> Optional[dict]:
    """
    Проверяет initData и возвращает данные пользователя Telegram: id, username, first_name, last_name.
    Возвращает None при неверной подписи или отсутствии user.
    """
    if not validate_init_data(init_data, bot_token):
        return None
    return parse_user_from_init_data(init_data)
