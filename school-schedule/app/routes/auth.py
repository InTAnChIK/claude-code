import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import audit, config, security
from ..db import get_db
from ..schemas import LoginIn, PasswordChangeIn

router = APIRouter(prefix="/api/auth")


def _public_user(user: dict) -> dict:
    return {k: user[k] for k in ("id", "username", "full_name", "role")}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        security.SESSION_COOKIE,
        token,
        max_age=config.SESSION_HOURS * 3600,
        httponly=True,
        secure=security.cookie_secure(request),
        samesite="strict",
        path="/",
    )


@router.post("/login")
def login(
    data: LoginIn,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
):
    ip = _client_ip(request)
    wait = security.login_blocked_minutes(conn, data.username, ip)
    if wait:
        raise HTTPException(429, f"Слишком много неудачных попыток входа. Попробуйте через {wait} мин.")

    user = security.check_credentials(conn, data.username, data.password)
    if not user:
        security.record_login_failure(conn, data.username, ip)
        # Коммитим неудачную попытку сразу: исключение ниже откатило бы транзакцию.
        conn.commit()
        raise HTTPException(401, "Неверный логин или пароль")

    security.clear_login_failures(conn, data.username)
    token, csrf = security.create_session(conn, user["id"])
    _set_session_cookie(response, request, token)
    audit.log(conn, dict(user), "login", "user", user["id"], f"Вход в систему с адреса {ip}")
    return {"user": _public_user(dict(user)), "csrf_token": csrf}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: dict = Depends(security.current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    security.delete_session(conn, request.cookies.get(security.SESSION_COOKIE, ""))
    response.delete_cookie(security.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict | None = Depends(security.optional_user)):
    if not user:
        return {"user": None}
    return {"user": _public_user(user), "csrf_token": user["csrf_token"]}


@router.post("/password")
def change_password(
    data: PasswordChangeIn,
    request: Request,
    response: Response,
    user: dict = Depends(security.current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    if not security.check_credentials(conn, user["username"], data.old_password):
        raise HTTPException(400, "Текущий пароль указан неверно")
    if data.old_password == data.new_password:
        raise HTTPException(400, "Новый пароль должен отличаться от текущего")
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (security.hash_password(data.new_password), user["id"]),
    )
    security.delete_user_sessions(conn, user["id"])
    token, csrf = security.create_session(conn, user["id"])
    _set_session_cookie(response, request, token)
    audit.log(conn, user, "update", "user", user["id"], "Сменил свой пароль")
    return {"ok": True, "csrf_token": csrf}
