"""FSM-состояния на SQLite: переживают рестарт процесса.

Aiogram по умолчанию держит состояния в памяти — при падении или перезапуске
человек оказывается «посреди анкеты» и бот его не понимает. Здесь состояние
пишется в ту же базу, что и всё остальное.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey

import db


def _key(key: StorageKey) -> str:
    return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{key.destiny}"


class SQLiteStorage(BaseStorage):
    async def set_state(self, key: StorageKey, state: State | str | None = None) -> None:
        value = state.state if isinstance(state, State) else state
        await db.execute(
            "INSERT INTO fsm (key, state) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET state = excluded.state",
            (_key(key), value),
        )

    async def get_state(self, key: StorageKey) -> Optional[str]:
        row = await db.fetchone("SELECT state FROM fsm WHERE key = ?", (_key(key),))
        return row["state"] if row else None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        await db.execute(
            "INSERT INTO fsm (key, data) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET data = excluded.data",
            (_key(key), json.dumps(data, ensure_ascii=False)),
        )

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        row = await db.fetchone("SELECT data FROM fsm WHERE key = ?", (_key(key),))
        if not row or not row["data"]:
            return {}
        try:
            return json.loads(row["data"])
        except json.JSONDecodeError:
            return {}

    async def close(self) -> None:
        return None
