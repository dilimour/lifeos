"""Комната «Финансы»: расходы, бюджет, копилка, импорт выписок."""
import re
from datetime import timedelta

from .. import db
from ..util import NUM, month_bounds, pct, rub, to_float

KEY = "finance"
HELP = """**Финансы — как пользоваться**
`450 кафе обед` — расход (категория по первому слову)
`+98000 зарплата` — доход
`бюджет` — расходы за месяц против лимитов
`копилка 15000` — отложить на цель, `копилка` — прогресс
`категории` — список категорий и слов
`отмена` — удалить последнюю запись
PDF-выписку Т-Банка просто перетащи сюда — импортирую сам.
Совет: карту ведёт импорт выписок, вручную вноси только наличные."""

AMOUNT_RE = re.compile(rf"^([+-]?)\s*({NUM})\s*(?:р|₽|руб\.?)?(?:\s+(.*))?$", re.I)


def _cats(cfg) -> dict[str, list[str]]:
    return cfg.section("finance").get("categories") or {}


def match_category(cfg, words: str) -> tuple[str | None, str]:
    """Первое слово (или фраза) -> категория. Возвращает (категория, остаток)."""
    words = (words or "").strip()
    if not words:
        return None, ""
    first, _, rest = words.partition(" ")
    f = first.lower()
    for cat, aliases in _cats(cfg).items():
        names = [cat.lower()] + [a.lower() for a in aliases or []]
        if any(f == n or (len(f) >= 4 and n.startswith(f)) or (len(n) >= 4 and f.startswith(n)) for n in names):
            return cat, rest
    return None, words


async def handle(ctx, text: str) -> str | None:
    t = text.strip()
    low = t.lower()
    if low in ("помощь", "?", "help"):
        return HELP
    if low in ("бюджет", "месяц"):
        return await budget_report(ctx)
    if low == "категории":
        return "\n".join(f"**{c}**: {', '.join(a or [])}" for c, a in _cats(ctx.cfg).items()) or "Категории не заданы в config.yaml"
    if low == "отмена":
        return await undo(ctx)
    if low.startswith("копилка"):
        return await savings(ctx, t[len("копилка"):].strip())

    m = AMOUNT_RE.match(t)
    if not m:
        return None
    sign, num, rest = m.groups()
    amount = to_float(num)
    if sign == "+":
        row = await db.one(ctx.db, "insert into tx (ts, amount, category, note) values (%s, %s, 'Доход', %s) returning id",
                           ctx.now(), amount, rest)
        ctx.last[KEY] = ("tx", row["id"])
        return f"➕ Доход {rub(amount)} записан."
    cat, note = match_category(ctx.cfg, rest)
    unknown = cat is None
    cat = cat or "Прочее"
    row = await db.one(ctx.db, "insert into tx (ts, amount, category, note) values (%s, %s, %s, %s) returning id",
                       ctx.now(), -amount, cat, note or None)
    ctx.last[KEY] = ("tx", row["id"])
    spent, limit = await month_spent(ctx, cat)
    tail = f" В категории за месяц {rub(spent)}" + (f" из {rub(limit)} ({pct(spent, limit)})" if limit else "") + "."
    hint = "\nКатегорию не узнал — записал в «Прочее». Добавь слово в config.yaml." if unknown else ""
    return f"➖ {rub(amount)} · {cat}.{tail}{hint}"


async def undo(ctx) -> str:
    last = ctx.last.pop(KEY, None)
    if not last:
        return "Нечего отменять."
    table, rid = last
    await ctx.db.execute(f"delete from {table} where id = %s", (rid,))
    return "Последняя запись удалена."


def _excluded(cfg) -> list[str]:
    return cfg.section("finance").get("exclude_from_budget") or ["Ипотека", "Свои счета", "Доход"]


async def month_spent(ctx, category: str) -> tuple[float, float]:
    start, end = month_bounds(ctx.now())
    row = await db.one(ctx.db, "select coalesce(-sum(amount), 0) s from tx where category = %s and amount < 0 and ts >= %s and ts < %s",
                       category, start, end)
    limit = (ctx.cfg.section("finance").get("budget") or {}).get(category, 0)
    return float(row["s"]), float(limit)


async def month_summary(ctx) -> dict:
    now = ctx.now()
    start, end = month_bounds(now)
    rows = await db.fetch(ctx.db, """select category, -sum(amount) s from tx
        where amount < 0 and ts >= %s and ts < %s group by category order by 2 desc""", start, end)
    budget = ctx.cfg.section("finance").get("budget") or {}
    excl = set(_excluded(ctx.cfg))
    spent = {r["category"]: float(r["s"]) for r in rows}
    total = sum(v for k, v in spent.items() if k not in excl)
    total_limit = float(sum(budget.values()))
    days_left = (end.date() - now.date()).days
    return {"spent": spent, "budget": budget, "total": total, "total_limit": total_limit,
            "days_left": days_left, "excluded": excl}


async def budget_report(ctx) -> str:
    s = await month_summary(ctx)
    lines = [f"**Бюджет месяца**: {rub(s['total'])} из {rub(s['total_limit'])} ({pct(s['total'], s['total_limit'])})"]
    if s["total_limit"] and s["days_left"] > 0:
        lines.append(f"Осталось {rub(max(s['total_limit'] - s['total'], 0))} на {s['days_left']} дн. — {rub(max(s['total_limit'] - s['total'], 0) / s['days_left'])} в день")
    for c, v in sorted(s["spent"].items(), key=lambda x: -x[1]):
        lim = s["budget"].get(c)
        mark = " ⚠️" if lim and v > lim else ""
        excl = " (вне бюджета)" if c in s["excluded"] else ""
        lines.append(f"• {c}: {rub(v)}" + (f" / {rub(lim)}" if lim else "") + mark + excl)
    if not s["spent"]:
        lines.append("Расходов в этом месяце пока нет.")
    return "\n".join(lines)


async def savings_progress(ctx) -> tuple[float, float, str]:
    goal = ctx.cfg.section("finance").get("savings_goal") or {}
    row = await db.one(ctx.db, "select coalesce(sum(amount), 0) s from savings")
    return float(row["s"]), float(goal.get("target", 0)), goal.get("name", "Цель")


async def savings(ctx, arg: str) -> str:
    if arg:
        m = re.fullmatch(rf"([+-]?)\s*({NUM})(?:\s+(.*))?", arg)
        if not m:
            return "Формат: `копилка 15000` или `копилка -5000`"
        amount = to_float(m.group(2)) * (-1 if m.group(1) == "-" else 1)
        row = await db.one(ctx.db, "insert into savings (ts, amount, note) values (%s, %s, %s) returning id",
                           ctx.now(), amount, m.group(3))
        ctx.last[KEY] = ("savings", row["id"])
    total, target, name = await savings_progress(ctx)
    since = ctx.now() - timedelta(days=90)
    row = await db.one(ctx.db, "select coalesce(sum(amount), 0) s, min(ts) first from savings where ts >= %s", since)
    months = max(1.0, (ctx.now() - row["first"]).days / 30) if row["first"] else 1.0
    pace = float(row["s"]) / months
    msg = f"🏠 Копилка «{name}»: {rub(total)}" + (f" из {rub(target)} ({pct(total, target)})" if target else "")
    if target and pace > 0 and total < target:
        msg += f"\nТемп: {rub(pace)}/мес → цель примерно через {((target - total) / pace):.0f} мес."
    return msg
