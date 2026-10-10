"""PostgreSQL: схема и общие запросы."""
import psycopg
from psycopg.rows import dict_row

SCHEMA = """
create table if not exists kv (
    key   text primary key,
    value text not null
);
create table if not exists tx (
    id        bigserial primary key,
    ts        timestamptz not null default now(),
    amount    numeric(12,2) not null,          -- расход < 0, доход > 0
    category  text not null,
    note      text,
    source    text not null default 'manual',  -- manual | import
    ext_hash  text unique                      -- для дедупликации выписок
);
create index if not exists tx_ts on tx (ts);
create table if not exists savings (
    id     bigserial primary key,
    ts     timestamptz not null default now(),
    amount numeric(12,2) not null,
    note   text
);
create table if not exists weight (
    id bigserial primary key,
    ts timestamptz not null default now(),
    kg numeric(5,2) not null
);
create table if not exists workout (
    id   bigserial primary key,
    ts   timestamptz not null default now(),
    kind text not null
);
create table if not exists exercise (
    id         bigserial primary key,
    workout_id bigint references workout(id) on delete cascade,
    ts         timestamptz not null default now(),
    name       text not null,
    sets       int,
    reps       int,
    kg         numeric(6,2)
);
create table if not exists task (
    id      bigserial primary key,
    created timestamptz not null default now(),
    jira    text,
    title   text not null,
    done_at timestamptz
);
create table if not exists study (
    id      bigserial primary key,
    ts      timestamptz not null default now(),
    minutes int not null,
    topic   text not null
);
create table if not exists note (
    id   bigserial primary key,
    ts   timestamptz not null default now(),
    room text not null,
    text text not null
);
"""


async def connect(url: str) -> psycopg.AsyncConnection:
    conn = await psycopg.AsyncConnection.connect(url, autocommit=True, row_factory=dict_row)
    await conn.execute(SCHEMA)
    return conn


async def fetch(conn, sql: str, *args) -> list[dict]:
    cur = await conn.execute(sql, args)
    return await cur.fetchall()


async def one(conn, sql: str, *args) -> dict | None:
    cur = await conn.execute(sql, args)
    return await cur.fetchone()


async def kv_get(conn, key: str) -> str | None:
    row = await one(conn, "select value from kv where key = %s", key)
    return row["value"] if row else None


async def kv_set(conn, key: str, value: str) -> None:
    await conn.execute(
        "insert into kv (key, value) values (%s, %s) on conflict (key) do update set value = excluded.value",
        (key, value),
    )
