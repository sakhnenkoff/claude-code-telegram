"""Tests for scan job type in the scheduler."""

import asyncio
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
    """Scan jobs pre-filter through SignalScanner before firing."""

    @pytest.mark.asyncio
    async def test_scan_job_fires_when_changes_detected(
        self, scheduler, event_bus, tmp_path
    ):
        """When scanner detects changes, event is published with signal-data wrapping."""
        scan_result = ScanResult(
            deltas=[SignalDelta(changed=True, summary="3 new commits on main")]
        )
        pending_state = {"git:main": "abc123"}

        mock_scanner = AsyncMock()
        mock_scanner.scan.return_value = (scan_result, pending_state)
        mock_scanner.commit_state = AsyncMock()

        with patch(_SCANNER_PATCH, return_value=mock_scanner):
            await scheduler._fire_event(
                job_name="midday-scan",
                prompt="Check for updates",
                working_directory=str(tmp_path),
                target_chat_ids=[456],
                skill_name=None,
                job_type="scan",
            )

        # Event was published
        event_bus.publish.assert_awaited_once()
        event = event_bus.publish.call_args[0][0]
        assert isinstance(event, ScheduledEvent)
        assert event.job_type == "scan"

        # Prompt injection safety: summary wrapped in signal-data tags
        assert event.prompt.startswith("<signal-data>")
        assert "<signal-data>" in event.prompt
        assert "3 new commits on main" in event.prompt
        assert "</signal-data>" in event.prompt

        # Two-phase commit: state committed after publish
        mock_scanner.commit_state.assert_awaited_once_with(pending_state)

    @pytest.mark.asyncio
    async def test_scan_job_silent_when_no_changes(
        self, scheduler, event_bus, tmp_path
    ):
        """When scanner detects no local changes, Claude still runs with MCP context."""
        scan_result = ScanResult(deltas=[SignalDelta(changed=False, summary="")])
        pending_state = {}

        mock_scanner = AsyncMock()
        mock_scanner.scan.return_value = (scan_result, pending_state)
        mock_scanner.commit_state = AsyncMock()

        with patch(_SCANNER_PATCH, return_value=mock_scanner):
            await scheduler._fire_event(
                job_name="midday-scan",
                prompt="Check for updates",
                working_directory=str(tmp_path),
                target_chat_ids=[456],
                skill_name=None,
                job_type="scan",
            )

        event_bus.publish.assert_awaited_once()
        event = event_bus.publish.call_args[0][0]
        assert isinstance(event, ScheduledEvent)
        assert "No local changes detected since last scan." in event.prompt

        # State is not committed without actual local changes
        mock_scanner.commit_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scan_job_does_not_commit_state_on_publish_failure(
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

        event_bus.publish = AsyncMock(side_effect=RuntimeError("bus broken"))

        with patch(_SCANNER_PATCH, return_value=mock_scanner):
            with pytest.raises(RuntimeError, match="bus broken"):
                await scheduler._fire_event(
                    job_name="midday-scan",
                    prompt="Check for updates",
                    working_directory=str(tmp_path),
                    target_chat_ids=[456],
                    skill_name=None,
                    job_type="scan",
                )

        # State must NOT be committed since publish failed
        mock_scanner.commit_state.assert_not_awaited()


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

        with patch(_SCANNER_PATCH, return_value=mock_scanner):
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
        # Without the lock they would interleave:
        # scan_start, scan_start, scan_end, scan_end
        assert execution_order == [
            "scan_start",
            "scan_end",
            "scan_start",
            "scan_end",
        ]
