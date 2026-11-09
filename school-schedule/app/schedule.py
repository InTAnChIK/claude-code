"""Сборка фактического расписания: постоянное расписание + изменения на конкретную дату."""

import re
import sqlite3
from datetime import date, timedelta

from .db import now_local, school_days

WEEKDAYS = ["", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

CHANGE_TYPES = {
    "teacher": "Замена учителя",
    "subject": "Другой предмет",
    "room": "Смена кабинета",
    "cancel": "Отмена урока",
    "move": "Перенос",
}


def today() -> date:
    return now_local().date()


def class_sort_key(name: str):
    m = re.match(r"\s*(\d+)\s*(.*)", name)
    return (int(m.group(1)), m.group(2).lower()) if m else (999, name.lower())


def bells(conn: sqlite3.Connection) -> dict[int, dict]:
    rows = conn.execute("SELECT * FROM bells ORDER BY lesson_no").fetchall()
    return {r["lesson_no"]: {"start": r["start_time"], "end": r["end_time"]} for r in rows}


_BASE_SQL = """
SELECT s.class_id, c.name AS class_name, s.lesson_no,
       s.subject_id, sub.name AS subject,
       s.teacher_id, t.name AS teacher,
       s.room_id, r.name AS room
FROM schedule s
JOIN classes c ON c.id = s.class_id
JOIN subjects sub ON sub.id = s.subject_id
LEFT JOIN teachers t ON t.id = s.teacher_id
LEFT JOIN rooms r ON r.id = s.room_id
WHERE s.weekday = ?
"""

_CHANGES_SQL = """
SELECT ch.*, c.name AS class_name,
       ns.name AS new_subject, nt.name AS new_teacher, nr.name AS new_room
FROM changes ch
JOIN classes c ON c.id = ch.class_id
LEFT JOIN subjects ns ON ns.id = ch.new_subject_id
LEFT JOIN teachers nt ON nt.id = ch.new_teacher_id
LEFT JOIN rooms nr ON nr.id = ch.new_room_id
"""


def _lesson_fields(row) -> dict:
    return {
        "subject_id": row["subject_id"],
        "subject": row["subject"],
        "teacher_id": row["teacher_id"],
        "teacher": row["teacher"],
        "room_id": row["room_id"],
        "room": row["room"],
    }


def base_lesson(conn: sqlite3.Connection, class_id: int, day: date, lesson_no: int):
    row = conn.execute(
        _BASE_SQL + " AND s.class_id = ? AND s.lesson_no = ?",
        (day.isoweekday(), class_id, lesson_no),
    ).fetchone()
    return _lesson_fields(row) if row else None


def _apply_overrides(fields: dict, ch) -> dict:
    out = dict(fields)
    for key in ("subject", "teacher", "room"):
        if ch[f"new_{key}_id"] is not None:
            out[f"{key}_id"] = ch[f"new_{key}_id"]
            out[key] = ch[f"new_{key}"]
    return out


_EMPTY = {k: None for k in ("subject_id", "subject", "teacher_id", "teacher", "room_id", "room")}


def merged_day(conn: sqlite3.Connection, day: date, class_id: int | None = None) -> list[dict]:
    """Изменения на прошедшие даты не применяются — они скрываются автоматически."""
    iso = day.isoformat()
    apply_changes = day >= today()
    class_filter = " AND s.class_id = ?" if class_id else ""
    params = (day.isoweekday(), class_id) if class_id else (day.isoweekday(),)
    entries: dict[tuple[int, int], dict] = {}

    for row in conn.execute(_BASE_SQL + class_filter, params):
        entries[(row["class_id"], row["lesson_no"])] = {
            "class_id": row["class_id"],
            "class_name": row["class_name"],
            "lesson_no": row["lesson_no"],
            **_lesson_fields(row),
            "orig": None,
            "status": "normal",
            "comment": "",
            "move": None,
            "change_id": None,
        }

    ch_filter = " AND ch.class_id = ?" if class_id else ""
    ch_params = (iso, class_id) if class_id else (iso,)
    extra: list[dict] = []
    own_changes = (
        conn.execute(_CHANGES_SQL + " WHERE ch.date = ?" + ch_filter, ch_params).fetchall()
        if apply_changes
        else []
    )

    for ch in own_changes:
        key = (ch["class_id"], ch["lesson_no"])
        entry = entries.get(key) or {
            "class_id": ch["class_id"],
            "class_name": ch["class_name"],
            "lesson_no": ch["lesson_no"],
            **_EMPTY,
            "orig": None,
            "move": None,
        }
        base = {k: entry[k] for k in _EMPTY}
        has_base = key in entries
        entry["orig"] = base if has_base else None
        entry["comment"] = ch["comment"]
        entry["change_id"] = ch["id"]
        if ch["type"] == "move":
            entry["status"] = "move_out"
            entry["move"] = {"date": ch["move_to_date"], "lesson_no": ch["move_to_lesson"]}
        else:
            entry["status"] = ch["type"]
            if ch["type"] != "cancel":
                entry.update(_apply_overrides(base, ch))
        entries[key] = entry

    incoming = (
        conn.execute(
            _CHANGES_SQL + " WHERE ch.type = 'move' AND ch.move_to_date = ?" + ch_filter, ch_params
        ).fetchall()
        if apply_changes
        else []
    )
    for ch in incoming:
        src_day = date.fromisoformat(ch["date"])
        src = base_lesson(conn, ch["class_id"], src_day, ch["lesson_no"]) or dict(_EMPTY)
        extra.append(
            {
                "class_id": ch["class_id"],
                "class_name": ch["class_name"],
                "lesson_no": ch["move_to_lesson"],
                **_apply_overrides(src, ch),
                "orig": src,
                "status": "move_in",
                "comment": ch["comment"],
                "move": {"date": ch["date"], "lesson_no": ch["lesson_no"]},
                "change_id": ch["id"],
            }
        )

    result = list(entries.values()) + extra
    result.sort(key=lambda e: (e["lesson_no"], class_sort_key(e["class_name"])))
    return result


def merged_range(
    conn: sqlite3.Connection, start: date, days: int, class_id: int | None = None
) -> list[dict]:
    work_days = set(school_days(conn))
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        lessons = merged_day(conn, d, class_id)
        out.append(
            {
                "date": d.isoformat(),
                "weekday": WEEKDAYS[d.isoweekday()],
                "is_school_day": d.isoweekday() in work_days or bool(lessons),
                "lessons": lessons,
            }
        )
    return out


def filter_by(lessons: list[dict], field: str, value: int) -> list[dict]:
    """Уроки, где учитель/кабинет участвует сейчас или был по расписанию."""
    key = f"{field}_id"
    return [
        e for e in lessons
        if e[key] == value or (e["orig"] is not None and e["orig"][key] == value)
    ]
