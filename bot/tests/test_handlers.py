"""Проверка обработчиков на живой PostgreSQL без Matrix.

    LIFEOS_TEST_DB=postgresql://t:t@127.0.0.1/t python -m pytest -q tests
"""
import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from lifeos import briefs, db, importer
from lifeos.config import Config
from lifeos.handlers import finance, health, learning, leisure, sport, work
from lifeos.util import parse_duration

URL = os.environ.get("LIFEOS_TEST_DB")
pytestmark = pytest.mark.skipif(not URL, reason="LIFEOS_TEST_DB не задан")
TZ = ZoneInfo("Europe/Moscow")
RAW = yaml.safe_load((Path(__file__).parent.parent / "config.example.yaml").read_text(encoding="utf-8"))


class Ctx:
    def __init__(self, conn, now):
        self.db, self._now, self.last = conn, now, {}
        self.cfg = Config("", "@lifeos:x", "", "@john:x", URL, Path("/tmp"), TZ, RAW)

    def now(self):
        return self._now


async def fresh(now=datetime(2026, 10, 12, 10, 0, tzinfo=TZ)):  # понедельник
    conn = await db.connect(URL)
    await conn.execute("drop schema public cascade; create schema public;")
    await conn.execute(db.SCHEMA)
    return Ctx(conn, now)


def run(coro):
    return asyncio.run(coro)


def test_duration():
    assert parse_duration("45") == 45
    assert parse_duration("1ч30") == 90
    assert parse_duration("1.5ч") == 90
    assert parse_duration("2 ч") == 120


def test_finance_flow():
    async def go():
        c = await fresh()
        r = await finance.handle(c, "450 кафе обед")
        assert "Кафе" in r and "450" in r
        r = await finance.handle(c, "1 200,50 магнит")
        assert "Продукты" in r
        r = await finance.handle(c, "300 непонятное")
        assert "Прочее" in r
        assert "удалена" in await finance.handle(c, "отмена")
        r = await finance.handle(c, "+98000 зарплата")
        assert "Доход" in r
        rep = await finance.handle(c, "бюджет")
        assert "Кафе" in rep and "Продукты" in rep and "из" in rep
        r = await finance.handle(c, "копилка 15000")
        assert "15 000" in r and "Дом" in r
        assert await finance.handle(c, "привет") is None
    run(go())


def test_health_flow():
    async def go():
        c = await fresh()
        base = c._now
        for i, w in enumerate([92.0, 91.8, 91.9, 91.5, 91.4, 91.3, 91.0, 90.9]):
            c._now = base - timedelta(days=14 - i * 2)
            await health.handle(c, f"{w}")
        c._now = base
        r = await health.handle(c, "вес 90,8")
        assert "Записал" in r and "до цели" in r
        r = await health.handle(c, "вес")
        assert "Темп" in r
        assert "дневник" in (await health.handle(c, "руки чешутся после стирки")).lower()
        assert "руки" in await health.handle(c, "дневник")
    run(go())


def test_sport_flow():
    async def go():
        c = await fresh()
        r = await sport.handle(c, "А")
        assert "Тренировка A" in r
        r = await sport.handle(c, "присед 3x5 60")
        assert "60" in r
        c._now += timedelta(days=2)
        await sport.handle(c, "b")
        r = await sport.handle(c, "присед 3х5 62,5")
        assert "прошлый раз 3x5 · 60" in r
        assert "B" in await sport.handle(c, "история")
        assert await sport.next_kind(c) == "A"
    run(go())


def test_work_flow():
    async def go():
        c = await fresh()
        r = await work.handle(c, "OMS-12 Обновить Postgres\n- VKSEC-3 доступы k8s\nпочистить логи")
        assert "Добавлено задач: 3" in r
        r = await work.handle(c, "OMS-12 Обновить Postgres ещё раз")
        assert "дубли" in r
        assert "Закрыто" in await work.handle(c, "готово OMS-12")
        lst = await work.handle(c, "задачи")
        assert "VKSEC-3" in lst and "OMS-12" not in lst
    run(go())


def test_learning_leisure():
    async def go():
        c = await fresh()
        r = await learning.handle(c, "1ч30 k8s ingress")
        assert "1 ч 30 м" in r and "из 6 ч" in r
        assert "k8s" in await learning.handle(c, "неделя")
        assert "Записал" in await leisure.handle(c, "съездить в Адыгею")
        assert "Адыгею" in await leisure.handle(c, "список")
    run(go())


def test_briefs():
    async def go():
        c = await fresh()
        await finance.handle(c, "500 кафе")
        await health.handle(c, "91")
        await work.handle(c, "OMS-1 задача")
        m = await briefs.morning(c)
        assert "тренировка" in m.lower() and "OMS-1" in m and "Месяц" in m
        e = await briefs.evening(c)
        assert "Итоги" in e and "не отмечена" in e
    run(go())


def test_import_parse_and_categorize():
    text = (
        "29.07.26             29.07.26    Пополнение. Система быстрых платежей            + 97 927.00 ₽      + 97 927.00 ₽\n"
        "\n"
        "29.07.26             29.07.26    Внешний перевод по номеру телефона               19 800.00 ₽         19 800.00 ₽\n"
        "                                 +79990000000\n"
        "29.07.26 20:26       29.07.26    Оплата в MAGNIT GM KRASNODAR 21                        891.92 ₽         891.92 ₽\n"
        "30.07.26 14:20       30.07.26    Оплата в SOME NEW SHOP                                390.00 ₽         390.00 ₽\n"
    )
    ops = importer.parse(text)
    assert len(ops) == 4 and ops[1]["desc"].endswith("+79990000000")
    rules = RAW["finance"]["import_rules"]
    cats = [importer.categorize(o, rules, "+79990000000", 18000) for o in ops]
    assert cats == ["Доход", "Ипотека", "Продукты", "Прочее"]

    async def go():
        c = await fresh()
        os.environ["LIFEOS_OWN_PHONE"] = "+79990000000"
        r1 = await importer.import_ops(c, ops)
        r2 = await importer.import_ops(c, ops)
        assert "4 новых" in r1 and "0 новых" in r2 and "SOME NEW SHOP" in r1
    run(go())
