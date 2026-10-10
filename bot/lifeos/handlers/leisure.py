"""Комната «Досуг»: идеи и планы на отдых."""
from .. import db

KEY = "leisure"
HELP = """**Досуг — как пользоваться**
Любой текст — идея или план (поездка, фильм, прогулка).
`список` — последние 20 идей
`отмена` — удалить последнюю"""


async def handle(ctx, text: str) -> str | None:
    t = text.strip()
    low = t.lower()
    if low in ("помощь", "?", "help"):
        return HELP
    if low == "список":
        rows = await db.fetch(ctx.db, "select id, text from note where room = %s order by ts desc limit 20", KEY)
        return "\n".join(f"{r['id']}. {r['text']}" for r in reversed(rows)) or "Пока пусто."
    if low == "отмена":
        last = ctx.last.pop(KEY, None)
        if not last:
            return "Нечего отменять."
        await ctx.db.execute(f"delete from {last[0]} where id = %s", (last[1],))
        return "Удалено."
    row = await db.one(ctx.db, "insert into note (ts, room, text) values (%s, %s, %s) returning id", ctx.now(), KEY, t)
    ctx.last[KEY] = ("note", row["id"])
    return "✨ Записал."
