import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

FIELD_LABELS = {
    "username": "Логин",
    "password": "Пароль",
    "old_password": "Текущий пароль",
    "new_password": "Новый пароль",
    "full_name": "ФИО",
    "role": "Роль",
    "is_active": "Активен",
    "date": "Дата",
    "class_id": "Класс",
    "lesson_no": "Номер урока",
    "group_no": "Группа",
    "type": "Тип изменения",
    "new_subject_id": "Новый предмет",
    "new_teacher_id": "Новый учитель",
    "new_room_id": "Новый кабинет",
    "move_to_date": "Дата переноса",
    "move_to_lesson": "Урок переноса",
    "comment": "Комментарий",
    "name": "Название",
    "weekday": "День недели",
    "subject_id": "Предмет",
    "teacher_id": "Учитель",
    "room_id": "Кабинет",
    "school_name": "Название школы",
    "school_days": "Учебные дни",
    "bells": "Звонки",
    "start": "Начало урока",
    "end": "Конец урока",
}

ChangeType = Literal["teacher", "subject", "room", "cancel", "move"]
Role = Literal["teacher", "admin"]
Id = Field(gt=0)


def _clean(text: str) -> str:
    # Убираем управляющие символы, сохраняя переводы строк.
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text).strip()


class Strict(BaseModel):
    model_config = {"extra": "forbid"}


class LoginIn(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class PasswordChangeIn(Strict):
    old_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class ChangeIn(Strict):
    date: date
    class_id: int = Id
    lesson_no: int = Field(ge=1, le=12)
    group_no: int = Field(default=0, ge=0, le=2)
    type: ChangeType
    new_subject_id: Optional[int] = Field(default=None, gt=0)
    new_teacher_id: Optional[int] = Field(default=None, gt=0)
    new_room_id: Optional[int] = Field(default=None, gt=0)
    move_to_date: Optional[date] = None
    move_to_lesson: Optional[int] = Field(default=None, ge=1, le=12)
    comment: str = Field(default="", max_length=500)

    @field_validator("comment")
    @classmethod
    def _comment(cls, v: str) -> str:
        return _clean(v)

    @model_validator(mode="after")
    def _by_type(self):
        t = self.type
        if t == "teacher" and not self.new_teacher_id:
            raise ValueError("Для замены учителя выберите нового учителя")
        if t == "subject" and not self.new_subject_id:
            raise ValueError("Для замены предмета выберите новый предмет")
        if t == "room" and not self.new_room_id:
            raise ValueError("Для смены кабинета выберите новый кабинет")
        if t == "move":
            if not self.move_to_date or not self.move_to_lesson:
                raise ValueError("Для переноса укажите дату и номер урока, на который переносится урок")
            if self.move_to_date == self.date and self.move_to_lesson == self.lesson_no:
                raise ValueError("Перенос на то же самое время не имеет смысла")
        else:
            self.move_to_date = None
            self.move_to_lesson = None
        if t == "cancel":
            self.new_subject_id = self.new_teacher_id = self.new_room_id = None
        return self


class NameIn(Strict):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = re.sub(r"\s+", " ", _clean(v))
        if not v:
            raise ValueError("Название не может быть пустым")
        return v


class LessonPart(Strict):
    subject_id: int = Id
    teacher_id: Optional[int] = Field(default=None, gt=0)
    room_id: Optional[int] = Field(default=None, gt=0)


class ScheduleSlotIn(Strict):
    """Один урок в постоянном расписании: либо общий для класса (whole), либо по группам."""

    class_id: int = Id
    weekday: int = Field(ge=1, le=7)
    lesson_no: int = Field(ge=1, le=12)
    whole: Optional[LessonPart] = None
    group1: Optional[LessonPart] = None
    group2: Optional[LessonPart] = None

    @model_validator(mode="after")
    def _one_kind(self):
        if self.whole and (self.group1 or self.group2):
            raise ValueError("Урок должен быть либо общим для класса, либо разделён на группы")
        if not (self.whole or self.group1 or self.group2):
            raise ValueError("Выберите предмет")
        return self

    def parts(self) -> dict[int, LessonPart]:
        return {n: p for n, p in ((0, self.whole), (1, self.group1), (2, self.group2)) if p}


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class BellIn(Strict):
    lesson_no: int = Field(ge=1, le=12)
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _time(cls, v: str) -> str:
        v = v.strip()
        if len(v) == 4 and v[1] == ":":
            v = "0" + v
        if not _TIME_RE.match(v):
            raise ValueError("Время нужно указать в формате ЧЧ:ММ, например 08:30")
        return v

    @model_validator(mode="after")
    def _order(self):
        if self.start >= self.end:
            raise ValueError(f"Урок {self.lesson_no}: конец должен быть позже начала")
        return self


class BellsIn(Strict):
    bells: list[BellIn] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _sequence(self):
        nums = [b.lesson_no for b in self.bells]
        if sorted(nums) != list(range(1, len(nums) + 1)):
            raise ValueError("Уроки должны идти подряд, начиная с 1-го")
        ordered = sorted(self.bells, key=lambda b: b.lesson_no)
        for prev, cur in zip(ordered, ordered[1:]):
            if cur.start < prev.end:
                raise ValueError(f"Урок {cur.lesson_no} начинается раньше, чем закончился урок {prev.lesson_no}")
        self.bells = ordered
        return self


class SettingsIn(Strict):
    school_name: str = Field(min_length=1, max_length=150)
    school_days: list[int] = Field(min_length=1, max_length=7)

    @field_validator("school_name")
    @classmethod
    def _school_name(cls, v: str) -> str:
        v = _clean(v)
        if not v:
            raise ValueError("Укажите название школы")
        return v

    @field_validator("school_days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("Дни недели — числа от 1 (пн) до 7 (вс)")
        return sorted(set(v))


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


def check_username(v: str) -> str:
    v = v.strip()
    if not _USERNAME_RE.match(v):
        raise ValueError("Логин: 3–32 символа, только латинские буквы, цифры, точка, дефис и подчёркивание")
    return v


def check_full_name(v: str) -> str:
    v = re.sub(r"\s+", " ", _clean(v))
    if not v:
        raise ValueError("Укажите ФИО")
    return v


class UserCreateIn(Strict):
    username: str
    full_name: str = Field(min_length=1, max_length=100)
    role: Role
    password: str = Field(min_length=8, max_length=200)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return check_username(v)

    @field_validator("full_name")
    @classmethod
    def _full_name(cls, v: str) -> str:
        return check_full_name(v)


class UserUpdateIn(Strict):
    full_name: str = Field(min_length=1, max_length=100)
    role: Role
    is_active: bool
    password: Optional[str] = Field(default=None, min_length=8, max_length=200)

    @field_validator("full_name")
    @classmethod
    def _full_name(cls, v: str) -> str:
        return check_full_name(v)

    @field_validator("password", mode="before")
    @classmethod
    def _empty_password(cls, v):
        return v or None
