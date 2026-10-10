"""Комната «Спорт»: тренировки A/B, упражнения, прогрессия весов."""
import re
from datetime import timedelta

from .. import db
from ..util import DAY_KEYS, to_float

KEY = "sport"
HELP = """**Спорт — как пользоваться**
`A` или `B` — отметить тренировку дня
`присед 3x5 60` — упражнение: подходы x повторы, вес (вес можно не писать)
`подтягивания 5x3` — без веса
`программа` — что входит в A и B
`история` — последние тренировки
`отмена` — удалить последнюю запись"""

EX_RE = re.compile(r"^(.+?)\s+(\d+)\s*[xх×*]\s*(\d+)(?:\s+(\d+(?:[.,]\d+)?)\s*(?:кг)?)?$", re.I)


def program(cfg) -> dict[str, list[str]]:
    return cfg.section("sport").get("program") or {}


async def handle(ctx, text: str) -> str | None:
    t = text.strip()
    low = t.lower()
    if low in ("помощь", "?", "help"):
        return HELP
    if low == "программа":
        return "\n".join(f"**{k}**: " + "; ".join(v) for k, v in program(ctx.cfg).items()) or "Программа не задана в config.yaml"
    if low == "история":
        rows = await db.fetch(ctx.db, """select w.ts, w.kind, string_agg(e.name || ' ' || e.sets || 'x' || e.reps ||
            coalesce(' ' || e.kg::text, ''), '; ' order by e.id) ex from workout w left join exercise e on e.workout_id = w.id
            group by w.id order by w.ts desc limit 7""")
        return "\n".join(f"{r['ts'].astimezone(ctx.cfg.tz):%d.%m} {r['kind']}: {r['ex'] or '—'}" for r in reversed(rows)) or "Тренировок пока нет."
    if low == "отмена":
        last = ctx.last.pop(KEY, None)
        if not last:
            return "Нечего отменять."
        await ctx.db.execute(f"delete from {last[0]} where id = %s", (last[1],))
        return "Последняя запись удалена."
    m = re.fullmatch(r"(?:трен(?:ировка)?\s+)?([abаб])", low)
    if m:
        kind = {"a": "A", "а": "A", "b": "B", "б": "B"}[m.group(1)]
        wid = await today_workout(ctx, kind)
        ctx.last[KEY] = ("workout", wid)
        return f"💪 Тренировка {kind} отмечена. Упражнения: " + "; ".join(program(ctx.cfg).get(kind, [])) + \
               "\nПиши подходы в формате `присед 3x5 60`."
    m = EX_RE.match(t)
    if m:
        name, sets, reps, w = m.group(1).strip().lower(), int(m.group(2)), int(m.group(3)), m.group(4)
        wkg = to_float(w) if w else None
        prev = await db.one(ctx.db, "select sets, reps, kg, ts from exercise where name = %s order by ts desc limit 1", name)
        wid = await today_workout(ctx, None)
        row = await db.one(ctx.db, "insert into exercise (workout_id, ts, name, sets, reps, kg) values (%s, %s, %s, %s, %s, %s) returning id",
                           wid, ctx.now(), name, sets, reps, wkg)
        ctx.last[KEY] = ("exercise", row["id"])
        msg = f"✅ {name}: {sets}x{reps}" + (f" · {wkg:g} кг" if wkg else "")
        if prev:
            msg += f" (прошлый раз {prev['sets']}x{prev['reps']}" + (f" · {float(prev['kg']):g} кг" if prev["kg"] else "") + ")"
        return msg
    return None


async def today_workout(ctx, kind: str | None) -> int:
    start = ctx.now().replace(hour=0, minute=0, second=0, microsecond=0)
    row = await db.one(ctx.db, "select id, kind from workout where ts >= %s order by ts desc limit 1", start)
    if row:
        if kind and row["kind"] != kind:
            await ctx.db.execute("update workout set kind = %s where id = %s", (kind, row["id"]))
        return row["id"]
    kind = kind or await next_kind(ctx)
    row = await db.one(ctx.db, "insert into workout (ts, kind) values (%s, %s) returning id", ctx.now(), kind)
    return row["id"]


async def next_kind(ctx) -> str:
    row = await db.one(ctx.db, "select kind from workout order by ts desc limit 1")
    return "B" if row and row["kind"] == "A" else "A"


def is_training_day(ctx, d) -> bool:
    days = ctx.cfg.section("sport").get("days") or ["mon", "wed", "fri"]
    return DAY_KEYS[d.weekday()] in days


async def done_today(ctx) -> str | None:
    start = ctx.now().replace(hour=0, minute=0, second=0, microsecond=0)
    row = await db.one(ctx.db, "select kind from workout where ts >= %s", start)
    return row["kind"] if row else None


async def week_count(ctx) -> int:
    start = ctx.now() - timedelta(days=ctx.now().weekday())
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    row = await db.one(ctx.db, "select count(*) n from workout where ts >= %s", start)
    return row["n"]
