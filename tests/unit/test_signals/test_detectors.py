from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.signals.state import StateStore


class FakeState:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._values = dict(initial or {})
        self.set = AsyncMock()
        self.set_many = AsyncMock()

    async def get(self, key: str, default: str | None = None) -> str | None:
        return self._values.get(key, default)


@pytest.mark.asyncio
async def test_git_detector_baselines_without_writing_state(
    tmp_path: Path,
) -> None:
    from src.signals.detectors import GitDetector

    repo = tmp_path / "app"
    repo.mkdir()

    store = StateStore(tmp_path / "state.db")
    await store.initialize()

    detector = GitDetector(state=store, repos=[repo])

    delta, pending = await detector.detect()

    assert not delta.changed
    assert delta.summary == ""
    assert pending == {"git:app": "missing"}
    assert await store.get("git:app") is None


@pytest.mark.asyncio
async def test_git_detector_reports_repo_state_change_without_committing() -> None:
    from src.signals.detectors import GitDetector

    state = FakeState({"git:app": "abc123:clean"})
    detector = GitDetector(
        state=state,
        repos=[],
        status_provider=AsyncMock(
            return_value={"app": "def456:dirty"},
        ),
    )

    delta, pending = await detector.detect()

    assert delta.changed
    assert "app" in delta.summary
    assert "updated" in delta.summary.lower()
    assert pending == {"git:app": "def456:dirty"}
    state.set.assert_not_awaited()
    state.set_many.assert_not_awaited()


@pytest.mark.asyncio
async def test_inbox_detector_reports_count_change_without_committing(
    tmp_path: Path,
) -> None:
    from src.signals.detectors import InboxDetector

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.md").write_text("# A\n", encoding="utf-8")
    (inbox / "b.md").write_text("# B\n", encoding="utf-8")
    (inbox / "ignore.txt").write_text("skip\n", encoding="utf-8")

    state = FakeState({"inbox:count": "1"})
    detector = InboxDetector(state=state, inbox_dir=inbox)

    delta, pending = await detector.detect()

    assert delta.changed
    assert "Inbox" in delta.summary
    assert "1" in delta.summary
    assert "2" in delta.summary
    assert pending == {"inbox:count": "2"}
    state.set.assert_not_awaited()
    state.set_many.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_detector_counts_open_markdown_checkboxes_only(
    tmp_path: Path,
) -> None:
    from src.signals.detectors import TaskDetector

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "today.md").write_text(
        "- [ ] ship detector\n"
        "- [x] merged already\n"
        "* [ ] write tests\n",
        encoding="utf-8",
    )
    (tasks_dir / "notes.txt").write_text("- [ ] should not count\n", encoding="utf-8")

    state = FakeState({"tasks:open": "1"})
    detector = TaskDetector(state=state, task_dir=tasks_dir)

    delta, pending = await detector.detect()

    assert delta.changed
    assert "Tasks" in delta.summary
    assert "1" in delta.summary
    assert "2" in delta.summary
    assert pending == {"tasks:open": "2"}
    state.set.assert_not_awaited()
    state.set_many.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_detector_scopes_status_to_frontmatter_only(
    tmp_path: Path,
) -> None:
    from src.signals.detectors import ProjectDetector

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "alpha.md").write_text(
        "---\n"
        "status: active\n"
        "owner: matvii\n"
        "---\n"
        "\n"
        "Body mentions status: archived but should be ignored.\n",
        encoding="utf-8",
    )

    state = FakeState({"projects:statuses": '{"alpha":"paused"}'})
    detector = ProjectDetector(state=state, projects_dir=projects_dir)

    delta, pending = await detector.detect()

    assert delta.changed
    assert "alpha" in delta.summary
    assert "paused" in delta.summary
    assert "active" in delta.summary
    assert pending == {"projects:statuses": '{"alpha":"active"}'}
    state.set.assert_not_awaited()
    state.set_many.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_detector_ignores_status_outside_frontmatter(
    tmp_path: Path,
) -> None:
    from src.signals.detectors import ProjectDetector

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "alpha.md").write_text(
        "---\n"
        "owner: matvii\n"
        "---\n"
        "\n"
        "status: active\n",
        encoding="utf-8",
    )

    state = FakeState()
    detector = ProjectDetector(state=state, projects_dir=projects_dir)

    delta, pending = await detector.detect()

    assert not delta.changed
    assert delta.summary == ""
    assert pending == {"projects:statuses": "{}"}
    state.set.assert_not_awaited()
    state.set_many.assert_not_awaited()
