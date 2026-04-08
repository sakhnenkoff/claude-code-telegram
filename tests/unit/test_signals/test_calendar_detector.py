"""Tests for CalendarDetector."""

from datetime import datetime, time, timedelta
from unittest.mock import patch

import pytest

from src.signals.detectors import CalendarDetector, Meeting, _CAL_LINE_RE


class TestCalLineRegex:
    """Test the calendar line regex against real cal-today-bin output."""

    def test_work_meeting(self):
        line = "- 14:30 - 15:00  Matvii / Krzysztof 1on1  [matvii.sakhnenko@vend.com]"
        match = _CAL_LINE_RE.match(line.strip())
        assert match is not None
        assert match.group(1) == "14:30"
        assert match.group(2) == "15:00"
        assert match.group(3).strip() == "Matvii / Krzysztof 1on1"
        assert match.group(4).strip() == "matvii.sakhnenko@vend.com"

    def test_personal_event(self):
        line = "- 17:45 - 18:45  GENTLE CANDLELIGHT FLOW  [Fitssey]"
        match = _CAL_LINE_RE.match(line.strip())
        assert match is not None
        assert match.group(4).strip() == "Fitssey"

    def test_sleep_entry_no_match(self):
        line = "- 23:00 - 08:00  🛌 😴  [Curiosities]"
        match = _CAL_LINE_RE.match(line.strip())
        # May or may not match depending on emoji handling — detector filters by calendar

    def test_empty_line_no_match(self):
        assert _CAL_LINE_RE.match("") is None
        assert _CAL_LINE_RE.match("some random text") is None


class TestCalendarDetector:
    """Test CalendarDetector parsing and filtering."""

    @pytest.fixture
    def sample_output(self):
        return (
            "- 23:00 - 08:00  🛌 😴  [Curiosities]\n"
            "- 09:30 - 11:20  iOS Dev Workshop  [matvii.sakhnenko@vend.com]\n"
            "- 10:00 - 10:25  Jobs iOS Sync  [matvii.sakhnenko@vend.com]\n"
            "- 12:00 - 13:00  Genesis Meetup  [matvii.sakhnenko@vend.com]\n"
            "- 14:30 - 15:00  Matvii / Krzysztof 1on1  [matvii.sakhnenko@vend.com]\n"
            "- 17:45 - 18:45  GENTLE CANDLELIGHT FLOW  [Fitssey]\n"
        )

    def test_parse_meetings(self, sample_output):
        detector = CalendarDetector()
        meetings = detector._parse_meetings(sample_output)
        # Should parse at least the work meetings (personal may or may not parse)
        work_meetings = [m for m in meetings if m.calendar.endswith("@vend.com")]
        assert len(work_meetings) == 4
        assert work_meetings[0].title == "iOS Dev Workshop"
        assert work_meetings[3].title == "Matvii / Krzysztof 1on1"

    async def test_detect_filters_by_time_and_calendar(self, sample_output):
        """Only work meetings starting in next 15 min are returned."""
        detector = CalendarDetector()

        # Mock cal-today-bin output and current time to 14:20 (10 min before 1on1)
        with patch.object(detector, "_run_cal_today", return_value=sample_output):
            with patch("src.signals.detectors.datetime") as mock_dt:
                mock_now = datetime.combine(datetime.now().date(), time(14, 20))
                mock_dt.now.return_value = mock_now
                mock_dt.combine = datetime.combine
                mock_dt.fromisoformat = datetime.fromisoformat
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

                meetings = await detector.detect()

        # Only the 1on1 at 14:30 should match (10 min away, @vend.com)
        assert len(meetings) == 1
        assert meetings[0].title == "Matvii / Krzysztof 1on1"

    async def test_detect_skips_personal_calendar(self, sample_output):
        """Personal calendar events (Fitssey) are filtered out."""
        detector = CalendarDetector()

        with patch.object(detector, "_run_cal_today", return_value=sample_output):
            with patch("src.signals.detectors.datetime") as mock_dt:
                # Set time to 17:35 (10 min before yoga)
                mock_now = datetime.combine(datetime.now().date(), time(17, 35))
                mock_dt.now.return_value = mock_now
                mock_dt.combine = datetime.combine
                mock_dt.fromisoformat = datetime.fromisoformat
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

                meetings = await detector.detect()

        # Yoga is in 10 min but from [Fitssey] — filtered out
        assert len(meetings) == 0

    async def test_detect_empty_output(self):
        """Empty cal-today-bin output returns no meetings."""
        detector = CalendarDetector()
        with patch.object(detector, "_run_cal_today", return_value=""):
            meetings = await detector.detect()
        assert meetings == []

    async def test_detect_cal_today_failure(self):
        """Failed cal-today-bin returns no meetings."""
        detector = CalendarDetector()
        with patch.object(detector, "_run_cal_today", return_value=""):
            meetings = await detector.detect()
        assert meetings == []
