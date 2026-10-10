"""Пространство «Моя жизнь» и комнаты по сферам. Создаются один раз, id хранятся в БД."""
import logging

from nio import RoomCreateResponse, RoomPreset

from . import db
from .handlers import HANDLERS

log = logging.getLogger("lifeos.rooms")

SPACE = ("space", "Моя жизнь", "Личный ассистент: финансы, здоровье, спорт, работа, обучение, досуг")
ROOMS = [
    ("briefs", "Сводки", "Утренний план и вечерний итог"),
    ("finance", "Финансы", "Расходы, бюджет, копилка, выписки"),
    ("health", "Здоровье", "Вес и дневник самочувствия"),
    ("sport", "Спорт", "Тренировки A/B и прогресс"),
    ("work", "Работа", "Задачи из Jira"),
    ("learning", "Обучение", "Время на учёбу и заметки"),
    ("leisure", "Досуг", "Идеи и планы на отдых"),
]


async def ensure(bot) -> dict[str, str]:
    """Возвращает {key: room_id}. Недостающие комнаты создаёт и приглашает владельца."""
    owner = bot.cfg.owner
    # создатель комнаты (бот) получает права сам; в комнатах v12 его нельзя указывать в power levels
    pl = {"users": {owner: 100}}
    joined = set(bot.client.rooms.keys())
    result: dict[str, str] = {}

    async def create(key, name, topic, space=False, parent=None):
        state = []
        if parent:
            state.append({"type": "m.space.parent", "state_key": parent,
                          "content": {"via": [bot.cfg.server_name], "canonical": True}})
        r = await bot.client.room_create(name=name, topic=topic, invite=[owner], preset=RoomPreset.private_chat,
                                         power_level_override=pl, initial_state=state, space=space, federate=False)
        if not isinstance(r, RoomCreateResponse):
            raise RuntimeError(f"не удалось создать комнату {name}: {r}")
        await db.kv_set(bot.db, f"room:{key}", r.room_id)
        log.info("создана комната %s → %s", name, r.room_id)
        return r.room_id, True

    async def get_or_create(key, name, topic, space=False, parent=None):
        rid = await db.kv_get(bot.db, f"room:{key}")
        if rid and rid in joined:
            return rid, False
        return await create(key, name, topic, space, parent)

    space_id, _ = await get_or_create(*SPACE, space=True)
    result["space"] = space_id
    for key, name, topic in ROOMS:
        rid, created = await get_or_create(key, name, topic, parent=space_id)
        result[key] = rid
        if created:
            await bot.client.room_put_state(space_id, "m.space.child", {"via": [bot.cfg.server_name]}, state_key=rid)
            handler = HANDLERS.get(key)
            welcome = handler.HELP if handler else \
                "Сюда приходит утренний план и вечерний итог. Время — в config.yaml → briefs."
            await bot.send(rid, welcome)
    return result
