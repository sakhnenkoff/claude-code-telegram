"""Persistent key-value store for signal scanner state.

Uses a standalone SQLite database (separate from bot.db) to track
last-known values for each signal detector.
"""

from pathlib import Path
from typing import Dict, Optional
import aiosqlite
import structlog

logger = structlog.get_logger()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS signal_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

class StateStore:
    """Simple async key-value store backed by SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(_CREATE_TABLE)
            await conn.commit()

    async def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT value FROM signal_state WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row[0] if row else default

    async def set(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """INSERT INTO signal_state (key, value, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                   updated_at = CURRENT_TIMESTAMP""",
                (key, value),
            )
            await conn.commit()

    async def set_many(self, pairs: Dict[str, str]) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            for key, value in pairs.items():
                await conn.execute(
                    """INSERT INTO signal_state (key, value, updated_at)
                       VALUES (?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                       updated_at = CURRENT_TIMESTAMP""",
                    (key, value),
                )
            await conn.commit()
