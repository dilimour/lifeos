"""Точка входа: вход в Matrix, комнаты, обработка сообщений, расписание сводок."""
import asyncio
import json
import logging
import tempfile
from datetime import datetime
from urllib.parse import urlparse

from nio import AsyncClient, AsyncClientConfig, LoginResponse, MatrixRoom, RoomMessageFile, RoomMessageText, WhoamiResponse

from . import briefs, db, importer, rooms
from .config import Config, load
from .handlers import HANDLERS
from .util import strip_md, to_html

log = logging.getLogger("lifeos")


class Bot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = AsyncClient(cfg.homeserver, cfg.user_id, config=AsyncClientConfig(store_sync_tokens=False))
        self.db = None
        self.rooms: dict[str, str] = {}
        self.by_id: dict[str, str] = {}
        self.last: dict = {}          # key комнаты -> (таблица, id) для «отмена»
        self.started = datetime.now(cfg.tz)

    def now(self) -> datetime:
        return datetime.now(self.cfg.tz)

    # ---------- Matrix ----------
    async def login(self) -> None:
        sess = self.cfg.data_dir / "session.json"
        if sess.exists():
            d = json.loads(sess.read_text())
            self.client.access_token, self.client.device_id = d["access_token"], d["device_id"]
            if isinstance(await self.client.whoami(), WhoamiResponse):
                log.info("сессия восстановлена")
                return
        r = await self.client.login(self.cfg.password, device_name="lifeos-bot")
        if not isinstance(r, LoginResponse):
            raise SystemExit(f"вход не удался: {r}")
        sess.write_text(json.dumps({"access_token": r.access_token, "device_id": r.device_id}))
        sess.chmod(0o600)
        log.info("вход выполнен как %s", r.user_id)

    async def send(self, room_id: str, text: str) -> None:
        await self.client.room_send(room_id, "m.room.message", {
            "msgtype": "m.text", "body": strip_md(text),
            "format": "org.matrix.custom.html", "formatted_body": to_html(text)})

    async def download(self, mxc: str) -> bytes:
        """Аутентифицированная загрузка медиа (Synapse ≥ 1.120 требует токен)."""
        u = urlparse(mxc)
        url = f"{self.cfg.homeserver}/_matrix/client/v1/media/download/{u.netloc}{u.path}"
        async with self.client.client_session.get(url, headers={"Authorization": f"Bearer {self.client.access_token}"}) as r:
            r.raise_for_status()
            return await r.read()

    # ---------- события ----------
    def _ours(self, room: MatrixRoom, event) -> str | None:
        if event.sender != self.cfg.owner:
            return None
        if datetime.fromtimestamp(event.server_timestamp / 1000, self.cfg.tz) < self.started:
            return None  # старые сообщения при перезапуске не обрабатываем
        return self.by_id.get(room.room_id)

    async def on_text(self, room: MatrixRoom, event: RoomMessageText) -> None:
        key = self._ours(room, event)
        handler = HANDLERS.get(key) if key else None
        if not handler:
            if key == "briefs" and event.body.strip().lower() in ("план", "утро"):
                await self.send(room.room_id, await briefs.morning(self))
            elif key == "briefs" and event.body.strip().lower() in ("итог", "вечер"):
                await self.send(room.room_id, await briefs.evening(self))
            return
        try:
            reply = await handler.handle(self, event.body)
        except Exception as e:  # noqa: BLE001 — сообщаем владельцу, бот продолжает работать
            log.exception("ошибка обработки")
            reply = f"⚠️ Ошибка: {e}"
        if reply is None:
            reply = "Не понял. Напиши `помощь`."
        await self.send(room.room_id, reply)

    async def on_file(self, room: MatrixRoom, event: RoomMessageFile) -> None:
        key = self._ours(room, event)
        if key != "finance":
            return
        if not event.body.lower().endswith(".pdf"):
            await self.send(room.room_id, "Принимаю только PDF-выписки.")
            return
        try:
            data = await self.download(event.url)
            with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                f.write(data)
                f.flush()
                text = await asyncio.to_thread(importer.pdf_to_text, f.name)
            reply = await importer.import_ops(self, importer.parse(text))
        except Exception as e:  # noqa: BLE001
            log.exception("ошибка импорта")
            reply = f"⚠️ Не удалось импортировать: {e}"
        await self.send(room.room_id, reply)

    # ---------- расписание ----------
    async def scheduler(self) -> None:
        times = self.cfg.section("briefs")
        jobs = {"morning": (times.get("morning", "08:45"), briefs.morning),
                "evening": (times.get("evening", "21:00"), briefs.evening)}
        while True:
            now = self.now()
            for name, (hhmm, fn) in jobs.items():
                if now.strftime("%H:%M") >= hhmm and await db.kv_get(self.db, f"sent:{name}") != now.date().isoformat():
                    try:
                        await self.send(self.rooms["briefs"], await fn(self))
                        await db.kv_set(self.db, f"sent:{name}", now.date().isoformat())
                    except Exception:  # noqa: BLE001
                        log.exception("ошибка сводки %s", name)
            await asyncio.sleep(30)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("nio").setLevel(logging.WARNING)
    cfg = load()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    bot = Bot(cfg)
    bot.db = await db.connect(cfg.database_url)
    await bot.login()
    await bot.client.sync(timeout=0, full_state=True)
    bot.rooms = await rooms.ensure(bot)
    bot.by_id = {v: k for k, v in bot.rooms.items()}
    # чтобы сводка не пришла сразу после первого запуска «задним числом»
    for name, default in (("morning", "08:45"), ("evening", "21:00")):
        if await db.kv_get(bot.db, f"sent:{name}") is None and bot.now().strftime("%H:%M") >= cfg.section("briefs").get(name, default):
            await db.kv_set(bot.db, f"sent:{name}", bot.now().date().isoformat())
    bot.client.add_event_callback(bot.on_text, RoomMessageText)
    bot.client.add_event_callback(bot.on_file, RoomMessageFile)
    asyncio.create_task(bot.scheduler())
    log.info("LifeOS запущен, комнат: %d", len(bot.rooms))
    await bot.client.sync_forever(timeout=30000)
