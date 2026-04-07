"""Signal scanner orchestration for contextual heartbeat detection."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Sequence

from . import ScanResult
from .detectors import GitDetector, InboxDetector, ProjectDetector, TaskDetector
from .state import StateStore

_DEFAULT_INBOX_DIRS = ("inbox", "Inbox")
_DEFAULT_TASK_DIRS = ("tasks", "Tasks")
_DEFAULT_PROJECT_DIRS = ("projects", "Projects")


class SignalScanner:
    """Run all signal detectors and commit state separately after publish."""

    def __init__(
        self,
        vault_path: Path,
        state_db_path: Path,
        extra_repos: list[Path] | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.state = StateStore(state_db_path)
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

        repos = self._dedupe_paths([vault_path, *(extra_repos or [])])
        self._detectors = [
            GitDetector(state=self.state, repos=repos),
            InboxDetector(
                state=self.state,
                inbox_dir=self._resolve_dir(_DEFAULT_INBOX_DIRS),
            ),
            TaskDetector(
                state=self.state,
                task_dir=self._resolve_dir(_DEFAULT_TASK_DIRS),
            ),
            ProjectDetector(
                state=self.state,
                projects_dir=self._resolve_dir(_DEFAULT_PROJECT_DIRS),
            ),
        ]

    async def scan(self) -> tuple[ScanResult, dict[str, str]]:
        """Return scan deltas and pending state without committing it."""
        await self._ensure_initialized()

        deltas = []
        pending: dict[str, str] = {}

        for detector in self._detectors:
            delta, detector_pending = await detector.detect()
            deltas.append(delta)
            pending.update(detector_pending)

        return ScanResult(deltas=deltas), pending

    async def commit_state(self, pending: dict[str, str]) -> None:
        """Persist pending detector state after downstream publish succeeds."""
        if not pending:
            return

        await self._ensure_initialized()
        await self.state.set_many(pending)

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        async with self._initialize_lock:
            if self._initialized:
                return
            await self.state.initialize()
            self._initialized = True

    def _resolve_dir(self, candidates: Sequence[str]) -> Path:
        for candidate in candidates:
            path = self.vault_path / candidate
            if path.exists():
                return path
        return self.vault_path / candidates[0]

    @staticmethod
    def _dedupe_paths(paths: Sequence[Path]) -> list[Path]:
        unique_paths: list[Path] = []
        seen: set[str] = set()

        for path in paths:
            normalized = path.expanduser().resolve(strict=False)
            key = str(normalized)
            if key in seen:
                continue
            seen.add(key)
            unique_paths.append(normalized)

        return unique_paths
