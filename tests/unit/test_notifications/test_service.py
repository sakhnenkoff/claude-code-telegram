"""Tests for the notification service."""

from unittest.mock import AsyncMock

import pytest

from src.events.bus import EventBus
from src.events.types import AgentResponseEvent
from src.notifications.service import NotificationService


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def mock_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def service(event_bus: EventBus, mock_bot: AsyncMock) -> NotificationService:
    svc = NotificationService(
        event_bus=event_bus,
        bot=mock_bot,
        default_chat_ids=[100, 200],
    )
    svc.register()
    return svc


class TestNotificationService:
    """Tests for NotificationService."""

    async def test_handle_response_queues_event(
        self, service: NotificationService
    ) -> None:
        """Events are queued for delivery."""
        event = AgentResponseEvent(chat_id=100, text="hello")
        await service.handle_response(event)
        assert service._send_queue.qsize() == 1

    async def test_resolve_chat_ids_specific(
        self, service: NotificationService
    ) -> None:
        """Specific chat_id takes precedence over defaults."""
        event = AgentResponseEvent(chat_id=999, text="test")
        ids = service._resolve_chat_ids(event)
        assert ids == [999]

    async def test_resolve_chat_ids_default(self, service: NotificationService) -> None:
        """chat_id=0 falls back to default chat IDs."""
        event = AgentResponseEvent(chat_id=0, text="test")
        ids = service._resolve_chat_ids(event)
        assert ids == [100, 200]

    def test_split_message_short(self, service: NotificationService) -> None:
        """Short messages are not split."""
        chunks = service._split_message("short text")
        assert len(chunks) == 1
        assert chunks[0] == "short text"

    def test_split_message_long(self, service: NotificationService) -> None:
        """Long messages are split at boundaries."""
        text = "A" * 4000 + "\n\n" + "B" * 200
        chunks = service._split_message(text, max_length=4096)
        assert len(chunks) >= 1
        # All content preserved
        total_len = sum(len(c) for c in chunks)
        assert total_len > 0

    def test_split_message_no_boundary(self, service: NotificationService) -> None:
        """Messages without boundaries are hard-split at default 4000."""
        text = "A" * 5000  # No newlines or spaces
        chunks = service._split_message(text)
        assert len(chunks) == 2
        assert len(chunks[0]) == 4000
        assert len(chunks[1]) == 1000

    async def test_send_to_telegram(
        self, service: NotificationService, mock_bot: AsyncMock
    ) -> None:
        """Messages are sent via the Telegram bot."""
        event = AgentResponseEvent(chat_id=123, text="hello world")
        await service._rate_limited_send(123, event)

        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 123
        assert call_kwargs["text"] == "hello world"

    async def test_ignores_non_response_events(
        self, service: NotificationService
    ) -> None:
        """Non-AgentResponseEvent events are ignored."""
        from src.events.bus import Event

        event = Event(source="test")
        await service.handle_response(event)
        assert service._send_queue.qsize() == 0

    async def test_html_formatting_applied(
        self, service: NotificationService, mock_bot: AsyncMock
    ) -> None:
        """Markdown is converted to HTML before sending."""
        event = AgentResponseEvent(
            chat_id=123,
            text="**bold** and *italic*",
            parse_mode="HTML",
        )
        await service._rate_limited_send(123, event)

        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert "<b>bold</b>" in call_kwargs["text"]
        assert "<i>italic</i>" in call_kwargs["text"]

    async def test_no_formatting_when_parse_mode_none(
        self, service: NotificationService, mock_bot: AsyncMock
    ) -> None:
        """Text passes through unchanged when parse_mode is None."""
        raw = "**bold** and _italic_"
        event = AgentResponseEvent(
            chat_id=123,
            text=raw,
            parse_mode=None,
        )
        await service._rate_limited_send(123, event)

        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["text"] == raw
        assert call_kwargs.get("parse_mode") is None

    async def test_fallback_on_telegram_error(
        self, service: NotificationService, mock_bot: AsyncMock
    ) -> None:
        """Falls back to plain text when HTML send fails."""
        from telegram.error import TelegramError

        # First call raises, second (fallback) succeeds
        mock_bot.send_message.side_effect = [
            TelegramError("Bad markup"),
            None,
        ]
        event = AgentResponseEvent(
            chat_id=123,
            text="**bold**",
            parse_mode="HTML",
        )
        await service._rate_limited_send(123, event)

        assert mock_bot.send_message.call_count == 2
        # Second call should have no parse_mode
        fallback_kwargs = mock_bot.send_message.call_args_list[1].kwargs
        assert fallback_kwargs.get("parse_mode") is None
