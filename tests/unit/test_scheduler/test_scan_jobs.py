"""Tests for scan job type in the scheduler."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.events.bus import EventBus
from src.events.types import ScheduledEvent
from src.scheduler.scheduler import JobScheduler
from src.signals import ScanResult, SignalDelta
from src.storage.database import DatabaseManager


@pytest.fixture
def event_bus():
    bus = EventBus()
    bus.publish = AsyncMock(wraps=bus.publish)
    return bus


@pytest.fixture
def scheduler(event_bus, tmp_path):
    db_manager = MagicMock(spec=DatabaseManager)
    return JobScheduler(
        event_bus=event_bus,
        db_manager=db_manager,
        default_working_directory=tmp_path,
    )


# Patch target: the class in its defining module, which the local import resolves from
_SCANNER_PATCH = "src.signals.scanner.SignalScanner"
_CAL_PATCH = "src.scheduler.scheduler.CalendarDetector"


def _mock_state(last_mcp_check=None, last_nudge_sent=None):
    """Create a mock StateStore for the trigger gate."""
    state = AsyncMock()

    async def get_side_effect(key, default=None):
        if key == "gate:last_mcp_check":
            return last_mcp_check
        if key == "gate:last_nudge_sent":
            return last_nudge_sent
        if key == "gate:prepped_meetings":
            return "[]"
        return default

    state.get = AsyncMock(side_effect=get_side_effect)
    state.set = AsyncMock()
    return state


class TestAnchorJobType:
    """Anchor jobs always fire events unconditionally."""

    @pytest.mark.asyncio
    async def test_anchor_job_always_fires_event(self, scheduler, event_bus, tmp_path):
        """An anchor job publishes a ScheduledEvent regardless of signal state."""
        await scheduler._fire_event(
            job_name="morning-briefing",
            prompt="Good morning",
            working_directory=str(tmp_path),
            target_chat_ids=[123],
            skill_name=None,
            job_type="anchor",
        )

        event_bus.publish.assert_awaited_once()
        event = event_bus.publish.call_args[0][0]
        assert isinstance(event, ScheduledEvent)
        assert event.job_name == "morning-briefing"
        assert event.prompt == "Good morning"
        assert event.job_type == "anchor"


class TestScanJobType:
    """Scan jobs go through the trigger gate before invoking Claude."""

    @pytest.mark.asyncio
    async def test_scan_with_changes_fires_change_trigger(
        self, scheduler, event_bus, tmp_path
    ):
        """When scanner detects changes and cooldown expired, CHANGE trigger fires."""
        scan_result = ScanResult(
            deltas=[SignalDelta(changed=True, summary="3 new commits on main")]
        )
        pending_state = {"git:main": "abc123"}

        mock_scanner = AsyncMock()
        mock_scanner.scan.return_value = (scan_result, pending_state)
        mock_scanner.commit_state = AsyncMock()
        mock_scanner.state = _mock_state()  # no prior state = cooldown expired

        mock_cal = AsyncMock()
        mock_cal.detect.return_value = []  # no upcoming meetings

        with patch(_SCANNER_PATCH, return_value=mock_scanner), \
             patch(_CAL_PATCH, return_value=mock_cal):
            await scheduler._fire_event(
                job_name="Signal Scan",
                prompt="Check for updates",
                working_directory=str(tmp_path),
                target_chat_ids=[456],
                skill_name=None,
                job_type="scan",
            )

        # Event was published with CHANGE trigger
        event_bus.publish.assert_awaited_once()
        event = event_bus.publish.call_args[0][0]
        assert isinstance(event, ScheduledEvent)
        assert event.job_type == "scan"
        assert event.trigger_mode == "change"

        # Prompt wrapped in signal-data tags
        assert "<signal-data>" in event.prompt
        assert "3 new commits on main" in event.prompt
        assert "</signal-data>" in event.prompt

        # Two-phase commit: state committed after publish
        mock_scanner.commit_state.assert_awaited_once_with(pending_state)

    @pytest.mark.asyncio
    async def test_scan_no_triggers_skips_claude(
        self, scheduler, event_bus, tmp_path
    ):
        """No changes + no meetings + recent MCP check = no event published."""
        scan_result = ScanResult(deltas=[SignalDelta(changed=False, summary="")])
        pending_state = {}

        # Recent MCP check = no CATCHUP trigger either
        recent = (datetime.now() - timedelta(minutes=30)).isoformat()

        mock_scanner = AsyncMock()
        mock_scanner.scan.return_value = (scan_result, pending_state)
        mock_scanner.commit_state = AsyncMock()
        mock_scanner.state = _mock_state(last_mcp_check=recent)

        mock_cal = AsyncMock()
        mock_cal.detect.return_value = []

        with patch(_SCANNER_PATCH, return_value=mock_scanner), \
             patch(_CAL_PATCH, return_value=mock_cal):
            await scheduler._fire_event(
                job_name="Signal Scan",
                prompt="Check for updates",
                working_directory=str(tmp_path),
                target_chat_ids=[456],
                skill_name=None,
                job_type="scan",
            )

        # No event published — gate returned None
        event_bus.publish.assert_not_awaited()
        mock_scanner.commit_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scan_catchup_fires_after_2h(
        self, scheduler, event_bus, tmp_path
    ):
        """No changes but last MCP check > 2h ago triggers CATCHUP."""
        scan_result = ScanResult(deltas=[SignalDelta(changed=False, summary="")])
        pending_state = {}

        old = (datetime.now() - timedelta(hours=3)).isoformat()

        mock_scanner = AsyncMock()
        mock_scanner.scan.return_value = (scan_result, pending_state)
        mock_scanner.commit_state = AsyncMock()
        mock_scanner.state = _mock_state(last_mcp_check=old)

        mock_cal = AsyncMock()
        mock_cal.detect.return_value = []

        with patch(_SCANNER_PATCH, return_value=mock_scanner), \
             patch(_CAL_PATCH, return_value=mock_cal):
            await scheduler._fire_event(
                job_name="Signal Scan",
                prompt="Check for updates",
                working_directory=str(tmp_path),
                target_chat_ids=[456],
                skill_name=None,
                job_type="scan",
            )

        event_bus.publish.assert_awaited_once()
        event = event_bus.publish.call_args[0][0]
        assert event.trigger_mode == "catchup"

    @pytest.mark.asyncio
    async def test_scan_does_not_commit_state_on_publish_failure(
        self, scheduler, event_bus, tmp_path
    ):
        """Two-phase commit: if publish fails, scanner state is NOT committed."""
        scan_result = ScanResult(
            deltas=[SignalDelta(changed=True, summary="new tasks")]
        )
        pending_state = {"tasks:hash": "xyz"}

        mock_scanner = AsyncMock()
        mock_scanner.scan.return_value = (scan_result, pending_state)
        mock_scanner.commit_state = AsyncMock()
        mock_scanner.state = _mock_state()

        mock_cal = AsyncMock()
        mock_cal.detect.return_value = []

        event_bus.publish = AsyncMock(side_effect=RuntimeError("bus broken"))

        with patch(_SCANNER_PATCH, return_value=mock_scanner), \
             patch(_CAL_PATCH, return_value=mock_cal):
            with pytest.raises(RuntimeError, match="bus broken"):
                await scheduler._fire_event(
                    job_name="Signal Scan",
                    prompt="Check for updates",
                    working_directory=str(tmp_path),
                    target_chat_ids=[456],
                    skill_name=None,
                    job_type="scan",
                )

        # State must NOT be committed since publish failed
        mock_scanner.commit_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scan_commits_state_even_when_no_trigger(
        self, scheduler, event_bus, tmp_path
    ):
        """Changes detected but in cooldown: state still committed to prevent re-detect."""
        scan_result = ScanResult(
            deltas=[SignalDelta(changed=True, summary="git changed")]
        )
        pending_state = {"git:repo": "abc"}

        # Recent nudge = in cooldown, recent MCP = no CATCHUP
        recent = (datetime.now() - timedelta(minutes=5)).isoformat()

        mock_scanner = AsyncMock()
        mock_scanner.scan.return_value = (scan_result, pending_state)
        mock_scanner.commit_state = AsyncMock()
        mock_scanner.state = _mock_state(
            last_nudge_sent=recent, last_mcp_check=recent
        )

        mock_cal = AsyncMock()
        mock_cal.detect.return_value = []

        with patch(_SCANNER_PATCH, return_value=mock_scanner), \
             patch(_CAL_PATCH, return_value=mock_cal):
            await scheduler._fire_event(
                job_name="Signal Scan",
                prompt="Check for updates",
                working_directory=str(tmp_path),
                target_chat_ids=[456],
                skill_name=None,
                job_type="scan",
            )

        # No event published (in cooldown)
        event_bus.publish.assert_not_awaited()
        # But state IS committed so the same changes don't re-detect
        mock_scanner.commit_state.assert_awaited_once_with(pending_state)


class TestScanLock:
    """Scan lock serializes concurrent scan jobs."""

    @pytest.mark.asyncio
    async def test_scan_lock_serializes_concurrent_scans(
        self, scheduler, event_bus, tmp_path
    ):
        """Two concurrent scan jobs run sequentially, not in parallel."""
        execution_order = []

        async def slow_scan():
            execution_order.append("scan_start")
            await asyncio.sleep(0.05)
            execution_order.append("scan_end")
            return (
                ScanResult(
                    deltas=[SignalDelta(changed=True, summary="changes found")]
                ),
                {"key": "value"},
            )

        mock_scanner = AsyncMock()
        mock_scanner.scan = slow_scan
        mock_scanner.commit_state = AsyncMock()
        mock_scanner.state = _mock_state()

        mock_cal = AsyncMock()
        mock_cal.detect.return_value = []

        with patch(_SCANNER_PATCH, return_value=mock_scanner), \
             patch(_CAL_PATCH, return_value=mock_cal):
            # Launch two scan jobs concurrently
            await asyncio.gather(
                scheduler._fire_event(
                    job_name="scan-1",
                    prompt="Prompt 1",
                    working_directory=str(tmp_path),
                    target_chat_ids=[1],
                    skill_name=None,
                    job_type="scan",
                ),
                scheduler._fire_event(
                    job_name="scan-2",
                    prompt="Prompt 2",
                    working_directory=str(tmp_path),
                    target_chat_ids=[2],
                    skill_name=None,
                    job_type="scan",
                ),
            )

        # With the lock, scans must be serialized:
        # scan_start, scan_end, scan_start, scan_end
        assert execution_order == [
            "scan_start",
            "scan_end",
            "scan_start",
            "scan_end",
        ]
