"""Signal detectors for contextual heartbeat scanning.

Detectors are intentionally two-phase: they compare current observations
against persisted state and return pending state updates for the scanner
to commit only after a downstream publish succeeds.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Awaitable, Callable, Protocol, Sequence

from . import SignalDelta

PendingStateUpdates = dict[str, str]

_OPEN_TASK_PATTERN = re.compile(r"(?m)^\s*[-*]\s+\[ \]\s+")
_FRONTMATTER_PATTERN = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---(?:[ \t]*\r?\n|\Z)",
    re.DOTALL,
)
_STATUS_PATTERN = re.compile(r"(?im)^status\s*:\s*(.+?)\s*$")


class StateReader(Protocol):
    async def get(self, key: str, default: str | None = None) -> str | None:
        """Return the persisted value for a key."""


GitStatusProvider = Callable[[], Awaitable[dict[str, str]]]


class GitDetector:
    """Detect changes in git HEAD/dirty state across repositories."""

    def __init__(
        self,
        state: StateReader,
        repos: Sequence[Path],
        status_provider: GitStatusProvider | None = None,
    ) -> None:
        self.state = state
        self.repos = list(repos)
        self.status_provider = status_provider

    async def detect(self) -> tuple[SignalDelta, PendingStateUpdates]:
        current = (
            await self.status_provider()
            if self.status_provider is not None
            else await asyncio.to_thread(self._collect_statuses)
        )
        pending: PendingStateUpdates = {}
        changed_repos: list[str] = []

        for repo_name in sorted(current):
            key = f"git:{repo_name}"
            pending[key] = current[repo_name]
            previous = await self.state.get(key)
            if previous is None:
                continue
            if previous != current[repo_name]:
                changed_repos.append(repo_name)

        summary = ""
        if changed_repos:
            if len(changed_repos) == 1:
                summary = f"Git: {changed_repos[0]} updated"
            else:
                joined = ", ".join(changed_repos)
                summary = f"Git: {len(changed_repos)} repos updated ({joined})"

        return SignalDelta(changed=bool(changed_repos), summary=summary), pending

    def _collect_statuses(self) -> dict[str, str]:
        return {
            repo.name: self._repo_fingerprint(repo)
            for repo in sorted(self.repos, key=lambda item: item.name)
        }

    def _repo_fingerprint(self, repo: Path) -> str:
        git_dir = repo / ".git"
        if not repo.exists() or not repo.is_dir() or not git_dir.exists():
            return "missing"

        head = self._git_output(repo, "rev-parse", "HEAD")
        if head is None:
            return "missing"

        status = self._git_output(
            repo,
            "status",
            "--short",
            "--untracked-files=normal",
        )
        dirty = "dirty" if status else "clean"
        return f"{head}:{dirty}"

    @staticmethod
    def _git_output(repo: Path, *args: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()


class InboxDetector:
    """Detect count changes in an inbox directory."""

    def __init__(
        self,
        state: StateReader,
        inbox_dir: Path,
        pattern: str = "*.md",
    ) -> None:
        self.state = state
        self.inbox_dir = inbox_dir
        self.pattern = pattern

    async def detect(self) -> tuple[SignalDelta, PendingStateUpdates]:
        current_count = await asyncio.to_thread(self._count_items)
        current_value = str(current_count)
        pending = {"inbox:count": current_value}
        previous = await self.state.get("inbox:count")

        if previous is None or previous == current_value:
            return SignalDelta(changed=False, summary=""), pending

        summary = f"Inbox: {previous} -> {current_value} items"
        return SignalDelta(changed=True, summary=summary), pending

    def _count_items(self) -> int:
        if not self.inbox_dir.exists():
            return 0
        return sum(1 for path in self.inbox_dir.glob(self.pattern) if path.is_file())


class TaskDetector:
    """Detect changes in the total number of open markdown tasks."""

    def __init__(
        self,
        state: StateReader,
        task_dir: Path,
        pattern: str = "*.md",
    ) -> None:
        self.state = state
        self.task_dir = task_dir
        self.pattern = pattern

    async def detect(self) -> tuple[SignalDelta, PendingStateUpdates]:
        current_count = await asyncio.to_thread(self._count_open_tasks)
        current_value = str(current_count)
        pending = {"tasks:open": current_value}
        previous = await self.state.get("tasks:open")

        if previous is None or previous == current_value:
            return SignalDelta(changed=False, summary=""), pending

        summary = f"Tasks: {previous} -> {current_value} open"
        return SignalDelta(changed=True, summary=summary), pending

    def _count_open_tasks(self) -> int:
        if not self.task_dir.exists():
            return 0

        total = 0
        for path in self.task_dir.glob(self.pattern):
            if not path.is_file():
                continue
            total += len(_OPEN_TASK_PATTERN.findall(path.read_text(encoding="utf-8")))
        return total


class ProjectDetector:
    """Detect changes in project statuses declared in markdown frontmatter."""

    def __init__(
        self,
        state: StateReader,
        projects_dir: Path,
        pattern: str = "*.md",
    ) -> None:
        self.state = state
        self.projects_dir = projects_dir
        self.pattern = pattern

    async def detect(self) -> tuple[SignalDelta, PendingStateUpdates]:
        current = await asyncio.to_thread(self._collect_statuses)
        serialized = json.dumps(current, sort_keys=True, separators=(",", ":"))
        pending = {"projects:statuses": serialized}
        previous_raw = await self.state.get("projects:statuses")

        if previous_raw is None:
            return SignalDelta(changed=False, summary=""), pending

        previous = self._deserialize_statuses(previous_raw)
        if previous == current:
            return SignalDelta(changed=False, summary=""), pending

        changes = self._summarize_changes(previous, current)
        summary = f"Projects: {'; '.join(changes)}" if changes else ""
        return SignalDelta(changed=bool(changes), summary=summary), pending

    def _collect_statuses(self) -> dict[str, str]:
        if not self.projects_dir.exists():
            return {}

        statuses: dict[str, str] = {}
        for path in self.projects_dir.glob(self.pattern):
            if not path.is_file():
                continue
            status = self._extract_status(path.read_text(encoding="utf-8"))
            if status is not None:
                statuses[path.stem] = status
        return statuses

    @staticmethod
    def _deserialize_statuses(raw: str) -> dict[str, str]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in parsed.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    @staticmethod
    def _extract_status(text: str) -> str | None:
        # Only inspect YAML frontmatter between the opening markers.
        frontmatter_match = _FRONTMATTER_PATTERN.match(text)
        if frontmatter_match is None:
            return None

        status_match = _STATUS_PATTERN.search(frontmatter_match.group(1))
        if status_match is None:
            return None

        value = status_match.group(1).split("#", 1)[0].strip().strip("'\"")
        return value or None

    @staticmethod
    def _summarize_changes(
        previous: dict[str, str],
        current: dict[str, str],
    ) -> list[str]:
        changes: list[str] = []
        for name in sorted(set(previous) | set(current)):
            old = previous.get(name)
            new = current.get(name)
            if old == new:
                continue
            if old is None and new is not None:
                changes.append(f"{name} set to {new}")
            elif old is not None and new is None:
                changes.append(f"{name} cleared from {old}")
            elif old is not None and new is not None:
                changes.append(f"{name} {old} -> {new}")
        return changes


@dataclass
class Meeting:
    """A calendar meeting parsed from cal-today-bin output."""

    title: str
    start_time: datetime
    end_time: datetime
    calendar: str
    starts_in_minutes: float


_CAL_LINE_RE = re.compile(
    r"^-\s+(\d{2}:\d{2})\s+-\s+(\d{2}:\d{2})\s{2,}(.+?)\s{2,}\[(.+?)\]$"
)


class CalendarDetector:
    """Check for upcoming work meetings using cal-today-bin."""

    async def detect(self) -> list[Meeting]:
        """Return work meetings starting in the next 15 minutes."""
        output = await asyncio.to_thread(self._run_cal_today)
        meetings = self._parse_meetings(output)
        return [
            m
            for m in meetings
            if 0 < m.starts_in_minutes <= 15
            and m.calendar.endswith("@vend.com")
        ]

    def _run_cal_today(self) -> str:
        result = subprocess.run(
            [str(Path.home() / ".local/bin/cal-today-bin")],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout if result.returncode == 0 else ""

    def _parse_meetings(self, output: str) -> list[Meeting]:
        meetings: list[Meeting] = []
        now = datetime.now()
        today = now.date()
        for line in output.strip().splitlines():
            match = _CAL_LINE_RE.match(line.strip())
            if not match:
                continue
            start_h, start_m = map(int, match.group(1).split(":"))
            end_h, end_m = map(int, match.group(2).split(":"))
            start_dt = datetime.combine(today, time(start_h, start_m))
            end_dt = datetime.combine(today, time(end_h, end_m))
            delta = (start_dt - now).total_seconds() / 60
            meetings.append(
                Meeting(
                    title=match.group(3).strip(),
                    start_time=start_dt,
                    end_time=end_dt,
                    calendar=match.group(4).strip(),
                    starts_in_minutes=delta,
                )
            )
        return meetings


__all__ = [
    "CalendarDetector",
    "GitDetector",
    "InboxDetector",
    "Meeting",
    "ProjectDetector",
    "TaskDetector",
]
