from pathlib import Path
import pytest
from src.signals.state import StateStore


@pytest.fixture
async def state_store(tmp_path):
    db_path = tmp_path / "test.db"
    store = StateStore(db_path)
    await store.initialize()
    return store


class TestStateStore:
    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing_key(self, state_store):
        result = await state_store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get(self, state_store):
        await state_store.set("inbox:count", "5")
        result = await state_store.get("inbox:count")
        assert result == "5"

    @pytest.mark.asyncio
    async def test_set_overwrites(self, state_store):
        await state_store.set("inbox:count", "5")
        await state_store.set("inbox:count", "8")
        result = await state_store.get("inbox:count")
        assert result == "8"

    @pytest.mark.asyncio
    async def test_get_default(self, state_store):
        result = await state_store.get("missing", default="0")
        assert result == "0"

    @pytest.mark.asyncio
    async def test_set_many_and_get(self, state_store):
        await state_store.set_many({"a": "1", "b": "2", "c": "3"})
        assert await state_store.get("a") == "1"
        assert await state_store.get("b") == "2"
        assert await state_store.get("c") == "3"
