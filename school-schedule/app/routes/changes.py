import sqlite3
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import audit, config
from ..db import get_db, now_iso, touch_updated
from ..schedule import CHANGE_TYPES, WEEKDAYS, base_groups, base_lesson, bells, merged_day, today
from ..schemas import ChangeIn
from ..security import current_user

router = APIRouter(prefix="/api/staff")

_LIST_SQL = """
SELECT ch.*, c.name AS class_name,
       ns.name AS new_subject, nt.name AS new_teacher, nr.name AS new_room,
       cu.full_name AS created_by_name, uu.full_name AS updated_by_name
FROM changes ch
JOIN classes c ON c.id = ch.class_id
LEFT JOIN subjects ns ON ns.id = ch.new_subject_id
LEFT JOIN teachers nt ON nt.id = ch.new_teacher_id
LEFT JOIN rooms nr ON nr.id = ch.new_room_id
LEFT JOIN users cu ON cu.id = ch.created_by
LEFT JOIN users uu ON uu.id = ch.updated_by
"""


def _fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d} ({WEEKDAYS[d.isoweekday()][:2].lower()})"


def describe(row) -> str:
    group = f", {row['group_no']} группа" if row["group_no"] else ""
    parts = [f"{_fmt_date(row['date'])}, {row['class_name']}, {row['lesson_no']}-й урок{group} — {CHANGE_TYPES[row['type']]}"]
    details = []
    if row["new_subject"]:
        details.append(f"предмет: {row['new_subject']}")
    if row["new_teacher"]:
        details.append(f"учитель: {row['new_teacher']}")
    if row["new_room"]:
        details.append(f"кабинет: {row['new_room']}")
    if row["type"] == "move":
        details.append(f"на {_fmt_date(row['move_to_date'])}, {row['move_to_lesson']}-й урок")
    if row["comment"]:
        details.append(f"«{row['comment']}»")
    if details:
        parts.append(", ".join(details))
    return ": ".join(parts)


def _get(conn: sqlite3.Connection, change_id: int):
    row = conn.execute(_LIST_SQL + " WHERE ch.id = ?", (change_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Изменение не найдено (возможно, его уже удалили)")
    return row


def _can_edit(user: dict, row) -> bool:
    return user["role"] == "admin" or row["created_by"] == user["id"]


def _serialize(row, user: dict) -> dict:
    data = dict(row)
    data["can_edit"] = _can_edit(user, row)
    data["type_label"] = CHANGE_TYPES[row["type"]]
    return data


def _check_ref(conn: sqlite3.Connection, table: str, item_id: Optional[int], label: str) -> None:
    if item_id is not None and not conn.execute(
        f"SELECT 1 FROM {table} WHERE id = ?", (item_id,)  # table — константа из кода
    ).fetchone():
        raise HTTPException(400, f"{label} не найден. Обновите страницу.")


def _check_date(d: date, label: str) -> None:
    if d < today():
        raise HTTPException(400, f"{label}: нельзя вносить изменения на прошедшие даты")
    if d > today() + timedelta(days=config.MAX_DAYS_AHEAD):
        raise HTTPException(400, f"{label}: слишком далёкая дата")


def _validate(conn: sqlite3.Connection, data: ChangeIn, change_id: Optional[int] = None) -> None:
    _check_ref(conn, "classes", data.class_id, "Класс")
    _check_ref(conn, "subjects", data.new_subject_id, "Предмет")
    _check_ref(conn, "teachers", data.new_teacher_id, "Учитель")
    _check_ref(conn, "rooms", data.new_room_id, "Кабинет")
    _check_date(data.date, "Дата")

    lesson_count = len(bells(conn))
    if lesson_count and data.lesson_no > lesson_count:
        raise HTTPException(400, f"В расписании звонков только {lesson_count} уроков")

    groups = base_groups(conn, data.class_id, data.date, data.lesson_no)
    if groups and data.group_no == 0 and 0 not in groups:
        raise HTTPException(400, "Этот урок разделён на группы — выберите, для какой группы изменение")
    if data.group_no and 0 in groups:
        raise HTTPException(400, "Этот урок не разделён на группы — выберите «Весь класс»")
    base = base_lesson(conn, data.class_id, data.date, data.lesson_no, data.group_no)
    if data.type != "subject" and not base:
        raise HTTPException(
            400,
            f"В этот день у {'группы' if data.group_no else 'класса'} нет {data.lesson_no}-го урока по расписанию. "
            "Чтобы добавить урок, выберите тип «Другой предмет».",
        )
    if data.type == "teacher" and base and base["teacher_id"] == data.new_teacher_id:
        raise HTTPException(400, "Этот учитель и так ведёт урок по расписанию")
    if data.type == "room" and base and base["room_id"] == data.new_room_id:
        raise HTTPException(400, "Урок и так проходит в этом кабинете")

    if data.type == "move":
        _check_date(data.move_to_date, "Дата переноса")
        if lesson_count and data.move_to_lesson > lesson_count:
            raise HTTPException(400, f"В расписании звонков только {lesson_count} уроков")
        busy = [
            e for e in merged_day(conn, data.move_to_date, data.class_id)
            if e["lesson_no"] == data.move_to_lesson
            and (e["group_no"] == data.group_no or 0 in (e["group_no"], data.group_no))
            and e["status"] not in ("cancel", "move_out")
            and (change_id is None or e["change_id"] != change_id)
        ]
        if busy:
            raise HTTPException(
                400,
                f"На {data.move_to_lesson}-м уроке {data.move_to_date.strftime('%d.%m')} у класса уже есть "
                f"урок «{busy[0]['subject']}». Сначала отмените или перенесите его.",
            )


def _save_error(exc: sqlite3.IntegrityError):
    if "UNIQUE" in str(exc):
        return HTTPException(
            409, "На этот урок уже внесено изменение. Найдите его в списке и отредактируйте."
        )
    return HTTPException(400, "Не удалось сохранить: проверьте выбранные значения")


@router.get("/changes")
def list_changes(
    class_id: Optional[int] = Query(default=None, gt=0),
    user: dict = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    iso = today().isoformat()
    sql = _LIST_SQL + " WHERE (ch.date >= ? OR ch.move_to_date >= ?)"
    params: list = [iso, iso]
    if class_id:
        sql += " AND ch.class_id = ?"
        params.append(class_id)
    rows = conn.execute(sql + " ORDER BY ch.date, ch.lesson_no, c.name, ch.group_no", params).fetchall()
    return {"items": [_serialize(r, user) for r in rows]}


@router.post("/changes", status_code=201)
def create_change(
    data: ChangeIn,
    user: dict = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    _validate(conn, data)
    ts = now_iso()
    try:
        cur = conn.execute(
            "INSERT INTO changes (date, class_id, lesson_no, group_no, type, new_subject_id, new_teacher_id, "
            "new_room_id, move_to_date, move_to_lesson, comment, created_by, created_at, updated_by, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.date.isoformat(), data.class_id, data.lesson_no, data.group_no, data.type,
                data.new_subject_id, data.new_teacher_id, data.new_room_id,
                data.move_to_date.isoformat() if data.move_to_date else None,
                data.move_to_lesson, data.comment, user["id"], ts, user["id"], ts,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise _save_error(exc) from exc
    row = _get(conn, cur.lastrowid)
    audit.log(conn, user, "create", "change", row["id"], describe(row))
    touch_updated(conn)
    return _serialize(row, user)


@router.put("/changes/{change_id}")
def update_change(
    change_id: int,
    data: ChangeIn,
    user: dict = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    old = _get(conn, change_id)
    if not _can_edit(user, old):
        raise HTTPException(403, "Учитель может редактировать только свои изменения")
    if old["date"] < today().isoformat():
        raise HTTPException(400, "Изменение на прошедшую дату редактировать нельзя")
    _validate(conn, data, change_id)
    try:
        conn.execute(
            "UPDATE changes SET date = ?, class_id = ?, lesson_no = ?, group_no = ?, type = ?, new_subject_id = ?, "
            "new_teacher_id = ?, new_room_id = ?, move_to_date = ?, move_to_lesson = ?, comment = ?, "
            "updated_by = ?, updated_at = ? WHERE id = ?",
            (
                data.date.isoformat(), data.class_id, data.lesson_no, data.group_no, data.type,
                data.new_subject_id, data.new_teacher_id, data.new_room_id,
                data.move_to_date.isoformat() if data.move_to_date else None,
                data.move_to_lesson, data.comment, user["id"], now_iso(), change_id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise _save_error(exc) from exc
    new = _get(conn, change_id)
    audit.log(conn, user, "update", "change", change_id, f"Было: {describe(old)}. Стало: {describe(new)}")
    touch_updated(conn)
    return _serialize(new, user)


@router.delete("/changes/{change_id}")
def delete_change(
    change_id: int,
    user: dict = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    old = _get(conn, change_id)
    if not _can_edit(user, old):
        raise HTTPException(403, "Учитель может удалять только свои изменения")
    conn.execute("DELETE FROM changes WHERE id = ?", (change_id,))
    audit.log(conn, user, "delete", "change", change_id, describe(old))
    touch_updated(conn)
    return {"ok": True}


@router.get("/audit")
def audit_log(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    where = "" if user["role"] == "admin" else " WHERE entity = 'change'"
    rows = conn.execute(
        f"SELECT * FROM audit_log{where} ORDER BY id DESC LIMIT ? OFFSET ?", (limit + 1, offset)
    ).fetchall()
    return {"items": [dict(r) for r in rows[:limit]], "has_more": len(rows) > limit}
