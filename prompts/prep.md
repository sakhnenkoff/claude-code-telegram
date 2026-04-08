<mode>PREP</mode>
<instructions>
Triggered by an upcoming work meeting. You receive a `<meeting-context>` block.

1. **Check meeting details** via Google Workspace MCP:
   - Is the meeting declined? If yes, respond with exactly `SILENT`
   - Are there >20 attendees (all-hands)? If yes, respond with exactly `SILENT`

2. **Gather context for this meeting:**
   - Slack: recent threads with/about the attendees (slack MCP)
   - GitHub: shared PRs, review requests with attendees (github-work MCP)
   - Vault: check people/ for matching person notes
   - If `<signal-data>` contains local changes, mention them briefly

3. **Respond as a meeting briefing:**
   - Meeting title + time remaining
   - Key context from Slack/GitHub/people notes
   - Suggested talking points (2-3 max)
   - Under 150 words
   - If nothing is actually actionable after checking: respond with exactly `SILENT`

4. **Do NOT write to NOW.md.** Prep notifications are ephemeral.
</instructions>
