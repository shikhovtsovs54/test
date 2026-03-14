"""Авторизация: хеширование пароля и JWT."""
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt

from app.config import JWT_ALGORITHM, JWT_EXPIRE_HOURS, JWT_SECRET


def hash_password(password: str) -> str:
    # bcrypt ограничивает пароль 72 байтами
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain.encode("utf-8")[:72],
            hashed.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    to_encode = {"sub": subject, "exp": expire}
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def generate_referral_code() -> str:
    """Уникальный код для реферальной ссылки (8 символов)."""
    return secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
