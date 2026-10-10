"""Утренний план и вечерний итог для комнаты «Сводки»."""
from datetime import timedelta

from . import db
from .handlers import finance, health, learning, sport, work
from .util import human_date, minutes_h, pct, rub


async def morning(ctx) -> str:
    now = ctx.now()
    lines = [f"☀️ **{human_date(now.date())}**"]

    s = await health.weight_stats(ctx)
    if s:
        w = f"⚖️ Вес: среднее за неделю {s['avg7']:.1f} кг".replace(".", ",")
        if s["goal"] and s["avg7"] > float(s["goal"]):
            w += f", до цели {s['avg7'] - float(s['goal']):.1f} кг".replace(".", ",")
        lines.append(w + ". Взвесься и напиши число в «Здоровье».")
    else:
        lines.append("⚖️ Взвесься натощак и напиши вес в «Здоровье».")

    done = await sport.done_today(ctx)
    if done:
        lines.append(f"💪 Тренировка {done} уже выполнена.")
    elif sport.is_training_day(ctx, now.date()):
        kind = await sport.next_kind(ctx)
        lines.append(f"💪 Сегодня тренировка **{kind}**: " + "; ".join(sport.program(ctx.cfg).get(kind, [])))
    else:
        lines.append("💪 Сегодня без зала: прогулка 8–10 тыс. шагов.")

    fs = await finance.month_summary(ctx)
    if fs["total_limit"]:
        left = max(fs["total_limit"] - fs["total"], 0)
        per_day = left / fs["days_left"] if fs["days_left"] else 0
        line = f"💰 Месяц: {rub(fs['total'])} из {rub(fs['total_limit'])} ({pct(fs['total'], fs['total_limit'])}), можно {rub(per_day)} в день"
        over = [c for c, lim in fs["budget"].items() if fs["spent"].get(c, 0) > lim]
        if over:
            line += ". Перерасход: " + ", ".join(over)
        lines.append(line + ".")
    total, target, name = await finance.savings_progress(ctx)
    if target:
        lines.append(f"🏠 «{name}»: {rub(total)} из {rub(target)} ({pct(total, target)}).")

    tasks = await work.open_tasks(ctx, limit=5)
    if tasks:
        lines.append("🛠 Задачи в работе:")
        lines += [f"  {t['id']}. {t['title']}" for t in tasks]

    goal_h = ctx.cfg.section("learning").get("hours_per_week", 0)
    if goal_h:
        m = await learning.week_minutes(ctx)
        lines.append(f"📚 Обучение за неделю: {minutes_h(m)} из {goal_h} ч.")
    return "\n".join(lines)


async def evening(ctx) -> str:
    now = ctx.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    lines = ["🌙 **Итоги дня**"]
    row = await db.one(ctx.db, "select count(*) n, coalesce(-sum(amount), 0) s from tx where amount < 0 and ts >= %s", start)
    lines.append(f"💰 Расходы сегодня: {row['n']} шт. на {rub(float(row['s']))}." if row["n"]
                 else "💰 Расходов за сегодня нет. Наличными что-то тратил?")
    if not await health.logged_today(ctx):
        lines.append("⚖️ Вес сегодня не записан.")
    done = await sport.done_today(ctx)
    if done:
        lines.append(f"💪 Тренировка {done} — выполнена.")
    elif sport.is_training_day(ctx, now.date()):
        lines.append("💪 Тренировка по плану была сегодня — не отмечена.")
    row = await db.one(ctx.db, "select coalesce(sum(minutes), 0) m from study where ts >= %s", start)
    if row["m"]:
        lines.append(f"📚 Обучение сегодня: {minutes_h(int(row['m']))}.")
    row = await db.one(ctx.db, "select count(*) n from task where done_at >= %s", start)
    if row["n"]:
        lines.append(f"🛠 Закрыто задач: {row['n']}.")
    tomorrow = (now + timedelta(days=1)).date()
    if sport.is_training_day(ctx, tomorrow):
        lines.append("Завтра тренировка — ложись вовремя.")
    return "\n".join(lines)
