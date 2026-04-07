<mode>MORNING</mode>
<instructions>
Full daily briefing. Rewrites NOW.md.

1. **Gather signals:**
   - Calendar: run `~/.local/bin/cal-today-bin` for today's events + tomorrow's first meeting
   - Slack: unread channels and DMs, especially @mentions (use slack MCP tools)
   - GitHub: PRs awaiting review and CI failures (use github-work MCP tools)
   - Gmail: important unread emails (use google-workspace MCP tools)
   - Vault: _tasks/ (open/in-progress), _plans/ (yesterday's plan), logs/ (last 3 daily notes)
   - Inbox: count items in inbox/, note age of oldest
   Skip gracefully if any MCP tool unavailable. Report which source failed.

2. **Inbox triage (lightweight):**
   Surface inbox/ items relevant to today's priorities. Do NOT file or modify items.

3. **Curator's Picks (resurfacing):**
   Read `~/.config/mcp/resurface-state.json` for cooldowns.
   Scan raw/ (NOT raw/processed/) and content/seeds/.
   Max 3 items: Anchor (useful today), Angle (adjacent), Echo (old but ripened).
   Update resurface-state.json. Do NOT modify raw/ or content/seeds/.
   Zero is valid if nothing resonates.

4. **Generate daily plan:**
   Write `_plans/YYYY-MM-DD-plan.md`: Calendar, Curator's Picks, Priority Tasks (top 3-5), Focus Blocks (calendar gaps, 10:00-18:00 CET), Carry-Forward.

5. **Rewrite NOW.md (section-aware):**
   - Active Focus: open tasks + active projects + today's priorities. Top 3.
   - Just Happened: git log, completed tasks, session activity since last rewrite.
   - Upcoming: calendar + tasks due within 72h.
   - Notes: NEVER TOUCH.
   Update YAML: `updated:` and `last_heartbeat:` to now.

6. **Deliver briefing** to Telegram:
   Top 3 priorities, calendar, Slack highlights, GitHub/email if urgent, Curator's Picks, inbox nudge, one strategic nudge. Under 400 words, scannable.
</instructions>
