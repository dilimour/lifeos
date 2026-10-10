"""Настройки: секреты из окружения, личные параметры — из config.yaml (не в git)."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


@dataclass
class Config:
    homeserver: str
    user_id: str
    password: str
    owner: str
    database_url: str
    data_dir: Path
    tz: ZoneInfo
    raw: dict = field(default_factory=dict)

    # удобные геттеры по разделам config.yaml
    def section(self, name: str) -> dict:
        return self.raw.get(name) or {}

    @property
    def server_name(self) -> str:
        return self.user_id.split(":", 1)[1]


def load() -> Config:
    path = Path(os.environ.get("LIFEOS_CONFIG", "/config/config.yaml"))
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return Config(
        homeserver=os.environ.get("LIFEOS_HOMESERVER", "http://synapse:8008"),
        user_id=os.environ["LIFEOS_BOT_USER"],
        password=os.environ["LIFEOS_BOT_PASSWORD"],
        owner=os.environ["LIFEOS_OWNER"],
        database_url=os.environ["LIFEOS_DATABASE_URL"],
        data_dir=Path(os.environ.get("LIFEOS_DATA_DIR", "/data")),
        tz=ZoneInfo(raw.get("timezone", "Europe/Moscow")),
        raw=raw,
    )
