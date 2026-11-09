import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bells (
    lesson_no  INTEGER PRIMARY KEY CHECK (lesson_no BETWEEN 1 AND 12),
    start_time TEXT NOT NULL,
    end_time   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classes (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS teachers (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS subjects (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS rooms (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS schedule (
    id         INTEGER PRIMARY KEY,
    class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    weekday    INTEGER NOT NULL CHECK (weekday BETWEEN 1 AND 7),
    lesson_no  INTEGER NOT NULL CHECK (lesson_no BETWEEN 1 AND 12),
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
    teacher_id INTEGER REFERENCES teachers(id) ON DELETE RESTRICT,
    room_id    INTEGER REFERENCES rooms(id) ON DELETE RESTRICT,
    UNIQUE (class_id, weekday, lesson_no)
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name     TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('teacher', 'admin')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS changes (
    id             INTEGER PRIMARY KEY,
    date           TEXT NOT NULL,
    class_id       INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    lesson_no      INTEGER NOT NULL CHECK (lesson_no BETWEEN 1 AND 12),
    type           TEXT NOT NULL CHECK (type IN ('teacher', 'subject', 'room', 'cancel', 'move')),
    new_subject_id INTEGER REFERENCES subjects(id) ON DELETE RESTRICT,
    new_teacher_id INTEGER REFERENCES teachers(id) ON DELETE RESTRICT,
    new_room_id    INTEGER REFERENCES rooms(id) ON DELETE RESTRICT,
    move_to_date   TEXT,
    move_to_lesson INTEGER CHECK (move_to_lesson BETWEEN 1 AND 12),
    comment        TEXT NOT NULL DEFAULT '',
    created_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL,
    updated_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE (date, class_id, lesson_no)
);
CREATE INDEX IF NOT EXISTS idx_changes_date ON changes(date);
CREATE INDEX IF NOT EXISTS idx_changes_move ON changes(move_to_date);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY,
    ts        TEXT NOT NULL,
    user_id   INTEGER,
    username  TEXT NOT NULL,
    action    TEXT NOT NULL,
    entity    TEXT NOT NULL,
    entity_id INTEGER,
    summary   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_failures (
    id  INTEGER PRIMARY KEY,
    key TEXT NOT NULL,
    ts  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_failures ON login_failures(key, ts);
"""

DEFAULT_SETTINGS = {
    "school_name": "Школа",
    "school_days": "1,2,3,4,5",
    "last_updated": "",
}


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI может открыть соединение в одном потоке пула, а использовать в другом; запросы не делят соединения.
    conn = sqlite3.connect(config.DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def connection():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db():
    with connection() as conn:
        yield conn


def init_db() -> None:
    with connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )


def now_local() -> datetime:
    return datetime.now(config.SCHOOL_TZ)


def now_iso() -> str:
    return now_local().isoformat(timespec="seconds")


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def touch_updated(conn: sqlite3.Connection) -> None:
    set_setting(conn, "last_updated", now_iso())


def school_days(conn: sqlite3.Connection) -> list[int]:
    raw = get_setting(conn, "school_days")
    return sorted(int(x) for x in raw.split(",") if x.strip())
