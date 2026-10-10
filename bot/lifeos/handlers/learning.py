"""Комната «Обучение»: учёт времени по темам, цель часов в неделю."""
import re
from datetime import timedelta

from .. import db
from ..util import minutes_h, parse_duration

KEY = "learning"
HELP = """**Обучение — как пользоваться**
`45 k8s` или `1ч30 python` — сколько занимался и чем
`неделя` — итоги недели против цели
`темы` — темы из плана
Любой другой текст — заметка (ссылка на курс, идея, вопрос).
`отмена` — удалить последнюю запись"""

DUR_RE = re.compile(r"^(\d+(?:[.,]\d+)?\s*ч(?:ас(?:а|ов)?)?\s*\d*\s*(?:м|мин)?|\d+\s*(?:м|мин|минут)?)\s+(.+)$", re.I)


async def handle(ctx, text: str) -> str | None:
    t = text.strip()
    low = t.lower()
    if low in ("помощь", "?", "help"):
        return HELP
    if low == "неделя":
        return await week_report(ctx)
    if low == "темы":
        topics = ctx.cfg.section("learning").get("topics") or []
        return "\n".join(f"• {x}" for x in topics) or "Темы не заданы в config.yaml"
    if low == "отмена":
        last = ctx.last.pop(KEY, None)
        if not last:
            return "Нечего отменять."
        await ctx.db.execute(f"delete from {last[0]} where id = %s", (last[1],))
        return "Последняя запись удалена."
    m = DUR_RE.match(t)
    if m:
        minutes = parse_duration(m.group(1))
        if minutes:
            row = await db.one(ctx.db, "insert into study (ts, minutes, topic) values (%s, %s, %s) returning id",
                               ctx.now(), minutes, m.group(2).strip().lower())
            ctx.last[KEY] = ("study", row["id"])
            return f"📚 {minutes_h(minutes)} · {m.group(2).strip()}. " + await week_line(ctx)
    row = await db.one(ctx.db, "insert into note (ts, room, text) values (%s, %s, %s) returning id", ctx.now(), KEY, t)
    ctx.last[KEY] = ("note", row["id"])
    return "📝 Сохранил заметку."


def week_start(ctx):
    now = ctx.now()
    return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


async def week_minutes(ctx) -> int:
    row = await db.one(ctx.db, "select coalesce(sum(minutes), 0) m from study where ts >= %s", week_start(ctx))
    return int(row["m"])


async def week_line(ctx) -> str:
    goal_h = ctx.cfg.section("learning").get("hours_per_week", 0)
    m = await week_minutes(ctx)
    return f"За неделю {minutes_h(m)}" + (f" из {goal_h} ч." if goal_h else ".")


async def week_report(ctx) -> str:
    rows = await db.fetch(ctx.db, "select topic, sum(minutes) m from study where ts >= %s group by topic order by 2 desc", week_start(ctx))
    lines = [await week_line(ctx)] + [f"• {r['topic']}: {minutes_h(r['m'])}" for r in rows]
    return "\n".join(lines)
