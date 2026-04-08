<mode>CATCHUP</mode>
<instructions>
Safety-net scan — it's been 2+ hours since the last full check.
Read the room, connect dots, suggest actions.

1. **Full MCP scan:**
   - Slack: threads you're in, DMs, relevant channels — not just @mentions (slack MCP)
   - GitHub: PRs, CI, review requests, new comments (github-work MCP)
   - Calendar: rest of today's schedule (~/.local/bin/cal-today-bin)
   - Gmail: important unread emails (google-workspace MCP)
   Skip gracefully if any source is unavailable.

2. **Cross-reference:**
   - Slack activity ↔ people/ notes (who needs a response?)
   - Upcoming calendar ↔ Slack threads (context for later meetings)
   - NOW.md Active Focus ↔ recent activity (priorities going stale?)
   - Inbox + tasks age (piling up?)

3. **Respond with urgency-based tone:**
   - **Urgent** (waiting >24h, explicit ask): directive. "Reply to X — waiting since yesterday."
   - **Non-urgent** (aging, no deadline): suggestive. "LinkedIn post aging 3 days — worth 20 min?"
   - **Informational** (no action needed): context. "Thread in #channel is active — related to your PR."
   - Max 5 bullets
   - Under 200 words
   - If nothing is actually actionable after checking: respond with exactly `SILENT`

4. **Do NOT write to NOW.md.** Catchup nudges are ephemeral.
</instructions>
