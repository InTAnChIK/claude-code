import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import audit, security
from ..db import get_db, now_iso, set_setting, touch_updated
from ..schedule import WEEKDAYS
from ..schemas import BellsIn, NameIn, ScheduleCellIn, SettingsIn, UserCreateIn, UserUpdateIn

router = APIRouter(prefix="/api/admin")

Kind = Literal["classes", "teachers", "subjects", "rooms"]
KIND_LABELS = {
    "classes": ("Класс", "класс"),
    "teachers": ("Учитель", "учителя"),
    "subjects": ("Предмет", "предмет"),
    "rooms": ("Кабинет", "кабинет"),
}


def _name_row(conn: sqlite3.Connection, kind: str, item_id: int):
    row = conn.execute(f"SELECT id, name FROM {kind} WHERE id = ?", (item_id,)).fetchone()  # kind проверен Literal
    if not row:
        raise HTTPException(404, f"{KIND_LABELS[kind][0]} не найден")
    return row


def _normalized_name(conn: sqlite3.Connection, kind: str, name: str, exclude_id: int | None = None) -> str:
    if kind == "classes":
        name = name.upper()
    # COLLATE NOCASE в SQLite не различает регистр только для латиницы, поэтому дубли ищем здесь.
    key = name.casefold()
    for row in conn.execute(f"SELECT id, name FROM {kind}"):
        if row["id"] != exclude_id and row["name"].casefold() == key:
            raise HTTPException(409, f"«{row['name']}» уже есть в списке")
    return name


@router.post("/dict/{kind}", status_code=201)
def create_item(
    kind: Kind,
    data: NameIn,
    user: dict = Depends(security.admin_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    data.name = _normalized_name(conn, kind, data.name)
    try:
        cur = conn.execute(f"INSERT INTO {kind} (name) VALUES (?)", (data.name,))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, f"«{data.name}» уже есть в списке") from exc
    audit.log(conn, user, "create", kind, cur.lastrowid, f"Добавлен {KIND_LABELS[kind][1]}: {data.name}")
    touch_updated(conn)
    return {"id": cur.lastrowid, "name": data.name}


@router.put("/dict/{kind}/{item_id}")
def rename_item(
    kind: Kind,
    item_id: int,
    data: NameIn,
    user: dict = Depends(security.admin_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    old = _name_row(conn, kind, item_id)
    data.name = _normalized_name(conn, kind, data.name, exclude_id=item_id)
    try:
        conn.execute(f"UPDATE {kind} SET name = ? WHERE id = ?", (data.name, item_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, f"«{data.name}» уже есть в списке") from exc
    audit.log(conn, user, "update", kind, item_id, f"Переименован {KIND_LABELS[kind][1]}: {old['name']} → {data.name}")
    touch_updated(conn)
    return {"id": item_id, "name": data.name}


@router.delete("/dict/{kind}/{item_id}")
def delete_item(
    kind: Kind,
    item_id: int,
    user: dict = Depends(security.admin_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    old = _name_row(conn, kind, item_id)
    try:
        conn.execute(f"DELETE FROM {kind} WHERE id = ?", (item_id,))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            409, f"Нельзя удалить «{old['name']}»: используется в расписании или заменах. Сначала уберите его оттуда."
        ) from exc
    audit.log(conn, user, "delete", kind, item_id, f"Удалён {KIND_LABELS[kind][1]}: {old['name']}")
    touch_updated(conn)
    return {"ok": True}


@router.get("/schedule")
def get_schedule(
    class_id: int = Query(gt=0),
    user: dict = Depends(security.admin_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    rows = conn.execute(
        "SELECT weekday, lesson_no, subject_id, teacher_id, room_id FROM schedule WHERE class_id = ?",
        (class_id,),
    ).fetchall()
    return {"cells": [dict(r) for r in rows]}


def _cell_label(conn: sqlite3.Connection, class_id: int, weekday: int, lesson_no: int) -> str:
    cls = conn.execute("SELECT name FROM classes WHERE id = ?", (class_id,)).fetchone()
    return f"{cls['name'] if cls else '?'}, {WEEKDAYS[weekday].lower()}, {lesson_no}-й урок"


@router.put("/schedule")
def set_cell(
    data: ScheduleCellIn,
    user: dict = Depends(security.admin_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    for table, item_id, label in (
        ("classes", data.class_id, "Класс"),
        ("subjects", data.subject_id, "Предмет"),
        ("teachers", data.teacher_id, "Учитель"),
        ("rooms", data.room_id, "Кабинет"),
    ):
        if item_id is not None and not conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (item_id,)).fetchone():
            raise HTTPException(400, f"{label} не найден. Обновите страницу.")
    lesson_count = conn.execute("SELECT COUNT(*) c FROM bells").fetchone()["c"]
    if data.lesson_no > lesson_count:
        raise HTTPException(400, f"В расписании звонков только {lesson_count} уроков — сначала добавьте звонок")
    conn.execute(
        "INSERT INTO schedule (class_id, weekday, lesson_no, subject_id, teacher_id, room_id) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(class_id, weekday, lesson_no) DO UPDATE SET "
        "subject_id = excluded.subject_id, teacher_id = excluded.teacher_id, room_id = excluded.room_id",
        (data.class_id, data.weekday, data.lesson_no, data.subject_id, data.teacher_id, data.room_id),
    )
    names = conn.execute(
        "SELECT (SELECT name FROM subjects WHERE id = ?) s, (SELECT name FROM teachers WHERE id = ?) t, "
        "(SELECT name FROM rooms WHERE id = ?) r",
        (data.subject_id, data.teacher_id, data.room_id),
    ).fetchone()
    summary = ", ".join(x for x in (names["s"], names["t"], names["r"] and f"каб. {names['r']}") if x)
    audit.log(conn, user, "update", "schedule", data.class_id,
              f"Постоянное расписание, {_cell_label(conn, data.class_id, data.weekday, data.lesson_no)}: {summary}")
    touch_updated(conn)
    return {"ok": True}


@router.delete("/schedule")
def delete_cell(
    class_id: int = Query(gt=0),
    weekday: int = Query(ge=1, le=7),
    lesson_no: int = Query(ge=1, le=12),
    user: dict = Depends(security.admin_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    cur = conn.execute(
        "DELETE FROM schedule WHERE class_id = ? AND weekday = ? AND lesson_no = ?",
        (class_id, weekday, lesson_no),
    )
    if cur.rowcount:
        audit.log(conn, user, "delete", "schedule", class_id,
                  f"Постоянное расписание, {_cell_label(conn, class_id, weekday, lesson_no)}: урок убран")
        touch_updated(conn)
    return {"ok": True}


@router.put("/bells")
def set_bells(
    data: BellsIn,
    user: dict = Depends(security.admin_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    count = len(data.bells)
    used = conn.execute(
        "SELECT MAX(n) m FROM (SELECT MAX(lesson_no) n FROM schedule UNION ALL SELECT MAX(lesson_no) FROM changes "
        "UNION ALL SELECT MAX(move_to_lesson) FROM changes)"
    ).fetchone()["m"]
    if used and used > count:
        raise HTTPException(400, f"В расписании или заменах есть {used}-й урок — нельзя оставить только {count} звонков")
    conn.execute("DELETE FROM bells")
    conn.executemany(
        "INSERT INTO bells (lesson_no, start_time, end_time) VALUES (?, ?, ?)",
        [(b.lesson_no, b.start, b.end) for b in data.bells],
    )
    audit.log(conn, user, "update", "bells", None,
              "Расписание звонков: " + "; ".join(f"{b.lesson_no}) {b.start}–{b.end}" for b in data.bells))
    touch_updated(conn)
    return {"ok": True}


@router.put("/settings")
def set_settings(
    data: SettingsIn,
    user: dict = Depends(security.admin_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    set_setting(conn, "school_name", data.school_name)
    set_setting(conn, "school_days", ",".join(str(d) for d in data.school_days))
    days = ", ".join(WEEKDAYS[d][:2].lower() for d in data.school_days)
    audit.log(conn, user, "update", "settings", None, f"Настройки: «{data.school_name}», учебные дни: {days}")
    touch_updated(conn)
    return {"ok": True}


def _user_row(conn: sqlite3.Connection, user_id: int):
    row = conn.execute(
        "SELECT id, username, full_name, role, is_active, created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Пользователь не найден")
    return row


def _active_admins(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) c FROM users WHERE role = 'admin' AND is_active = 1").fetchone()["c"]


ROLE_LABELS = {"teacher": "учитель", "admin": "администратор"}


@router.get("/users")
def list_users(user: dict = Depends(security.admin_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT id, username, full_name, role, is_active, created_at FROM users ORDER BY full_name"
    ).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/users", status_code=201)
def create_user(
    data: UserCreateIn,
    user: dict = Depends(security.admin_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    try:
        cur = conn.execute(
            "INSERT INTO users (username, full_name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (data.username, data.full_name, security.hash_password(data.password), data.role, now_iso()),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, f"Логин «{data.username}» уже занят") from exc
    audit.log(conn, user, "create", "user", cur.lastrowid,
              f"Создан пользователь {data.username} ({data.full_name}), роль: {ROLE_LABELS[data.role]}")
    return dict(_user_row(conn, cur.lastrowid))


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    data: UserUpdateIn,
    user: dict = Depends(security.admin_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    old = _user_row(conn, user_id)
    if user_id == user["id"] and (data.role != "admin" or not data.is_active):
        raise HTTPException(400, "Нельзя снять с себя роль администратора или заблокировать себя")
    losing_admin = old["role"] == "admin" and old["is_active"] and (data.role != "admin" or not data.is_active)
    if losing_admin and _active_admins(conn) <= 1:
        raise HTTPException(400, "Должен остаться хотя бы один активный администратор")

    conn.execute(
        "UPDATE users SET full_name = ?, role = ?, is_active = ? WHERE id = ?",
        (data.full_name, data.role, int(data.is_active), user_id),
    )
    notes = [f"роль: {ROLE_LABELS[data.role]}", "активен" if data.is_active else "заблокирован"]
    if data.password:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (security.hash_password(data.password), user_id)
        )
        notes.append("пароль сброшен")
    if data.password or not data.is_active or data.role != old["role"]:
        security.delete_user_sessions(conn, user_id)
    audit.log(conn, user, "update", "user", user_id, f"Изменён пользователь {old['username']}: " + ", ".join(notes))
    return dict(_user_row(conn, user_id))


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    user: dict = Depends(security.admin_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    old = _user_row(conn, user_id)
    if user_id == user["id"]:
        raise HTTPException(400, "Нельзя удалить собственную учётную запись")
    if old["role"] == "admin" and old["is_active"] and _active_admins(conn) <= 1:
        raise HTTPException(400, "Должен остаться хотя бы один активный администратор")
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    audit.log(conn, user, "delete", "user", user_id, f"Удалён пользователь {old['username']} ({old['full_name']})")
    return {"ok": True}
