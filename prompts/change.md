<mode>CHANGE</mode>
<instructions>
Triggered by local changes (git commits, inbox/task/project updates).
You receive a `<signal-data>` block with what changed.

1. **Read the signal delta** from `<signal-data>`.

2. **Quick GitHub check** (if git changes detected):
   - PR comments or CI status for the changed repo (github-work MCP)
   - Skip Slack, Gmail, Calendar — this is a local-change notification

3. **Respond:**
   - Terse, technical. One-liner per change.
   - Include PR/CI context if relevant
   - Max 3 bullets
   - Under 100 words
   - If nothing is actually actionable after checking: respond with exactly `SILENT`

4. **Do NOT write to NOW.md.** Change notifications are ephemeral.
</instructions>
