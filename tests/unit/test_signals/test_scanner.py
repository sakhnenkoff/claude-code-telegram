from pathlib import Path

import pytest

from src.signals.state import StateStore


def _create_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "inbox").mkdir(parents=True)
    (vault / "tasks").mkdir()
    (vault / "projects").mkdir()
    return vault


@pytest.mark.asyncio
async def test_first_scan_baselines_without_reporting_changes(
    tmp_path: Path,
) -> None:
    from src.signals import SignalScanner

    vault = _create_vault(tmp_path)
    scanner = SignalScanner(vault, tmp_path / "signals.db")

    result, pending = await scanner.scan()

    assert not result.has_changes
    assert result.summary == ""
    assert pending["inbox:count"] == "0"
    assert pending["tasks:open"] == "0"
    assert pending["projects:statuses"] == "{}"


@pytest.mark.asyncio
async def test_scan_reports_inbox_change_after_committed_baseline(
    tmp_path: Path,
) -> None:
    from src.signals import SignalScanner

    vault = _create_vault(tmp_path)
    scanner = SignalScanner(vault, tmp_path / "signals.db")

    _, baseline_pending = await scanner.scan()
    await scanner.commit_state(baseline_pending)

    (vault / "inbox" / "note.md").write_text("# Note\n", encoding="utf-8")

    result, pending = await scanner.scan()

    assert result.has_changes
    assert "Inbox" in result.summary
    assert pending["inbox:count"] == "1"


@pytest.mark.asyncio
async def test_scan_without_changes_returns_no_changes(
    tmp_path: Path,
) -> None:
    from src.signals import SignalScanner

    vault = _create_vault(tmp_path)
    scanner = SignalScanner(vault, tmp_path / "signals.db")

    _, baseline_pending = await scanner.scan()
    await scanner.commit_state(baseline_pending)
    (vault / "inbox" / "note.md").write_text("# Note\n", encoding="utf-8")

    _, changed_pending = await scanner.scan()
    await scanner.commit_state(changed_pending)

    result, pending = await scanner.scan()

    assert not result.has_changes
    assert result.summary == ""
    assert pending["inbox:count"] == "1"


@pytest.mark.asyncio
async def test_commit_state_persists_pending_values(
    tmp_path: Path,
) -> None:
    from src.signals import SignalScanner

    vault = _create_vault(tmp_path)
    db_path = tmp_path / "signals.db"
    scanner = SignalScanner(vault, db_path)

    _, pending = await scanner.scan()
    await scanner.commit_state(pending)

    store = StateStore(db_path)
    await store.initialize()

    for key, value in pending.items():
        assert await store.get(key) == value


@pytest.mark.asyncio
async def test_scan_redetects_same_change_when_state_is_not_committed(
    tmp_path: Path,
) -> None:
    from src.signals import SignalScanner

    vault = _create_vault(tmp_path)
    scanner = SignalScanner(vault, tmp_path / "signals.db")

    _, baseline_pending = await scanner.scan()
    await scanner.commit_state(baseline_pending)
    (vault / "inbox" / "note.md").write_text("# Note\n", encoding="utf-8")

    first_result, first_pending = await scanner.scan()
    second_result, second_pending = await scanner.scan()

    assert first_result.has_changes
    assert second_result.has_changes
    assert first_result.summary == second_result.summary
    assert first_pending == second_pending
