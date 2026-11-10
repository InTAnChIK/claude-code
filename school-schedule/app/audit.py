import sqlite3

from .db import now_iso


def log(
    conn: sqlite3.Connection,
    user: dict | None,
    action: str,
    entity: str,
    entity_id: int | None,
    summary: str,
) -> None:
    conn.execute(
        "INSERT INTO audit_log (ts, user_id, username, action, entity, entity_id, summary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            now_iso(),
            user["id"] if user else None,
            (f"{user['full_name']} ({user['username']})" if user else "система"),
            action,
            entity,
            entity_id,
            summary,
        ),
    )
