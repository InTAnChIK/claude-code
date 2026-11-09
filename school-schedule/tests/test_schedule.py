from datetime import timedelta

from app.db import connection
from app.schedule import merged_day, today
from app.seed import CLASSES, WEEK


def test_seed_has_no_teacher_double_booking():
    for weekday, lessons in WEEK.items():
        for lesson_no, line in enumerate(lessons, start=1):
            teachers = [cell.split()[1] for cell in line.split("|") if cell.strip() != "-"]
            assert len(teachers) == len(set(teachers)), (weekday, lesson_no, teachers)
            assert len(line.split("|")) == len(CLASSES)


def _class_id(conn, name):
    return conn.execute("SELECT id FROM classes WHERE name = ?", (name,)).fetchone()["id"]


def _next_school_day(d, n=0):
    days = []
    while len(days) <= n:
        if d.isoweekday() <= 5:
            days.append(d)
        d += timedelta(days=1)
    return days[n]


def test_seed_changes_are_applied():
    day0, day1 = _next_school_day(today()), _next_school_day(today(), 1)
    with connection() as conn:
        lessons = merged_day(conn, day0, _class_id(conn, "5А"))
        second = next(e for e in lessons if e["lesson_no"] == 2)
        assert second["status"] == "teacher"
        assert second["teacher"] == "Новикова Татьяна Юрьевна"
        assert second["orig"]["teacher"] != second["teacher"]

        cancelled = next(e for e in merged_day(conn, day1, _class_id(conn, "9В")) if e["lesson_no"] == 1)
        assert cancelled["status"] == "cancel"

        lessons_5a = merged_day(conn, day1, _class_id(conn, "5А"))
        out = next(e for e in lessons_5a if e["status"] == "move_out")
        incoming = next(e for e in lessons_5a if e["status"] == "move_in")
        assert out["lesson_no"] == 1
        assert incoming["lesson_no"] == out["move"]["lesson_no"]
        assert incoming["subject"] == out["subject"]


def test_past_changes_are_hidden():
    yesterday = today() - timedelta(days=1)
    with connection() as conn:
        cid = _class_id(conn, "5А")
        lesson = conn.execute(
            "SELECT lesson_no FROM schedule WHERE class_id = ? AND weekday = ? LIMIT 1", (cid, yesterday.isoweekday())
        ).fetchone()
        conn.execute(
            "INSERT INTO changes (date, class_id, lesson_no, type, comment, created_at, updated_at) "
            "VALUES (?, ?, ?, 'cancel', '', '', '')",
            (yesterday.isoformat(), cid, lesson["lesson_no"] if lesson else 1),
        )
        assert all(e["status"] == "normal" for e in merged_day(conn, yesterday, cid))
