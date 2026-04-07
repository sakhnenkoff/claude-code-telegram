"""Signal scanning for contextual heartbeat system.

Pre-filters local changes (git, tasks, inbox, projects) before invoking Claude.
Only fires a ScheduledEvent when something actually changed.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class SignalDelta:
    """Result from a single signal detector."""
    changed: bool
    summary: str


@dataclass
class ScanResult:
    """Aggregated result from all detectors."""
    deltas: List[SignalDelta] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return any(d.changed for d in self.deltas)

    @property
    def summary(self) -> str:
        changed = [d for d in self.deltas if d.changed and d.summary]
        if not changed:
            return ""
        return "\n".join(f"- {d.summary}" for d in changed)
