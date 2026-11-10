"""Конфиг бота «Химия». Читает переменные окружения и .env рядом с файлом."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS: list[int] = [
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().isdigit()
]

DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "himiya.db"))

# ── Игровые настройки ────────────────────────────────────────────────
BOT_NAME = "Химия"
MATCH_TTL_HOURS = int(os.getenv("MATCH_TTL_HOURS", "48"))  # мэтч сгорает, если тишина
PHOTO_PEEK_STARS = int(os.getenv("PHOTO_PEEK_STARS", "1"))  # цена «подглядеть фото», Telegram Stars
MIN_AGE = 18
MAX_AGE = 99
DAILY_LIKES = int(os.getenv("DAILY_LIKES", "40"))  # лимит лайков в сутки (анти-спам)

# ── Лента ────────────────────────────────────────────────────────────
INGEST_MINUTES = int(os.getenv("INGEST_MINUTES", "30"))     # как часто тянуть RSS
DIGEST_HOUR = int(os.getenv("DIGEST_HOUR", "10"))           # во сколько слать дайджест
DIGEST_TZ_OFFSET = int(os.getenv("DIGEST_TZ_OFFSET", "0"))  # Лондон: 0 (лето — 1)

# Цвета/эмодзи бренда
E = {
    "fire": "🔥",
    "heart": "❤️",
    "chem": "🧪",
    "quest": "🧊",
    "ok": "✅",
    "no": "➖",
    "star": "⭐",
    "shield": "🛡",
}
