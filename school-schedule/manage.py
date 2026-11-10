#!/usr/bin/env python3
"""Служебные команды: python manage.py <команда>. Справка: python manage.py --help"""

import argparse
import getpass
import sys

from pydantic import ValidationError

from app import audit, security
from app.db import connection, init_db, now_iso
from app.schemas import UserCreateIn, check_full_name, check_username


def ask_password() -> str:
    while True:
        first = getpass.getpass("Пароль (минимум 8 символов, ввод не отображается): ")
        if len(first) < 8:
            print("Пароль слишком короткий.")
            continue
        if first != getpass.getpass("Повторите пароль: "):
            print("Пароли не совпадают, попробуйте ещё раз.")
            continue
        return first


def cmd_init_db(args) -> None:
    init_db()
    print("База данных готова.")


def cmd_seed(args) -> None:
    from app.seed import seed

    init_db()
    with connection() as conn:
        try:
            seed(conn)
        except RuntimeError as exc:
            sys.exit(str(exc))
    print("Пример данных загружен: классы 5А, 7Б, 9В, неделя расписания и несколько замен.")


def cmd_create_admin(args) -> None:
    role = "admin"
    init_db()
    username = args.username or input("Логин (латиница, цифры, . _ -): ").strip()
    full_name = args.name or input("ФИО: ").strip()
    try:
        check_username(username)
        check_full_name(full_name)
    except ValueError as exc:
        sys.exit(f"Ошибка: {exc}")
    password = ask_password()
    try:
        data = UserCreateIn(username=username, full_name=full_name, role=role, password=password)
    except ValidationError as exc:
        sys.exit("Ошибка: " + "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors()))
    with connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (data.username,)).fetchone():
            sys.exit(f"Логин «{data.username}» уже занят.")
        cur = conn.execute(
            "INSERT INTO users (username, full_name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (data.username, data.full_name, security.hash_password(data.password), role, now_iso()),
        )
        audit.log(conn, None, "create", "user", cur.lastrowid,
                  f"Создан пользователь {data.username} ({data.full_name}) из командной строки, роль: {role}")
    print(f"Готово: администратор «{data.username}» создан. Вход: /admin")


def cmd_reset_password(args) -> None:
    init_db()
    with connection() as conn:
        user = conn.execute("SELECT id FROM users WHERE username = ?", (args.username,)).fetchone()
        if not user:
            sys.exit(f"Пользователь «{args.username}» не найден.")
        password = ask_password()
        conn.execute(
            "UPDATE users SET password_hash = ?, is_active = 1 WHERE id = ?",
            (security.hash_password(password), user["id"]),
        )
        security.delete_user_sessions(conn, user["id"])
        conn.execute("DELETE FROM login_failures WHERE key = ?", (f"user:{args.username.lower()}",))
        audit.log(conn, None, "update", "user", user["id"], f"Пароль пользователя {args.username} сброшен из командной строки")
    print("Пароль изменён, пользователь разблокирован.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Управление сайтом школьного расписания")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="создать пустую базу данных").set_defaults(func=cmd_init_db)
    sub.add_parser("seed", help="загрузить пример данных (только в пустую базу)").set_defaults(func=cmd_seed)

    p = sub.add_parser("create-admin", help="создать администратора (завуча)")
    p.add_argument("--username")
    p.add_argument("--name", help="ФИО")
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("reset-password", help="задать новый пароль пользователю и снять блокировку")
    p.add_argument("--username", required=True)
    p.set_defaults(func=cmd_reset_password)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
