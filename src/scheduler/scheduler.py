"""Job scheduler for recurring agent tasks.

Wraps APScheduler's AsyncIOScheduler and publishes ScheduledEvents
to the event bus when jobs fire.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from apscheduler.schedulers.asyncio import (
    AsyncIOScheduler,  # type: ignore[import-untyped]
)
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]

from ..events.bus import EventBus
from ..events.types import ScheduledEvent
from ..signals.detectors import CalendarDetector, Meeting
from ..storage.database import DatabaseManager

logger = structlog.get_logger()

# Maps job names to prompt template modes
_JOB_MODE_MAP: Dict[str, str] = {
    "Heartbeat Morning": "morning",
    "Heartbeat Midday": "midday",
    "Heartbeat Evening": "evening",
    "Heartbeat Weekly": "weekly",
}


@dataclass
class Trigger:
    """Result of the trigger gate evaluation."""
    mode: str  # "change", "prep", "catchup"
    context: Any = None  # Meeting for prep, None for others


def _minutes_since(iso_timestamp: str) -> float:
    """Minutes elapsed since an ISO 8601 timestamp."""
    then = datetime.fromisoformat(iso_timestamp)
    now = datetime.now(tz=then.tzinfo)
    return (now - then).total_seconds() / 60


class JobScheduler:
    """Cron scheduler that publishes ScheduledEvents to the event bus."""

    def __init__(
        self,
        event_bus: EventBus,
        db_manager: DatabaseManager,
        default_working_directory: Path,
    ) -> None:
        self.event_bus = event_bus
        self.db_manager = db_manager
        self.default_working_directory = default_working_directory
        self._scan_lock = asyncio.Lock()
        self._scheduler = AsyncIOScheduler(
            job_defaults={
                "misfire_grace_time": None,  # Always run, no matter how late
                "coalesce": True,            # Merge multiple missed runs into one
            }
        )

    async def start(self) -> None:
        """Load persisted jobs and start the scheduler."""
        await self._load_jobs_from_db()
        self._scheduler.start()
        logger.info("Job scheduler started")
        await self._check_missed_anchors()

    async def stop(self) -> None:
        """Shutdown the scheduler gracefully."""
        self._scheduler.shutdown(wait=False)
        logger.info("Job scheduler stopped")

    # ------------------------------------------------------------------
    # Prompt template composition
    # ------------------------------------------------------------------

    def _compose_prompt(self, mode: str, base_prompt: str) -> str:
        """Compose a prompt from template files, falling back to base_prompt.

        Looks for ``prompts/shared.md`` and ``prompts/{mode}.md`` relative to
        the package install path.  If both exist, returns their concatenation.
        Otherwise returns *base_prompt* unchanged (backward-compatible).
        """
        # Primary: relative to the package root (…/site-packages/prompts/)
        pkg_prompts = Path(__file__).parent.parent.parent / "prompts"

        # Fallback: working directory parent (for dev / editable installs)
        cwd_prompts = Path.cwd() / "prompts"

        prompts_dir: Optional[Path] = None
        if (pkg_prompts / "shared.md").is_file():
            prompts_dir = pkg_prompts
        elif (cwd_prompts / "shared.md").is_file():
            prompts_dir = cwd_prompts

        if prompts_dir is None:
            logger.debug(
                "No prompt templates found, using DB prompt",
                pkg_path=str(pkg_prompts),
                cwd_path=str(cwd_prompts),
            )
            return base_prompt

        shared_path = prompts_dir / "shared.md"
        mode_path = prompts_dir / f"{mode}.md"

        if not mode_path.is_file():
            logger.warning(
                "Mode template not found, using DB prompt",
                mode=mode,
                expected_path=str(mode_path),
            )
            return base_prompt

        shared_content = shared_path.read_text(encoding="utf-8")
        mode_content = mode_path.read_text(encoding="utf-8")

        logger.info(
            "Composed prompt from templates",
            mode=mode,
            prompts_dir=str(prompts_dir),
            shared_chars=len(shared_content),
            mode_chars=len(mode_content),
        )
        return f"{shared_content}\n\n{mode_content}"

    # ------------------------------------------------------------------

    async def add_job(
        self,
        job_name: str,
        cron_expression: str,
        prompt: str,
        target_chat_ids: Optional[List[int]] = None,
        working_directory: Optional[Path] = None,
        skill_name: Optional[str] = None,
        created_by: int = 0,
    ) -> str:
        """Add a new scheduled job.

        Args:
            job_name: Human-readable job name.
            cron_expression: Cron-style schedule (e.g. "0 9 * * 1-5").
            prompt: The prompt to send to Claude when the job fires.
            target_chat_ids: Telegram chat IDs to send the response to.
            working_directory: Working directory for Claude execution.
            skill_name: Optional skill to invoke.
            created_by: Telegram user ID of the creator.

        Returns:
            The job ID.
        """
        trigger = CronTrigger.from_crontab(cron_expression)
        work_dir = working_directory or self.default_working_directory

        job = self._scheduler.add_job(
            self._fire_event,
            trigger=trigger,
            kwargs={
                "job_name": job_name,
                "prompt": prompt,
                "working_directory": str(work_dir),
                "target_chat_ids": target_chat_ids or [],
                "skill_name": skill_name,
            },
            name=job_name,
        )

        # Persist to database
        await self._save_job(
            job_id=job.id,
            job_name=job_name,
            cron_expression=cron_expression,
            prompt=prompt,
            target_chat_ids=target_chat_ids or [],
            working_directory=str(work_dir),
            skill_name=skill_name,
            created_by=created_by,
        )

        logger.info(
            "Scheduled job added",
            job_id=job.id,
            job_name=job_name,
            cron=cron_expression,
        )
        return str(job.id)

    async def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job."""
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            logger.warning("Job not found in scheduler", job_id=job_id)

        await self._delete_job(job_id)
        logger.info("Scheduled job removed", job_id=job_id)
        return True

    async def list_jobs(self) -> List[Dict[str, Any]]:
        """List all scheduled jobs from the database."""
        async with self.db_manager.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM scheduled_jobs WHERE is_active = 1 ORDER BY created_at"
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def _fire_event(
        self,
        job_name: str,
        prompt: str,
        working_directory: str,
        target_chat_ids: List[int],
        skill_name: Optional[str],
        config_overrides: Optional[Dict[str, Any]] = None,
        job_type: str = "anchor",
    ) -> None:
        """Called by APScheduler when a job triggers. Publishes a ScheduledEvent."""
        if job_type == "scan":
            async with self._scan_lock:
                from ..signals.scanner import SignalScanner

                state_db = Path(working_directory) / ".signal_state.db"
                scanner = SignalScanner(
                    vault_path=Path(working_directory),
                    state_db_path=state_db,
                )
                result, pending_state = await scanner.scan()

                # Run calendar check
                cal_detector = CalendarDetector()
                upcoming_meetings = await cal_detector.detect()

                # Evaluate trigger gate
                trigger = await self._evaluate_trigger_gate(
                    has_local_changes=result.has_changes,
                    upcoming_meetings=upcoming_meetings,
                    state=scanner.state,
                )

                if trigger is None:
                    logger.debug("No triggers, skipping Claude invocation")
                    # Still commit detector state so deltas don't re-detect
                    if result.has_changes:
                        await scanner.commit_state(pending_state)
                    return

                # Compose trigger-specific prompt
                composed = self._compose_prompt(trigger.mode, prompt)

                # Template fallback guard: if _compose_prompt fell back to DB prompt
                # for non-change modes, skip — the DB prompt is wrong (old nudge).
                if trigger.mode != "change" and composed == prompt:
                    logger.error(
                        "Template not found for mode, skipping invocation",
                        mode=trigger.mode,
                    )
                    if result.has_changes:
                        await scanner.commit_state(pending_state)
                    return

                # Inject signal-data + trigger context
                if trigger.mode == "prep" and result.has_changes:
                    signal_summary = f"Meeting prep mode. Also since last check:\n{result.summary}"
                elif result.has_changes:
                    signal_summary = result.summary
                else:
                    signal_summary = "No local changes."
                composed = f"<signal-data>\n{signal_summary}\n</signal-data>\n\n{composed}"

                if trigger.mode == "prep" and trigger.context:
                    composed += (
                        f"\n\n<meeting-context>\n"
                        f"Title: {trigger.context.title}\n"
                        f"Starts: {trigger.context.start_time}\n"
                        f"Calendar: {trigger.context.calendar}\n"
                        f"</meeting-context>"
                    )

                event = ScheduledEvent(
                    job_name=job_name,
                    prompt=composed,
                    working_directory=Path(working_directory),
                    target_chat_ids=target_chat_ids,
                    skill_name=skill_name,
                    config_overrides=config_overrides or {},
                    job_type=job_type,
                    trigger_mode=trigger.mode,
                )

                logger.info(
                    "Scan job fired",
                    job_name=job_name,
                    trigger_mode=trigger.mode,
                    has_local_changes=result.has_changes,
                    event_id=event.id,
                )

                await self.event_bus.publish(event)

                # Commit detector state (two-phase: after successful publish)
                if result.has_changes:
                    await scanner.commit_state(pending_state)
                return

        # Anchor type: compose prompt from templates if mode is known
        mode = _JOB_MODE_MAP.get(job_name)
        if mode:
            prompt = self._compose_prompt(mode, prompt)
        else:
            logger.debug(
                "No template mode mapping for job, using DB prompt",
                job_name=job_name,
            )

        event = ScheduledEvent(
            job_name=job_name,
            prompt=prompt,
            working_directory=Path(working_directory),
            target_chat_ids=target_chat_ids,
            skill_name=skill_name,
            config_overrides=config_overrides or {},
            job_type=job_type,
        )

        logger.info(
            "Scheduled job fired",
            job_name=job_name,
            event_id=event.id,
        )

        await self.event_bus.publish(event)

        # Track last_fired_at for idempotent catch-up.
        try:
            tz = CronTrigger.from_crontab("0 0 * * *").timezone
            async with self.db_manager.get_connection() as conn:
                await conn.execute(
                    "UPDATE scheduled_jobs SET last_fired_at = ? WHERE job_name = ? AND is_active = 1",
                    (datetime.now(tz=tz).isoformat(), job_name),
                )
                await conn.commit()
        except Exception:
            logger.debug("Could not update last_fired_at", job_name=job_name)

    async def _load_jobs_from_db(self) -> None:
        """Load persisted jobs and re-register them with APScheduler."""
        try:
            async with self.db_manager.get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT * FROM scheduled_jobs WHERE is_active = 1"
                )
                rows = list(await cursor.fetchall())

            for row in rows:
                row_dict = dict(row)
                try:
                    trigger = CronTrigger.from_crontab(row_dict["cron_expression"])

                    # Parse target_chat_ids from stored string
                    chat_ids_str = row_dict.get("target_chat_ids", "")
                    chat_ids = (
                        [int(x) for x in chat_ids_str.split(",") if x.strip()]
                        if chat_ids_str
                        else []
                    )

                    # Parse per-job config overrides
                    config_overrides_raw = row_dict.get("config_overrides", "{}")
                    try:
                        config_overrides = (
                            json.loads(config_overrides_raw)
                            if config_overrides_raw
                            else {}
                        )
                        if not isinstance(config_overrides, dict):
                            config_overrides = {}
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            "Invalid config_overrides JSON, using defaults",
                            job_id=row_dict.get("job_id"),
                        )
                        config_overrides = {}

                    self._scheduler.add_job(
                        self._fire_event,
                        trigger=trigger,
                        kwargs={
                            "job_name": row_dict["job_name"],
                            "prompt": row_dict["prompt"],
                            "working_directory": row_dict["working_directory"],
                            "target_chat_ids": chat_ids,
                            "skill_name": row_dict.get("skill_name"),
                            "config_overrides": config_overrides,
                            "job_type": row_dict.get("job_type", "anchor"),
                        },
                        id=row_dict["job_id"],
                        name=row_dict["job_name"],
                        replace_existing=True,
                    )
                    logger.debug(
                        "Loaded scheduled job from DB",
                        job_id=row_dict["job_id"],
                        job_name=row_dict["job_name"],
                    )
                except Exception:
                    logger.exception(
                        "Failed to load scheduled job",
                        job_id=row_dict.get("job_id"),
                    )

            logger.info("Loaded scheduled jobs from database", count=len(rows))
        except Exception:
            # Table might not exist yet on first run
            logger.debug("No scheduled_jobs table found, starting fresh")

    async def _check_missed_anchors(self) -> None:
        """Fire anchor jobs that should have already run today."""
        trigger_sample = CronTrigger.from_crontab("0 0 * * *")
        local_tz = trigger_sample.timezone
        now = datetime.now(tz=local_tz)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        try:
            async with self.db_manager.get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT * FROM scheduled_jobs WHERE is_active = 1 AND job_type = 'anchor'"
                )
                rows = list(await cursor.fetchall())

            for row in rows:
                row_dict = dict(row)
                try:
                    trigger = CronTrigger.from_crontab(row_dict["cron_expression"])
                    next_from_midnight = trigger.get_next_fire_time(None, midnight)

                    if not (next_from_midnight and midnight <= next_from_midnight <= now):
                        continue

                    last_fired = row_dict.get("last_fired_at")
                    if last_fired:
                        last_fired_dt = datetime.fromisoformat(str(last_fired))
                        if last_fired_dt.date() >= now.date():
                            logger.debug(
                                "Anchor already fired today, skipping catch-up",
                                job_name=row_dict["job_name"],
                            )
                            continue

                    logger.info(
                        "Detected missed anchor job, firing catch-up",
                        job_name=row_dict["job_name"],
                        scheduled_time=str(next_from_midnight),
                        current_time=str(now),
                    )

                    chat_ids_str = row_dict.get("target_chat_ids", "")
                    chat_ids = (
                        [int(x) for x in chat_ids_str.split(",") if x.strip()]
                        if chat_ids_str
                        else []
                    )

                    try:
                        config_overrides = json.loads(
                            row_dict.get("config_overrides", "{}") or "{}"
                        )
                        if not isinstance(config_overrides, dict):
                            config_overrides = {}
                    except (json.JSONDecodeError, TypeError):
                        config_overrides = {}

                    await self._fire_event(
                        job_name=row_dict["job_name"],
                        prompt=row_dict["prompt"],
                        working_directory=row_dict["working_directory"],
                        target_chat_ids=chat_ids,
                        skill_name=row_dict.get("skill_name"),
                        config_overrides=config_overrides,
                        job_type=row_dict.get("job_type", "anchor"),
                    )

                    async with self.db_manager.get_connection() as conn:
                        await conn.execute(
                            "UPDATE scheduled_jobs SET last_fired_at = ? WHERE job_id = ?",
                            (now.isoformat(), row_dict["job_id"]),
                        )
                        await conn.commit()
                except Exception:
                    logger.exception(
                        "Failed to check missed anchor",
                        job_id=row_dict.get("job_id"),
                    )
        except Exception:
            logger.debug("Could not check missed anchors")

    async def _evaluate_trigger_gate(
        self,
        has_local_changes: bool,
        upcoming_meetings: List[Meeting],
        state: "StateStore",
    ) -> Optional[Trigger]:
        """Evaluate trigger priority: PREP > CHANGE > CATCHUP."""
        now = datetime.now()

        # Daily cleanup: clear stale prepped_meetings from previous days
        prepped_raw = await state.get("gate:prepped_meetings", "[]")
        if prepped_raw is None:
            prepped_raw = "[]"
        try:
            prepped = json.loads(prepped_raw)
        except json.JSONDecodeError:
            prepped = []
        today = now.date()
        clean_prepped = []
        for key in prepped:
            parts = key.rsplit("::", 1)
            if len(parts) == 2:
                try:
                    meeting_date = datetime.fromisoformat(parts[1]).date()
                    if meeting_date >= today:
                        clean_prepped.append(key)
                except ValueError:
                    pass  # drop malformed keys
        if clean_prepped != prepped:
            await state.set("gate:prepped_meetings", json.dumps(clean_prepped))
        prepped = clean_prepped

        # Priority 1: Pre-meeting prep (bypasses cooldown)
        if upcoming_meetings:
            for meeting in upcoming_meetings:
                meeting_key = f"{meeting.title}::{meeting.start_time.isoformat()}"
                if meeting_key not in prepped:
                    prepped.append(meeting_key)
                    await state.set("gate:prepped_meetings", json.dumps(prepped))
                    return Trigger(mode="prep", context=meeting)

        # Priority 2: Local changes (respects cooldown)
        if has_local_changes:
            last_nudge = await state.get("gate:last_nudge_sent")
            if last_nudge is None or _minutes_since(last_nudge) >= 30:
                return Trigger(mode="change", context=None)
            else:
                logger.debug("Change detected but in cooldown")

        # Priority 3: Safety net (2h since last MCP check)
        last_mcp = await state.get("gate:last_mcp_check")
        if last_mcp is None or _minutes_since(last_mcp) >= 120:
            return Trigger(mode="catchup", context=None)

        return None  # No triggers

    async def _save_job(
        self,
        job_id: str,
        job_name: str,
        cron_expression: str,
        prompt: str,
        target_chat_ids: List[int],
        working_directory: str,
        skill_name: Optional[str],
        created_by: int,
    ) -> None:
        """Persist a job definition to the database."""
        chat_ids_str = ",".join(str(cid) for cid in target_chat_ids)
        async with self.db_manager.get_connection() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO scheduled_jobs
                (job_id, job_name, cron_expression, prompt, target_chat_ids,
                 working_directory, skill_name, created_by, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    job_id,
                    job_name,
                    cron_expression,
                    prompt,
                    chat_ids_str,
                    working_directory,
                    skill_name,
                    created_by,
                ),
            )
            await conn.commit()

    async def _delete_job(self, job_id: str) -> None:
        """Soft-delete a job from the database."""
        async with self.db_manager.get_connection() as conn:
            await conn.execute(
                "UPDATE scheduled_jobs SET is_active = 0 WHERE job_id = ?",
                (job_id,),
            )
            await conn.commit()
