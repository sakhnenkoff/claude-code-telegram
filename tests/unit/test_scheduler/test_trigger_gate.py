"""Tests for the trigger gate logic."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.events.bus import EventBus
from src.scheduler.scheduler import JobScheduler, Trigger, _minutes_since
from src.signals.detectors import Meeting
from src.storage.database import DatabaseManager


@pytest.fixture
def mock_state():
    """A mock StateStore."""
    state = AsyncMock()
    state.get = AsyncMock(return_value=None)
    state.set = AsyncMock()
    return state


@pytest.fixture
def scheduler(tmp_path):
    event_bus = EventBus()
    db_manager = MagicMock(spec=DatabaseManager)
    return JobScheduler(event_bus, db_manager, tmp_path)


def _meeting(title: str, minutes_from_now: float, calendar: str = "matvii@vend.com") -> Meeting:
    now = datetime.now()
    start = now + timedelta(minutes=minutes_from_now)
    end = start + timedelta(minutes=30)
    return Meeting(
        title=title,
        start_time=start,
        end_time=end,
        calendar=calendar,
        starts_in_minutes=minutes_from_now,
    )


class TestMinutesSince:
    def test_recent_timestamp(self):
        ts = (datetime.now() - timedelta(minutes=10)).isoformat()
        assert 9.5 < _minutes_since(ts) < 10.5

    def test_old_timestamp(self):
        ts = (datetime.now() - timedelta(hours=3)).isoformat()
        assert 179 < _minutes_since(ts) < 181


class TestTriggerGate:
    async def test_prep_highest_priority(self, scheduler, mock_state):
        """PREP fires even when CHANGE and CATCHUP also qualify."""
        mock_state.get.return_value = None  # no prior state
        meeting = _meeting("1:1 Krzysztof", 10)

        trigger = await scheduler._evaluate_trigger_gate(
            has_local_changes=True,
            upcoming_meetings=[meeting],
            state=mock_state,
        )

        assert trigger is not None
        assert trigger.mode == "prep"
        assert trigger.context == meeting

    async def test_change_when_no_meeting_and_cooled_down(self, scheduler, mock_state):
        """CHANGE fires when local changes detected and cooldown expired."""
        mock_state.get.return_value = None

        trigger = await scheduler._evaluate_trigger_gate(
            has_local_changes=True,
            upcoming_meetings=[],
            state=mock_state,
        )

        assert trigger is not None
        assert trigger.mode == "change"

    async def test_change_skipped_in_cooldown(self, scheduler, mock_state):
        """CHANGE is suppressed when a nudge was sent < 30 min ago."""
        recent = (datetime.now() - timedelta(minutes=10)).isoformat()

        async def get_side_effect(key, default=None):
            if key == "gate:last_nudge_sent":
                return recent
            if key == "gate:prepped_meetings":
                return "[]"
            if key == "gate:last_mcp_check":
                return recent  # also recent, so no CATCHUP
            return default

        mock_state.get.side_effect = get_side_effect

        trigger = await scheduler._evaluate_trigger_gate(
            has_local_changes=True,
            upcoming_meetings=[],
            state=mock_state,
        )

        assert trigger is None  # suppressed

    async def test_catchup_after_2h(self, scheduler, mock_state):
        """CATCHUP fires when last MCP check was > 2h ago."""
        old = (datetime.now() - timedelta(hours=3)).isoformat()

        async def get_side_effect(key, default=None):
            if key == "gate:last_mcp_check":
                return old
            if key == "gate:prepped_meetings":
                return "[]"
            return default

        mock_state.get.side_effect = get_side_effect

        trigger = await scheduler._evaluate_trigger_gate(
            has_local_changes=False,
            upcoming_meetings=[],
            state=mock_state,
        )

        assert trigger is not None
        assert trigger.mode == "catchup"

    async def test_no_triggers(self, scheduler, mock_state):
        """No triggers when nothing changed, no meetings, MCP check recent."""
        recent = (datetime.now() - timedelta(minutes=30)).isoformat()

        async def get_side_effect(key, default=None):
            if key == "gate:last_mcp_check":
                return recent
            if key == "gate:prepped_meetings":
                return "[]"
            return default

        mock_state.get.side_effect = get_side_effect

        trigger = await scheduler._evaluate_trigger_gate(
            has_local_changes=False,
            upcoming_meetings=[],
            state=mock_state,
        )

        assert trigger is None

    async def test_prepped_meeting_not_retriggered(self, scheduler, mock_state):
        """A meeting already in prepped_meetings is skipped."""
        meeting = _meeting("1:1 Krzysztof", 10)
        prepped_key = f"{meeting.title}::{meeting.start_time.isoformat()}"

        async def get_side_effect(key, default=None):
            if key == "gate:prepped_meetings":
                return json.dumps([prepped_key])
            if key == "gate:last_mcp_check":
                return datetime.now().isoformat()
            return default

        mock_state.get.side_effect = get_side_effect

        trigger = await scheduler._evaluate_trigger_gate(
            has_local_changes=False,
            upcoming_meetings=[meeting],
            state=mock_state,
        )

        assert trigger is None  # meeting already prepped, no other triggers

    async def test_stale_prepped_meetings_cleaned(self, scheduler, mock_state):
        """Prepped meetings from previous days are cleaned up."""
        yesterday = (datetime.now() - timedelta(days=1))
        old_key = f"Old Meeting::{yesterday.isoformat()}"
        today_meeting = _meeting("Today Meeting", 10)
        today_key = f"Today Meeting::{today_meeting.start_time.isoformat()}"

        async def get_side_effect(key, default=None):
            if key == "gate:prepped_meetings":
                return json.dumps([old_key, today_key])
            if key == "gate:last_mcp_check":
                return datetime.now().isoformat()
            return default

        mock_state.get.side_effect = get_side_effect

        await scheduler._evaluate_trigger_gate(
            has_local_changes=False,
            upcoming_meetings=[today_meeting],
            state=mock_state,
        )

        # Should have cleaned up old_key and written back
        set_calls = [c for c in mock_state.set.call_args_list
                     if c[0][0] == "gate:prepped_meetings"]
        assert len(set_calls) >= 1
        cleaned = json.loads(set_calls[0][0][1])
        assert old_key not in cleaned
