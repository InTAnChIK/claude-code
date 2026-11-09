import os
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

DB_PATH = Path(os.environ.get("DB_PATH", BASE_DIR / "data" / "schedule.db"))
STATIC_DIR = BASE_DIR / "static"
SCHOOL_TZ = ZoneInfo(os.environ.get("SCHOOL_TZ", "Europe/Moscow"))

# "auto": Secure-cookie ставится, если запрос пришёл по HTTPS (через прокси с X-Forwarded-Proto).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "auto").lower()
SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "12"))

LOGIN_MAX_FAILS_PER_USER = 5
LOGIN_MAX_FAILS_PER_IP = 20
LOGIN_WINDOW_MINUTES = 15

MAX_DAYS_AHEAD = 366
