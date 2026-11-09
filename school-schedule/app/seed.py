"""Пример данных: 3 класса, неделя постоянного расписания и несколько замен на ближайшие дни."""

import sqlite3
from datetime import date, timedelta

from . import audit
from .db import now_iso, set_setting, touch_updated
from .schedule import base_lesson, today

BELLS = [
    (1, "08:30", "09:15"),
    (2, "09:25", "10:10"),
    (3, "10:30", "11:15"),
    (4, "11:35", "12:20"),
    (5, "12:30", "13:15"),
    (6, "13:25", "14:10"),
    (7, "14:20", "15:05"),
    (8, "15:15", "16:00"),
]

# Учитель → (полное имя, свой кабинет)
TEACHERS = {
    "Iv": ("Иванова Мария Петровна", "201"),
    "Sm": ("Смирнова Ольга Викторовна", "202"),
    "Ku": ("Кузнецова Анна Сергеевна", "301"),
    "Po": ("Попов Дмитрий Александрович", "302"),
    "So": ("Соколова Елена Игоревна", "204"),
    "Le": ("Лебедев Андрей Николаевич", "205"),
    "No": ("Новикова Татьяна Юрьевна", "206"),
    "Ko": ("Козлова Наталья Владимировна", "303"),
    "Mo": ("Морозов Сергей Павлович", "304"),
    "Vo": ("Волков Алексей Игоревич", "305"),
    "Pa": ("Павлов Игорь Олегович", "Спортзал"),
    "Fe": ("Фёдорова Светлана Андреевна", "102"),
    "Or": ("Орлов Виктор Семёнович", "Мастерская"),
}
# Английский в 7Б идёт по группам: вторую группу ведёт отдельный учитель.
SECOND_ENGLISH = ("Белова Анна Дмитриевна", "207")

SUBJECTS = {
    "R": "Русский язык", "L": "Литература", "M": "Математика", "A": "Алгебра",
    "G": "Геометрия", "E": "Английский язык", "H": "История", "O": "Обществознание",
    "Ge": "География", "B": "Биология", "P": "Физика", "C": "Химия", "I": "Информатика",
    "F": "Физкультура", "Mu": "Музыка", "Iz": "ИЗО", "T": "Технология", "Ob": "ОБЗР",
}

EXTRA_ROOMS = ["Актовый зал"]

# Неделя: день → урок → (5А, 7Б, 9В); каждая ячейка «Предмет Учитель». Учителя за один урок не пересекаются.
WEEK = {
    1: ["R Iv | A Po | H Le", "M Ku | R Iv | E So", "E So | H Le | A Ku", "L Iv | E So | R Sm",
        "F Pa | P Mo | G Ku", "- | F Pa | C Ko", "- | - | F Pa"],
    2: ["M Ku | R Iv | B Ko", "R Iv | A Po | P Mo", "H Le | B Ko | A Ku", "B Ko | Ge No | E So",
        "Iz Fe | E So | L Sm", "- | I Vo | O Le", "- | - | I Vo"],
    3: ["R Iv | P Mo | G Ku", "M Ku | L Iv | R Sm", "L Iv | A Po | Ge No", "E So | F Pa | P Mo",
        "T Or | O Le | E So", "T Or | Mu Fe | Ob Pa"],
    4: ["M Ku | E So | R Sm", "R Iv | G Po | B Ko", "Ge No | R Iv | A Ku", "F Pa | A Po | H Le",
        "Mu Fe | B Ko | P Mo", "- | T Or | F Pa", "- | T Or | -"],
    5: ["R Iv | H Le | E So", "M Ku | E So | L Sm", "E So | R Iv | G Ku", "H Le | L Iv | C Ko",
        "L Iv | F Pa | I Vo", "- | Ge No | O Le", "- | - | F Pa"],
}
CLASSES = ["5А", "7Б", "9В"]


def _ids(conn: sqlite3.Connection, table: str) -> dict[str, int]:
    return {r["name"]: r["id"] for r in conn.execute(f"SELECT id, name FROM {table}")}


def _next_school_day(d: date, days: set[int]) -> date:
    while d.isoweekday() not in days:
        d += timedelta(days=1)
    return d


def seed(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM classes LIMIT 1").fetchone():
        raise RuntimeError("В базе уже есть данные — пример не загружен, чтобы ничего не перезаписать.")

    set_setting(conn, "school_name", "МБОУ «Средняя школа № 1»")
    set_setting(conn, "school_days", "1,2,3,4,5")
    conn.execute("DELETE FROM bells")
    conn.executemany("INSERT INTO bells (lesson_no, start_time, end_time) VALUES (?, ?, ?)", BELLS)

    conn.executemany("INSERT INTO classes (name) VALUES (?)", [(c,) for c in CLASSES])
    conn.executemany(
        "INSERT INTO teachers (name) VALUES (?)", [(t[0],) for t in TEACHERS.values()] + [(SECOND_ENGLISH[0],)]
    )
    conn.executemany("INSERT INTO subjects (name) VALUES (?)", [(s,) for s in SUBJECTS.values()])
    rooms = sorted({t[1] for t in TEACHERS.values()} | set(EXTRA_ROOMS) | {SECOND_ENGLISH[1]})
    conn.executemany("INSERT INTO rooms (name) VALUES (?)", [(r,) for r in rooms])

    class_ids, teacher_ids = _ids(conn, "classes"), _ids(conn, "teachers")
    subject_ids, room_ids = _ids(conn, "subjects"), _ids(conn, "rooms")

    rows = []
    for weekday, lessons in WEEK.items():
        for lesson_no, line in enumerate(lessons, start=1):
            for class_name, cell in zip(CLASSES, line.split("|")):
                cell = cell.strip()
                if cell == "-":
                    continue
                subj, teacher = cell.split()
                full_name, room = TEACHERS[teacher]
                slot = (class_ids[class_name], weekday, lesson_no)
                lesson = (subject_ids[SUBJECTS[subj]], teacher_ids[full_name], room_ids[room])
                if class_name == "7Б" and subj == "E":
                    second = (lesson[0], teacher_ids[SECOND_ENGLISH[0]], room_ids[SECOND_ENGLISH[1]])
                    rows += [(*slot, 1, *lesson), (*slot, 2, *second)]
                else:
                    rows.append((*slot, 0, *lesson))
    conn.executemany(
        "INSERT INTO schedule (class_id, weekday, lesson_no, group_no, subject_id, teacher_id, room_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )

    work_days = set(WEEK)
    day0 = _next_school_day(today(), work_days)
    day1 = _next_school_day(day0 + timedelta(days=1), work_days)
    last_5a = max(n for n in range(1, 9) if base_lesson(conn, class_ids["5А"], day1, n))

    T = lambda key: teacher_ids[TEACHERS[key][0]]  # noqa: E731
    changes = [
        (day0, "5А", 2, "teacher", None, T("No"), None, None, None, "Кузнецова А. С. на курсах повышения квалификации"),
        (day0, "7Б", 3, "room", None, None, room_ids["Актовый зал"], None, None, "В кабинете ремонт"),
        (day1, "9В", 1, "cancel", None, None, None, None, None, "Приходить ко 2-му уроку"),
        (day1, "7Б", 3, "subject", subject_ids["Информатика"], T("Vo"), room_ids["305"], None, None, ""),
        (day1, "5А", 1, "move", None, None, None, day1, last_5a + 1, "Урок перенесён в конец дня"),
    ]
    ts = now_iso()
    for d, cls, n, typ, subj, teacher, room, mdate, mlesson, comment in changes:
        cur = conn.execute(
            "INSERT INTO changes (date, class_id, lesson_no, type, new_subject_id, new_teacher_id, new_room_id, "
            "move_to_date, move_to_lesson, comment, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (d.isoformat(), class_ids[cls], n, typ, subj, teacher, room,
             mdate.isoformat() if mdate else None, mlesson, comment, ts, ts),
        )
        audit.log(conn, None, "create", "change", cur.lastrowid, f"Пример данных: {cls}, {d.isoformat()}, {n}-й урок")
    touch_updated(conn)
