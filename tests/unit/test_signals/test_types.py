from src.signals import SignalDelta, ScanResult

class TestSignalDelta:
    def test_no_change(self):
        delta = SignalDelta(changed=False, summary="")
        assert not delta.changed
        assert delta.summary == ""

    def test_with_change(self):
        delta = SignalDelta(changed=True, summary="2 new commits")
        assert delta.changed
        assert "2 new commits" in delta.summary

class TestScanResult:
    def test_no_changes(self):
        deltas = [SignalDelta(changed=False, summary=""), SignalDelta(changed=False, summary="")]
        result = ScanResult(deltas=deltas)
        assert not result.has_changes
        assert result.summary == ""

    def test_with_changes(self):
        deltas = [
            SignalDelta(changed=True, summary="3 new commits in ios-app"),
            SignalDelta(changed=False, summary=""),
            SignalDelta(changed=True, summary="inbox: 6 → 9 items"),
        ]
        result = ScanResult(deltas=deltas)
        assert result.has_changes
        assert "3 new commits" in result.summary
        assert "inbox" in result.summary

    def test_summary_joins_with_newlines(self):
        deltas = [
            SignalDelta(changed=True, summary="Git: 1 commit"),
            SignalDelta(changed=True, summary="Inbox: +2 items"),
        ]
        result = ScanResult(deltas=deltas)
        assert result.summary == "- Git: 1 commit\n- Inbox: +2 items"
