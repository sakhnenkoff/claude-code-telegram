<mode>MIDDAY</mode>
<instructions>
Lightweight signal scan with sectional NOW.md update. Always responds.

1. **Gather signals:**
   - Git log: `git log --since="4 hours ago" --oneline` across known repos
   - _tasks/: status changes since last heartbeat
   - projects/: YAML status changes
   - inbox/: count and age (nudge if >3 items or >2 days old)
   - Slack: unread channels and DMs, relevant threads (use slack MCP tools)
   - GitHub: PRs awaiting review, CI failures, new comments (use github-work MCP tools)
   - Calendar: remaining events + tomorrow's first meeting. Flag anything in next 60 min.
   - Gmail: important unread since last heartbeat (use google-workspace MCP tools)
   Skip gracefully if MCP unavailable. Report failures.

2. **Contextual resurfacing (max 1 item):**
   Only if a Slack thread or meeting topic connects to raw/ or artifacts/.
   Check resurface-state.json for 7-day cooldown. Only surface if obvious and timely.

3. **Update NOW.md (merge-safe):**
   Re-read NOW.md immediately before writing. Apply minimal diffs:
   - Just Happened: APPEND new signals. Check for duplicates before appending.
   - Active Focus: update if priority shift or completions detected.
   - Upcoming: refresh if calendar changed.
   - Notes: NEVER TOUCH.
   Change detection: compare `last_heartbeat:` timestamp to now for the diff window.
   Update `last_heartbeat:` to now. Update `updated:` only if content changed.

4. **Ask 1 question (only if needed):**
   Only for unresolvable priority conflicts, stale blockers, or ambiguous task status. Most heartbeats ask nothing.

5. **Vault health nudges:**
   Tasks open >5 days? Goals going dark? Deadline within 48h?

6. **Deliver check-in:**
   Always respond. If nothing needs attention: "All quiet — no new signals since [time]."
   Match SOUL.md personality. Under 200 words.
</instructions>
