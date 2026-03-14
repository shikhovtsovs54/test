"""Простой лог событий для отображения на фронтенде."""

from collections import deque
from datetime import datetime

# Последние 200 событий
_event_log: deque = deque(maxlen=200)


def log(message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    _event_log.append(f"{ts} - {message}")


def get_recent_events(limit: int = 50) -> list:
    return list(_event_log)[-limit:]
