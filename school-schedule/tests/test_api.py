from datetime import timedelta

from app.schedule import today

from .conftest import make_client


def next_school_day(n=0):
    d, found = today(), []
    while len(found) <= n:
        if d.isoweekday() <= 5:
            found.append(d)
        d += timedelta(days=1)
    return found[n]


def meta(client):
    return client.get("/api/meta").json()


def id_of(items, name):
    return next(i["id"] for i in items if i["name"] == name)


# ---------- публичная часть ----------

def test_meta_and_schedule(anon):
    m = meta(anon)
    assert m["school_name"]
    assert [c["name"] for c in m["classes"]] == ["5А", "7Б", "9В"]
    assert len(m["bells"]) == 8
    r = anon.get("/api/schedule", params={"class_id": id_of(m["classes"], "5А"), "days": 7})
    assert r.status_code == 200
    days = r.json()["days"]
    assert len(days) == 7
    assert any(d["lessons"] for d in days)


def test_schedule_shows_seeded_changes(anon):
    statuses = set()
    for c in meta(anon)["classes"]:
        days = anon.get("/api/schedule", params={"class_id": c["id"], "days": 8}).json()["days"]
        statuses |= {e["status"] for d in days for e in d["lessons"]}
    assert {"teacher", "room", "cancel", "subject", "move_out", "move_in"} <= statuses


def test_bad_params_give_russian_errors(anon):
    r = anon.get("/api/schedule", params={"class_id": "abc"})
    assert r.status_code == 422
    assert "Класс" in r.json()["detail"]
    assert anon.get("/api/schedule", params={"class_id": 999}).json()["detail"] == "Класс не найден"


def test_security_headers(anon):
    r = anon.get("/")
    assert r.status_code == 200
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert anon.head("/").status_code == 200
    assert anon.get("/api/meta").headers["cache-control"] == "no-store"


# ---------- вход ----------

def test_login_wrong_password_and_lockout(anon):
    for _ in range(5):
        r = anon.post("/api/auth/login", json={"username": "teacher", "password": "wrong-password"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Неверный логин или пароль"
    r = anon.post("/api/auth/login", json={"username": "teacher", "password": "teacher-pass-123"})
    assert r.status_code == 429
    assert "Попробуйте через" in r.json()["detail"]


def test_unknown_user_same_error(anon):
    r = anon.post("/api/auth/login", json={"username": "nobody", "password": "whatever1"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Неверный логин или пароль"


def test_login_cookie_and_logout(teacher):
    me = teacher.get("/api/auth/me").json()
    assert me["user"]["username"] == "teacher"
    assert teacher.post("/api/auth/logout").status_code == 200
    assert teacher.get("/api/auth/me").json()["user"] is None


def test_csrf_required(teacher):
    teacher.headers.pop("X-CSRF-Token")
    r = teacher.post("/api/staff/changes", json={})
    assert r.status_code == 403


def test_staff_endpoints_require_login(anon):
    assert anon.get("/api/staff/changes").status_code == 401
    assert anon.post("/api/admin/dict/classes", json={"name": "6А"}).status_code == 401


def test_change_password(teacher):
    r = teacher.post("/api/auth/password", json={"old_password": "bad", "new_password": "new-pass-789"})
    assert r.status_code == 400
    r = teacher.post("/api/auth/password", json={"old_password": "teacher-pass-123", "new_password": "new-pass-789"})
    assert r.status_code == 200
    teacher.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert teacher.get("/api/auth/me").json()["user"]["username"] == "teacher"
    fresh = make_client()
    assert fresh.post("/api/auth/login", json={"username": "teacher", "password": "new-pass-789"}).status_code == 200


# ---------- замены ----------

def change_payload(client, **overrides):
    m = meta(client)
    day = next_school_day(1)
    payload = {
        "date": day.isoformat(),
        "class_id": id_of(m["classes"], "7Б"),
        "lesson_no": 2,
        "type": "teacher",
        "new_teacher_id": id_of(m["teachers"], "Орлов Виктор Семёнович"),
        "comment": "Болезнь <script>alert(1)</script>",
    }
    payload.update(overrides)
    return payload


def test_teacher_creates_edits_deletes_own_change(teacher, anon):
    before = meta(anon)["last_updated"]
    r = teacher.post("/api/staff/changes", json=change_payload(teacher))
    assert r.status_code == 201, r.text
    change = r.json()
    assert change["can_edit"] and change["created_by_name"] == "Тест teacher"
    assert meta(anon)["last_updated"] >= before

    days = anon.get("/api/schedule", params={"class_id": change["class_id"], "days": 8}).json()["days"]
    assert any(e["change_id"] == change["id"] for d in days for e in d["lessons"])

    r = teacher.put(f"/api/staff/changes/{change['id']}", json=change_payload(teacher, type="cancel", comment="Отмена"))
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "cancel" and r.json()["new_teacher_id"] is None

    assert teacher.delete(f"/api/staff/changes/{change['id']}").status_code == 200
    log = teacher.get("/api/staff/audit").json()["items"]
    assert [e["action"] for e in log[:3]] == ["delete", "update", "create"]
    assert all(e["entity"] == "change" for e in log)


def test_teacher_cannot_edit_others_change_but_admin_can(teacher, teacher2, admin):
    change = teacher.post("/api/staff/changes", json=change_payload(teacher)).json()
    assert teacher2.delete(f"/api/staff/changes/{change['id']}").status_code == 403
    assert admin.delete(f"/api/staff/changes/{change['id']}").status_code == 200


def test_duplicate_change_rejected(teacher):
    assert teacher.post("/api/staff/changes", json=change_payload(teacher)).status_code == 201
    r = teacher.post("/api/staff/changes", json=change_payload(teacher, type="cancel"))
    assert r.status_code == 409
    assert "уже внесено изменение" in r.json()["detail"]


def test_change_validation_messages(teacher):
    r = teacher.post("/api/staff/changes", json=change_payload(teacher, new_teacher_id=None))
    assert r.status_code == 422
    assert r.json()["detail"] == "Для замены учителя выберите нового учителя"

    past = (today() - timedelta(days=1)).isoformat()
    r = teacher.post("/api/staff/changes", json=change_payload(teacher, date=past))
    assert "прошедшие даты" in r.json()["detail"]

    r = teacher.post("/api/staff/changes", json=change_payload(teacher, lesson_no=8))
    assert r.status_code == 400 and "нет 8-го урока" in r.json()["detail"]

    r = teacher.post("/api/staff/changes", json=change_payload(teacher, date="31.12.2026"))
    assert r.status_code == 422 and r.json()["detail"].startswith("Дата:")


def test_move_into_busy_slot_rejected(teacher):
    day = next_school_day(1)
    r = teacher.post(
        "/api/staff/changes",
        json=change_payload(teacher, type="move", move_to_date=day.isoformat(), move_to_lesson=3, new_teacher_id=None),
    )
    assert r.status_code == 400
    assert "уже есть урок" in r.json()["detail"]
    r = teacher.post(
        "/api/staff/changes",
        json=change_payload(teacher, type="move", move_to_date=day.isoformat(), move_to_lesson=8, new_teacher_id=None),
    )
    assert r.status_code == 201, r.text


def test_teacher_cannot_use_admin_api(teacher):
    assert teacher.post("/api/admin/dict/classes", json={"name": "6А"}).status_code == 403
    assert teacher.get("/api/admin/users").status_code == 403


# ---------- администрирование ----------

def test_admin_dictionaries_and_schedule(admin, anon):
    r = admin.post("/api/admin/dict/classes", json={"name": "  6А  "})
    assert r.status_code == 201 and r.json()["name"] == "6А"
    class_id = r.json()["id"]
    assert admin.post("/api/admin/dict/classes", json={"name": "6а"}).status_code == 409

    m = meta(admin)
    cell = {"class_id": class_id, "weekday": 1, "lesson_no": 1,
            "subject_id": id_of(m["subjects"], "Математика"), "teacher_id": None, "room_id": None}
    assert admin.put("/api/admin/schedule", json=cell).status_code == 200
    cells = admin.get("/api/admin/schedule", params={"class_id": class_id}).json()["cells"]
    assert len(cells) == 1

    subject_id = id_of(m["subjects"], "Математика")
    r = admin.delete(f"/api/admin/dict/subjects/{subject_id}")
    assert r.status_code == 409 and "Нельзя удалить" in r.json()["detail"]

    assert [c["name"] for c in meta(anon)["classes"]] == ["5А", "6А", "7Б", "9В"]


def test_admin_bells_and_settings(admin):
    bells = [{"lesson_no": 1, "start": "8:30", "end": "09:15"}, {"lesson_no": 2, "start": "09:00", "end": "09:45"}]
    r = admin.put("/api/admin/bells", json={"bells": bells})
    assert r.status_code == 422 and "раньше" in r.json()["detail"]
    r = admin.put("/api/admin/bells", json={"bells": bells[:1]})
    assert r.status_code == 400  # в расписании есть уроки после 1-го

    r = admin.put("/api/admin/settings", json={"school_name": "Гимназия № 5", "school_days": [6, 1, 2, 3, 4, 5]})
    assert r.status_code == 200
    m = meta(admin)
    assert m["school_name"] == "Гимназия № 5" and m["school_days"] == [1, 2, 3, 4, 5, 6]


def test_admin_users(admin):
    r = admin.post("/api/admin/users", json={"username": "новый", "full_name": "Х", "role": "teacher", "password": "12345678"})
    assert r.status_code == 422 and "Логин" in r.json()["detail"]
    r = admin.post("/api/admin/users", json={"username": "petrov", "full_name": "Петров П. П.", "role": "teacher", "password": "short"})
    assert r.status_code == 422 and "Пароль" in r.json()["detail"]
    r = admin.post("/api/admin/users", json={"username": "petrov", "full_name": "Петров П. П.", "role": "teacher", "password": "petrov-pass"})
    assert r.status_code == 201
    uid = r.json()["id"]

    new_client = make_client()
    assert new_client.post("/api/auth/login", json={"username": "petrov", "password": "petrov-pass"}).status_code == 200
    r = admin.put(f"/api/admin/users/{uid}", json={"full_name": "Петров П. П.", "role": "teacher", "is_active": False})
    assert r.status_code == 200
    assert new_client.get("/api/auth/me").json()["user"] is None  # сессии заблокированного удалены

    me = admin.get("/api/auth/me").json()["user"]
    r = admin.put(f"/api/admin/users/{me['id']}", json={"full_name": "X", "role": "teacher", "is_active": True})
    assert r.status_code == 400
    assert admin.delete(f"/api/admin/users/{me['id']}").status_code == 400

    audit = admin.get("/api/staff/audit").json()["items"]
    assert any(e["entity"] == "user" for e in audit)
