"""Комната «Работа»: список задач (выгрузка из Jira текстом)."""
import re

from .. import db

KEY = "work"
HELP = """**Работа — как пользоваться**
Вставь список задач — каждая строка станет задачей (ключ вида `OMS-123` распознаю).
`задачи` — открытые задачи
`готово 12` или `готово OMS-123` — закрыть
`удалить 12` — удалить
`отмена` — удалить последнюю добавленную"""

JIRA_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


async def handle(ctx, text: str) -> str | None:
    t = text.strip()
    low = t.lower()
    if low in ("помощь", "?", "help"):
        return HELP
    if low in ("задачи", "список"):
        return await open_list(ctx)
    m = re.fullmatch(r"(готово|сделано|удалить)\s+(\S+)", t, re.I)
    if m:
        verb, ref = m.group(1).lower(), m.group(2)
        cond, arg = ("id = %s", int(ref)) if ref.isdigit() else ("jira = %s", ref.upper())
        if verb == "удалить":
            cur = await ctx.db.execute(f"delete from task where {cond}", (arg,))
            return "🗑 Удалено." if cur.rowcount else "Не нашёл такую задачу."
        cur = await ctx.db.execute(f"update task set done_at = %s where {cond} and done_at is null", (ctx.now(), arg))
        return "✅ Закрыто. " + (await open_count_text(ctx)) if cur.rowcount else "Не нашёл открытую задачу."
    if low == "отмена":
        last = ctx.last.pop(KEY, None)
        if not last:
            return "Нечего отменять."
        await ctx.db.execute("delete from task where id = any(%s)", (last[1],))
        return "Последние добавленные задачи удалены."
    lines = [re.sub(r"^\s*[-*•\d.)]+\s*", "", ln).strip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return None
    ids = []
    for ln in lines:
        jm = JIRA_RE.search(ln)
        jira = jm.group(1) if jm else None
        if jira and await db.one(ctx.db, "select 1 from task where jira = %s and done_at is null", jira):
            continue
        row = await db.one(ctx.db, "insert into task (created, jira, title) values (%s, %s, %s) returning id", ctx.now(), jira, ln)
        ids.append(row["id"])
    ctx.last[KEY] = ("task", ids)
    return f"📌 Добавлено задач: {len(ids)}" + (f" (дубли пропущены: {len(lines) - len(ids)})" if len(ids) < len(lines) else "") + \
           ". " + await open_count_text(ctx)


async def open_tasks(ctx, limit: int = 50) -> list[dict]:
    return await db.fetch(ctx.db, "select id, jira, title, created from task where done_at is null order by created limit %s", limit)


async def open_count_text(ctx) -> str:
    row = await db.one(ctx.db, "select count(*) n from task where done_at is null")
    return f"Открыто: {row['n']}."


async def open_list(ctx) -> str:
    rows = await open_tasks(ctx)
    if not rows:
        return "Открытых задач нет 🎉"
    return "\n".join(f"{r['id']}. {r['title']}" for r in rows)
