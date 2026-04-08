"""Tests for startup catch-up of missed anchor jobs."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.events.bus import EventBus
from src.scheduler.scheduler import JobScheduler
from src.storage.database import DatabaseManager


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock(spec=DatabaseManager)


@pytest.fixture
def scheduler(event_bus: EventBus, mock_db: AsyncMock, tmp_path: Path) -> JobScheduler:
    return JobScheduler(
        event_bus=event_bus,
        db_manager=mock_db,
        default_working_directory=tmp_path,
    )


class TestMissedAnchors:
    """Tests for startup catch-up of missed anchor jobs."""

    @pytest.mark.asyncio
    async def test_missed_morning_anchor_fires_catchup(
        self, scheduler: JobScheduler, mock_db: AsyncMock
    ) -> None:
        """A morning anchor missed by restart is caught up."""
        mock_row = {
            "job_id": "hb-morning",
            "job_name": "Heartbeat Morning",
            "cron_expression": "0 9 * * 1-5",
            "prompt": "Morning brief",
            "working_directory": "/tmp/vault",
            "target_chat_ids": "246177948",
            "skill_name": None,
            "config_overrides": "{}",
            "job_type": "anchor",
            "last_fired_at": None,
        }
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [mock_row]
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = mock_cursor
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_db.get_connection.return_value = mock_conn

        scheduler._fire_event = AsyncMock()

        with patch("src.scheduler.scheduler.datetime") as mock_dt:
            from apscheduler.triggers.cron import CronTrigger

            tz = CronTrigger.from_crontab("0 0 * * *").timezone
            mock_now = datetime(2026, 4, 8, 9, 30, tzinfo=tz)
            mock_dt.now.return_value = mock_now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            await scheduler._check_missed_anchors()

        scheduler._fire_event.assert_called_once()
        call_kwargs = scheduler._fire_event.call_args.kwargs
        assert call_kwargs["job_name"] == "Heartbeat Morning"

    @pytest.mark.asyncio
    async def test_already_fired_today_skips_catchup(
        self, scheduler: JobScheduler, mock_db: AsyncMock
    ) -> None:
        """An anchor that already fired today is not caught up again."""
        mock_row = {
            "job_id": "hb-morning",
            "job_name": "Heartbeat Morning",
            "cron_expression": "0 9 * * 1-5",
            "prompt": "Morning brief",
            "working_directory": "/tmp/vault",
            "target_chat_ids": "246177948",
            "skill_name": None,
            "config_overrides": "{}",
            "job_type": "anchor",
            "last_fired_at": "2026-04-08T09:05:00+02:00",
        }
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [mock_row]
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = mock_cursor
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_db.get_connection.return_value = mock_conn

        scheduler._fire_event = AsyncMock()

        with patch("src.scheduler.scheduler.datetime") as mock_dt:
            from apscheduler.triggers.cron import CronTrigger

            tz = CronTrigger.from_crontab("0 0 * * *").timezone
            mock_now = datetime(2026, 4, 8, 9, 30, tzinfo=tz)
            mock_dt.now.return_value = mock_now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            await scheduler._check_missed_anchors()

        scheduler._fire_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_future_anchor_not_caught_up(
        self, scheduler: JobScheduler, mock_db: AsyncMock
    ) -> None:
        """An anchor whose time hasn't passed yet is not caught up."""
        mock_row = {
            "job_id": "hb-evening",
            "job_name": "Heartbeat Evening",
            "cron_expression": "0 20 * * 1-5",
            "prompt": "Evening wrap",
            "working_directory": "/tmp/vault",
            "target_chat_ids": "246177948",
            "skill_name": None,
            "config_overrides": "{}",
            "job_type": "anchor",
            "last_fired_at": None,
        }
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [mock_row]
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = mock_cursor
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_db.get_connection.return_value = mock_conn

        scheduler._fire_event = AsyncMock()

        with patch("src.scheduler.scheduler.datetime") as mock_dt:
            from apscheduler.triggers.cron import CronTrigger

            tz = CronTrigger.from_crontab("0 0 * * *").timezone
            mock_now = datetime(2026, 4, 8, 9, 30, tzinfo=tz)
            mock_dt.now.return_value = mock_now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            await scheduler._check_missed_anchors()

        scheduler._fire_event.assert_not_called()
