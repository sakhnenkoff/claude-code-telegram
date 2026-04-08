"""Tests for event handlers."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.events.bus import EventBus
from src.events.handlers import AgentHandler
from src.events.types import AgentResponseEvent, ScheduledEvent, WebhookEvent


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def mock_claude() -> AsyncMock:
    mock = AsyncMock()
    mock.run_command = AsyncMock()
    return mock


@pytest.fixture
def agent_handler(event_bus: EventBus, mock_claude: AsyncMock) -> AgentHandler:
    handler = AgentHandler(
        event_bus=event_bus,
        claude_integration=mock_claude,
        default_working_directory=Path("/tmp/test"),
        default_user_id=42,
    )
    handler.register()
    return handler


class TestAgentHandler:
    """Tests for AgentHandler."""

    async def test_webhook_event_triggers_claude(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """Webhook events are processed through Claude."""
        mock_response = MagicMock()
        mock_response.content = "Analysis complete"
        mock_claude.run_command.return_value = mock_response

        published: list = []
        original_publish = event_bus.publish

        async def capture_publish(event):  # type: ignore[no-untyped-def]
            published.append(event)
            await original_publish(event)

        event_bus.publish = capture_publish  # type: ignore[assignment]

        event = WebhookEvent(
            provider="github",
            event_type_name="push",
            payload={"ref": "refs/heads/main"},
            delivery_id="del-1",
        )

        await agent_handler.handle_webhook(event)

        mock_claude.run_command.assert_called_once()
        call_kwargs = mock_claude.run_command.call_args
        assert "github" in call_kwargs.kwargs["prompt"].lower()

        # Should publish an AgentResponseEvent
        response_events = [e for e in published if isinstance(e, AgentResponseEvent)]
        assert len(response_events) == 1
        assert response_events[0].text == "Analysis complete"

    async def test_scheduled_event_triggers_claude(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """Scheduled events invoke Claude with the job's prompt."""
        mock_response = MagicMock()
        mock_response.content = "Standup summary"
        mock_response.session_id = "test-session"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        published: list = []
        original_publish = event_bus.publish

        async def capture_publish(event):  # type: ignore[no-untyped-def]
            published.append(event)
            await original_publish(event)

        event_bus.publish = capture_publish  # type: ignore[assignment]

        event = ScheduledEvent(
            job_name="standup",
            prompt="Generate daily standup",
            target_chat_ids=[100],
        )

        await agent_handler.handle_scheduled(event)

        mock_claude.run_command.assert_called_once()
        assert "standup" in mock_claude.run_command.call_args.kwargs["prompt"].lower()

        response_events = [e for e in published if isinstance(e, AgentResponseEvent)]
        assert len(response_events) == 1
        assert response_events[0].chat_id == 100

    async def test_scheduled_event_with_skill(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """Scheduled events with skill_name prepend the skill invocation."""
        mock_response = MagicMock()
        mock_response.content = "Done"
        mock_response.session_id = "test-session"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        event = ScheduledEvent(
            job_name="standup",
            prompt="morning report",
            skill_name="daily-standup",
            target_chat_ids=[100],
        )

        await agent_handler.handle_scheduled(event)

        prompt = mock_claude.run_command.call_args.kwargs["prompt"]
        assert prompt.startswith("/daily-standup")
        assert "morning report" in prompt

    async def test_scheduled_silent_response_is_suppressed(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """SILENT responses from scheduled jobs are not forwarded to Telegram."""
        mock_response = MagicMock()
        mock_response.content = "SILENT"
        mock_response.session_id = "test-session"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        published: list = []
        original_publish = event_bus.publish

        async def capture_publish(event):  # type: ignore[no-untyped-def]
            published.append(event)
            await original_publish(event)

        event_bus.publish = capture_publish  # type: ignore[assignment]

        event = ScheduledEvent(
            job_name="Signal Scan",
            prompt="Check signals",
            target_chat_ids=[100],
        )

        await agent_handler.handle_scheduled(event)
        await asyncio.sleep(0)

        response_events = [e for e in published if isinstance(e, AgentResponseEvent)]
        assert len(response_events) == 0, "SILENT response should not be forwarded"

    async def test_scheduled_heartbeat_ok_is_suppressed(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """HEARTBEAT_OK responses are also suppressed."""
        mock_response = MagicMock()
        mock_response.content = "HEARTBEAT_OK"
        mock_response.session_id = "test-session"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        published: list = []
        original_publish = event_bus.publish

        async def capture_publish(event):  # type: ignore[no-untyped-def]
            published.append(event)
            await original_publish(event)

        event_bus.publish = capture_publish  # type: ignore[assignment]

        event = ScheduledEvent(
            job_name="Signal Scan",
            prompt="Check signals",
            target_chat_ids=[100],
        )

        await agent_handler.handle_scheduled(event)
        await asyncio.sleep(0)

        response_events = [e for e in published if isinstance(e, AgentResponseEvent)]
        assert len(response_events) == 0, "HEARTBEAT_OK should not be forwarded"

    async def test_scheduled_actionable_response_is_forwarded(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """Non-suppression responses are forwarded normally."""
        mock_response = MagicMock()
        mock_response.content = "You have a PR review waiting"
        mock_response.session_id = "test-session"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        published: list = []
        original_publish = event_bus.publish

        async def capture_publish(event):  # type: ignore[no-untyped-def]
            published.append(event)
            await original_publish(event)

        event_bus.publish = capture_publish  # type: ignore[assignment]

        event = ScheduledEvent(
            job_name="Signal Scan",
            prompt="Check signals",
            target_chat_ids=[100],
        )

        await agent_handler.handle_scheduled(event)
        await asyncio.sleep(0)

        response_events = [e for e in published if isinstance(e, AgentResponseEvent)]
        assert len(response_events) == 1
        assert response_events[0].text == "You have a PR review waiting"

    async def test_scheduled_uses_force_new(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """Scheduled jobs always start fresh sessions."""
        mock_response = MagicMock()
        mock_response.content = "Result"
        mock_response.session_id = "test-session"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        event = ScheduledEvent(
            job_name="standup",
            prompt="Generate standup",
            target_chat_ids=[100],
        )

        await agent_handler.handle_scheduled(event)
        await asyncio.sleep(0)

        call_kwargs = mock_claude.run_command.call_args.kwargs
        assert call_kwargs.get("force_new") is True, (
            "Scheduled jobs must use force_new=True"
        )

    async def test_scheduled_cleans_up_session(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """Scheduled job sessions are cleaned up after execution."""
        mock_response = MagicMock()
        mock_response.content = "Result"
        mock_response.session_id = "heartbeat-session-123"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        event = ScheduledEvent(
            job_name="standup",
            prompt="Generate standup",
            target_chat_ids=[100],
        )

        await agent_handler.handle_scheduled(event)
        await asyncio.sleep(0)

        mock_claude.session_manager.remove_session.assert_called_once_with(
            "heartbeat-session-123"
        )

    async def test_claude_error_does_not_propagate(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """Agent errors are logged but don't crash the handler."""
        mock_claude.run_command.side_effect = RuntimeError("SDK error")

        event = WebhookEvent(
            provider="github",
            event_type_name="push",
            payload={},
        )

        # Should not raise
        await agent_handler.handle_webhook(event)

    def test_build_webhook_prompt(self, agent_handler: AgentHandler) -> None:
        """Webhook prompt includes provider and event info."""
        event = WebhookEvent(
            provider="github",
            event_type_name="pull_request",
            payload={"action": "opened", "number": 42},
        )

        prompt = agent_handler._build_webhook_prompt(event)
        assert "github" in prompt.lower()
        assert "pull_request" in prompt
        assert "action: opened" in prompt

    def test_payload_summary_truncation(self, agent_handler: AgentHandler) -> None:
        """Large payloads are truncated in the summary."""
        big_payload = {"key": "x" * 3000}
        summary = agent_handler._summarize_payload(big_payload)
        assert len(summary) <= 2100  # 2000 + truncation message

    async def test_catchup_updates_last_mcp_check(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """CATCHUP mode updates gate:last_mcp_check after Claude completes."""
        mock_response = MagicMock()
        mock_response.content = "You have 3 unread DMs"
        mock_response.session_id = "test-session"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        event = ScheduledEvent(
            job_name="Signal Scan",
            prompt="Catchup check",
            target_chat_ids=[100],
            working_directory=Path("/tmp/test-vault"),
            trigger_mode="catchup",
        )

        with patch("src.events.handlers.StateStore") as mock_store_cls:
            mock_store = AsyncMock()
            mock_store_cls.return_value = mock_store

            await agent_handler.handle_scheduled(event)
            await asyncio.sleep(0.1)

            # last_mcp_check should be updated for catchup
            set_calls = [c for c in mock_store.set.call_args_list
                         if c[0][0] == "gate:last_mcp_check"]
            assert len(set_calls) == 1

    async def test_change_does_not_update_last_mcp_check(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """CHANGE mode does NOT update gate:last_mcp_check."""
        mock_response = MagicMock()
        mock_response.content = "3 commits pushed"
        mock_response.session_id = "test-session"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        event = ScheduledEvent(
            job_name="Signal Scan",
            prompt="Change notification",
            target_chat_ids=[100],
            working_directory=Path("/tmp/test-vault"),
            trigger_mode="change",
        )

        with patch("src.events.handlers.StateStore") as mock_store_cls:
            mock_store = AsyncMock()
            mock_store_cls.return_value = mock_store

            await agent_handler.handle_scheduled(event)
            await asyncio.sleep(0.1)

            mcp_calls = [c for c in mock_store.set.call_args_list
                         if c[0][0] == "gate:last_mcp_check"]
            assert len(mcp_calls) == 0  # CHANGE doesn't reset MCP timer

    async def test_catchup_silent_still_updates_last_mcp_check(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """CATCHUP + SILENT still updates last_mcp_check (full scan ran)."""
        mock_response = MagicMock()
        mock_response.content = "SILENT"
        mock_response.session_id = "test-session"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        event = ScheduledEvent(
            job_name="Signal Scan",
            prompt="Catchup",
            target_chat_ids=[100],
            working_directory=Path("/tmp/test-vault"),
            trigger_mode="catchup",
        )

        with patch("src.events.handlers.StateStore") as mock_store_cls:
            mock_store = AsyncMock()
            mock_store_cls.return_value = mock_store
            await agent_handler.handle_scheduled(event)
            await asyncio.sleep(0.1)

            mcp_calls = [c for c in mock_store.set.call_args_list
                         if c[0][0] == "gate:last_mcp_check"]
            assert len(mcp_calls) == 1  # updated even though SILENT

    async def test_prep_does_not_update_last_nudge_sent(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """PREP mode does NOT update gate:last_nudge_sent (bypasses cooldown)."""
        mock_response = MagicMock()
        mock_response.content = "Meeting prep info"
        mock_response.session_id = "test-session"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        event = ScheduledEvent(
            job_name="Signal Scan",
            prompt="Prep",
            target_chat_ids=[100],
            working_directory=Path("/tmp/test-vault"),
            trigger_mode="prep",
        )

        with patch("src.events.handlers.StateStore") as mock_store_cls:
            mock_store = AsyncMock()
            mock_store_cls.return_value = mock_store
            await agent_handler.handle_scheduled(event)
            await asyncio.sleep(0.1)

            nudge_calls = [c for c in mock_store.set.call_args_list
                           if c[0][0] == "gate:last_nudge_sent"]
            assert len(nudge_calls) == 0  # PREP doesn't update cooldown

    async def test_change_actionable_updates_last_nudge_sent(
        self, event_bus: EventBus, mock_claude: AsyncMock, agent_handler: AgentHandler
    ) -> None:
        """CHANGE with actionable response DOES update gate:last_nudge_sent."""
        mock_response = MagicMock()
        mock_response.content = "3 commits pushed"
        mock_response.session_id = "test-session"
        mock_claude.run_command.return_value = mock_response
        mock_claude.session_manager = AsyncMock()

        event = ScheduledEvent(
            job_name="Signal Scan",
            prompt="Change",
            target_chat_ids=[100],
            working_directory=Path("/tmp/test-vault"),
            trigger_mode="change",
        )

        with patch("src.events.handlers.StateStore") as mock_store_cls:
            mock_store = AsyncMock()
            mock_store_cls.return_value = mock_store
            await agent_handler.handle_scheduled(event)
            await asyncio.sleep(0.1)

            nudge_calls = [c for c in mock_store.set.call_args_list
                           if c[0][0] == "gate:last_nudge_sent"]
            assert len(nudge_calls) == 1
