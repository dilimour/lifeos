"""Разбор чисел и форматирование ответов."""
import html
import re
from datetime import date, datetime

NUM = r"\d[\d\s]*(?:[.,]\d{1,2})?"

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def to_float(s: str) -> float:
    return float(s.replace(" ", "").replace(" ", "").replace(",", "."))


def rub(x: float) -> str:
    """12345.6 -> '12 346 ₽'"""
    return f"{round(x):,}".replace(",", " ") + " ₽"


def kg(x: float) -> str:
    return f"{x:.1f}".replace(".", ",") + " кг"


def pct(part: float, whole: float) -> str:
    return f"{(part / whole * 100):.0f}%" if whole else "—"


def human_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()].capitalize()}, {d.day} {MONTHS_GEN[d.month - 1]}"


def minutes_h(m: int) -> str:
    h, mm = divmod(int(m), 60)
    return f"{h} ч {mm:02d} м" if h else f"{mm} м"


def parse_duration(s: str) -> int | None:
    """'45', '45м', '1ч', '1ч30', '1.5ч', '90 мин' -> минуты."""
    s = s.strip().lower().replace(",", ".")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*ч(?:ас(?:а|ов)?)?\s*(\d+)?\s*(?:м|мин)?", s)
    if m:
        return int(float(m.group(1)) * 60 + int(m.group(2) or 0))
    m = re.fullmatch(r"(\d+)\s*(?:м|мин|минут)?", s)
    if m:
        return int(m.group(1))
    return None


def to_html(text: str) -> str:
    """Мини-разметка: **жирный**, переносы строк."""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t.replace("\n", "<br>")


def strip_md(text: str) -> str:
    return text.replace("**", "")


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end
