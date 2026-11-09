import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config
from .db import init_db
from .routes import admin, auth, changes, public
from .schemas import FIELD_LABELS

logger = logging.getLogger("school_schedule")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Школьное расписание", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


_ERROR_TEXT = {
    "missing": "обязательное поле",
    "int_parsing": "должно быть целым числом",
    "int_type": "должно быть целым числом",
    "bool_parsing": "должно быть да/нет",
    "date_parsing": "неверная дата",
    "date_from_datetime_parsing": "неверная дата",
    "date_type": "неверная дата",
    "string_type": "должно быть текстом",
    "literal_error": "недопустимое значение",
    "greater_than": "вне допустимого диапазона",
    "greater_than_equal": "вне допустимого диапазона",
    "less_than_equal": "вне допустимого диапазона",
    "extra_forbidden": "лишнее поле",
    "list_type": "должно быть списком",
    "json_invalid": "некорректный JSON",
}


def _error_message(err: dict) -> str:
    etype = err.get("type", "")
    ctx = err.get("ctx") or {}
    if etype == "value_error":
        return str(err.get("msg", "")).removeprefix("Value error, ")
    if etype == "string_too_short":
        text = "не заполнено" if ctx.get("min_length") == 1 else f"минимум {ctx.get('min_length')} символов"
    elif etype == "string_too_long":
        text = f"максимум {ctx.get('max_length')} символов"
    elif etype == "too_short":
        text = "нужно выбрать хотя бы одно значение"
    elif etype == "too_long":
        text = "слишком много значений"
    else:
        text = _ERROR_TEXT.get(etype, "заполнено неверно")
    field = next((str(p) for p in reversed(err.get("loc", ())) if isinstance(p, str) and p != "body"), None)
    label = FIELD_LABELS.get(field or "", field)
    return f"{label}: {text}" if label else text.capitalize()


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    messages = list(dict.fromkeys(_error_message(e) for e in exc.errors()))
    return JSONResponse(status_code=422, content={"detail": "; ".join(messages[:5])})


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if exc.status_code == 404 and detail == "Not Found":
        detail = "Страница не найдена"
    elif exc.status_code == 405:
        detail = "Метод не поддерживается"
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception("Необработанная ошибка: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера. Попробуйте ещё раз."})


app.include_router(public.router)
app.include_router(auth.router)
app.include_router(changes.router)
app.include_router(admin.router)

app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.api_route("/admin", methods=["GET", "HEAD"], include_in_schema=False)
def admin_page():
    return FileResponse(config.STATIC_DIR / "admin.html")
