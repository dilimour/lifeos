"""Импорт PDF-выписки Т-Банка: pdftotext → операции → категории → tx."""
import hashlib
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime

from . import db
from .util import rub

LINE = re.compile(
    r"^\s*(\d\d\.\d\d\.\d\d)(?:\s+(\d\d:\d\d))?\s+(\d\d\.\d\d\.\d\d)\s+(.+?)\s{2,}"
    r"(\+?\s?[\d ]+\.\d\d) ₽\s+(\+?\s?[\d ]+\.\d\d) ₽\s*$"
)
SKIP = re.compile(r"Дата и время|операции|обработки|Описание|Страница|\bВыписка\b|Баланс|АО «ТБанк»|Расходы|Поступления")


def pdf_to_text(path: str) -> str:
    return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True).stdout


def parse(text: str) -> list[dict]:
    """Строки выписки → операции. Вторая строка описания (телефон, город) приклеивается."""
    rows, last = [], None
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            d, t, _, desc, a, _ = m.groups()
            sign = 1 if a.strip().startswith("+") else -1
            last = {"date": d, "time": t or "", "desc": desc.strip(),
                    "amount": sign * float(a.replace("+", "").replace(" ", ""))}
            rows.append(last)
        elif last and line.strip() and not SKIP.search(line) \
                and len(line) - len(line.lstrip()) > 20 and len(line.strip()) < 60:
            last["desc"] += " " + line.strip()
            last = None
        elif line.strip():
            last = None
    return rows


def categorize(op: dict, rules: list, own_phone: str | None, mortgage_min: float) -> str:
    d, a = op["desc"], op["amount"]
    if a > 0:
        if "договор" in d or "Перевод себе" in d:
            return "Свои счета"
        return "Доход"
    if own_phone and own_phone in d:
        return "Ипотека" if -a >= mortgage_min else "Свои счета"
    if "договор" in d:
        return "Свои счета"
    up = d.upper()
    for pattern, cat in rules:
        if pattern.upper() in up:
            return cat
    if "по номеру телефона" in d or "Внешний банковский" in d:
        return "Переводы"
    if "Снятие наличных" in d:
        return "Наличные"
    return "Прочее"


def op_hash(op: dict) -> str:
    return hashlib.sha1(f"{op['date']}|{op['time']}|{op['amount']:.2f}|{op['desc']}".encode()).hexdigest()


async def import_ops(ctx, ops: list[dict]) -> str:
    fin = ctx.cfg.section("finance")
    rules = fin.get("import_rules") or []
    own_phone = os.environ.get("LIFEOS_OWN_PHONE") or None
    mortgage_min = float(fin.get("mortgage_min_transfer", 18000))
    added, dup = 0, 0
    by_cat: dict[str, float] = defaultdict(float)
    unknown: Counter = Counter()
    dates = []
    for op in ops:
        cat = categorize(op, rules, own_phone, mortgage_min)
        dt = datetime.strptime(f"{op['date']} {op['time'] or '12:00'}", "%d.%m.%y %H:%M").replace(tzinfo=ctx.cfg.tz)
        dates.append(dt)
        cur = await ctx.db.execute(
            "insert into tx (ts, amount, category, note, source, ext_hash) values (%s, %s, %s, %s, 'import', %s) "
            "on conflict (ext_hash) do nothing", (dt, op["amount"], cat, op["desc"][:200], op_hash(op)))
        if cur.rowcount:
            added += 1
            if op["amount"] < 0:
                by_cat[cat] += -op["amount"]
            if cat == "Прочее":
                unknown[re.sub(r"\d{3,}", "", op["desc"])[:40]] += 1
        else:
            dup += 1
    if not ops:
        return "В файле не нашёл операций. Это точно выписка Т-Банка в PDF?"
    lines = [f"📄 Импорт: {added} новых операций, {dup} уже были. Период {min(dates):%d.%m.%Y} — {max(dates):%d.%m.%Y}."]
    for cat, s in sorted(by_cat.items(), key=lambda x: -x[1])[:12]:
        lines.append(f"• {cat}: {rub(s)}")
    if unknown:
        lines.append("Не распознал (добавь правила в config.yaml → finance.import_rules):")
        lines += [f"  – {name} ×{n}" for name, n in unknown.most_common(8)]
    return "\n".join(lines)
