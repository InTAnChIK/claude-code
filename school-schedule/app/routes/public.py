import sqlite3
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import config
from ..db import get_db, get_setting, school_days
from ..schedule import CHANGE_TYPES, bells, class_sort_key, filter_by, merged_range, today

router = APIRouter(prefix="/api")


def _names(conn: sqlite3.Connection, table: str) -> list[dict]:
    rows = [dict(r) for r in conn.execute(f"SELECT id, name FROM {table}")]  # table — константа из кода
    key = (lambda r: class_sort_key(r["name"])) if table == "classes" else (lambda r: r["name"].lower())
    return sorted(rows, key=key)


def _start_date(start: Optional[date]) -> date:
    start = start or today()
    if abs((start - today()).days) > config.MAX_DAYS_AHEAD:
        raise HTTPException(400, "Дата слишком далеко от сегодняшней")
    return start


def _require_exists(conn: sqlite3.Connection, table: str, item_id: int, label: str) -> None:
    if not conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (item_id,)).fetchone():
        raise HTTPException(404, f"{label} не найден")


@router.get("/meta")
def meta(conn: sqlite3.Connection = Depends(get_db)):
    return {
        "school_name": get_setting(conn, "school_name"),
        "school_days": school_days(conn),
        "bells": [{"lesson_no": n, **b} for n, b in bells(conn).items()],
        "classes": _names(conn, "classes"),
        "teachers": _names(conn, "teachers"),
        "subjects": _names(conn, "subjects"),
        "rooms": _names(conn, "rooms"),
        "today": today().isoformat(),
        "last_updated": get_setting(conn, "last_updated"),
        "change_types": CHANGE_TYPES,
    }


@router.get("/schedule")
def schedule(
    class_id: int = Query(gt=0),
    start: Optional[date] = None,
    days: int = Query(default=1, ge=1, le=14),
    conn: sqlite3.Connection = Depends(get_db),
):
    _require_exists(conn, "classes", class_id, "Класс")
    return {
        "days": merged_range(conn, _start_date(start), days, class_id),
        "last_updated": get_setting(conn, "last_updated"),
    }


@router.get("/search")
def search(
    teacher_id: Optional[int] = Query(default=None, gt=0),
    room_id: Optional[int] = Query(default=None, gt=0),
    start: Optional[date] = None,
    days: int = Query(default=1, ge=1, le=14),
    conn: sqlite3.Connection = Depends(get_db),
):
    if bool(teacher_id) == bool(room_id):
        raise HTTPException(400, "Выберите учителя или кабинет")
    if teacher_id:
        _require_exists(conn, "teachers", teacher_id, "Учитель")
        field, value = "teacher", teacher_id
    else:
        _require_exists(conn, "rooms", room_id, "Кабинет")
        field, value = "room", room_id
    result = merged_range(conn, _start_date(start), days)
    for day in result:
        day["lessons"] = filter_by(day["lessons"], field, value)
    return {"days": result, "last_updated": get_setting(conn, "last_updated")}


@router.get("/changes")
def changes_feed(
    class_id: Optional[int] = Query(default=None, gt=0),
    conn: sqlite3.Connection = Depends(get_db),
):
    if class_id:
        _require_exists(conn, "classes", class_id, "Класс")
    days = merged_range(conn, today(), config.CHANGES_FEED_DAYS, class_id)
    feed = []
    for day in days:
        items = [e for e in day["lessons"] if e["status"] != "normal"]
        if items:
            feed.append({"date": day["date"], "weekday": day["weekday"], "items": items})
    return {"days": feed, "last_updated": get_setting(conn, "last_updated")}
