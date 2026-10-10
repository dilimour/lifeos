"""Комната «Здоровье»: вес и дневник самочувствия."""
import re
from datetime import timedelta

from .. import db
from ..util import NUM, kg, to_float

KEY = "health"
HELP = """**Здоровье — как пользоваться**
`91.4` или `вес 91.4` — утреннее взвешивание
`вес` — динамика и прогноз до цели
`дневник` — последние записи дневника
Любой другой текст — запись в дневник (самочувствие, кожа, что ел, сон).
`отмена` — удалить последнюю запись"""

WEIGHT_RE = re.compile(rf"^(?:вес\s+)?({NUM})\s*(?:кг)?$", re.I)


async def handle(ctx, text: str) -> str | None:
    t = text.strip()
    low = t.lower()
    if low in ("помощь", "?", "help"):
        return HELP
    if low == "вес":
        return await weight_report(ctx)
    if low == "дневник":
        rows = await db.fetch(ctx.db, "select ts, text from note where room = %s order by ts desc limit 10", KEY)
        return "\n".join(f"{r['ts'].astimezone(ctx.cfg.tz):%d.%m %H:%M} — {r['text']}" for r in reversed(rows)) or "Дневник пуст."
    if low == "отмена":
        last = ctx.last.pop(KEY, None)
        if not last:
            return "Нечего отменять."
        await ctx.db.execute(f"delete from {last[0]} where id = %s", (last[1],))
        return "Последняя запись удалена."
    m = WEIGHT_RE.match(t)
    if m:
        value = to_float(m.group(1))
        if 30 <= value <= 300:
            row = await db.one(ctx.db, "insert into weight (ts, kg) values (%s, %s) returning id", ctx.now(), value)
            ctx.last[KEY] = ("weight", row["id"])
            return "⚖️ Записал. " + await weight_report(ctx, short=True)
    row = await db.one(ctx.db, "insert into note (ts, room, text) values (%s, %s, %s) returning id", ctx.now(), KEY, t)
    ctx.last[KEY] = ("note", row["id"])
    return "📝 Записал в дневник."


async def weight_stats(ctx) -> dict | None:
    rows = await db.fetch(ctx.db, "select ts, kg from weight where ts >= %s order by ts", ctx.now() - timedelta(days=60))
    if not rows:
        return None
    now = ctx.now()
    last = float(rows[-1]["kg"])
    week = [float(r["kg"]) for r in rows if r["ts"] >= now - timedelta(days=7)]
    prev = [float(r["kg"]) for r in rows if now - timedelta(days=14) <= r["ts"] < now - timedelta(days=7)]
    avg7 = sum(week) / len(week) if week else last
    delta_week = avg7 - (sum(prev) / len(prev)) if prev else None
    # наклон по последним 28 дням (кг/неделю), МНК
    pts = [((r["ts"] - now).total_seconds() / 86400, float(r["kg"])) for r in rows if r["ts"] >= now - timedelta(days=28)]
    slope = None
    if len(pts) >= 5:
        n = len(pts)
        mx = sum(x for x, _ in pts) / n
        my = sum(y for _, y in pts) / n
        den = sum((x - mx) ** 2 for x, _ in pts)
        if den:
            slope = sum((x - mx) * (y - my) for x, y in pts) / den * 7
    goal = (ctx.cfg.section("health").get("weight_goal"))
    return {"last": last, "avg7": avg7, "delta_week": delta_week, "slope": slope, "goal": goal,
            "last_ts": rows[-1]["ts"]}


async def weight_report(ctx, short: bool = False) -> str:
    s = await weight_stats(ctx)
    if not s:
        return "Записей веса пока нет. Пиши число каждое утро после пробуждения."
    parts = [f"Сейчас {kg(s['last'])}, среднее за 7 дней {kg(s['avg7'])}"]
    if s["delta_week"] is not None:
        parts.append(f"за неделю {s['delta_week']:+.1f}".replace(".", ",") + " кг")
    if s["goal"]:
        left = s["avg7"] - float(s["goal"])
        if left > 0:
            parts.append(f"до цели {kg(left)}")
            if s["slope"] and s["slope"] < 0:
                parts.append(f"при текущем темпе ~{left / -s['slope']:.0f} нед.")
        else:
            parts.append("цель достигнута 🎉")
    text = ", ".join(parts).rstrip(".") + "."
    if not short and s["slope"] is not None:
        text += f"\nТемп за 4 недели: {s['slope']:+.2f} кг/нед.".replace(".", ",", 1) + " Комфортно: −0,5…−0,7."
    return text


async def logged_today(ctx) -> bool:
    start = ctx.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return bool(await db.one(ctx.db, "select 1 from weight where ts >= %s", start))
