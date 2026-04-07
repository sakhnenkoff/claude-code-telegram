<mode>EVENING</mode>
<instructions>
Autonomous day wrap-up. Drafts updates but does NOT confirm task statuses.

1. **Gather signals:**
   Same as morning EXCEPT: skip Gmail, skip resurfacing.
   Additionally read: _plans/YYYY-MM-DD-plan.md (today's plan), logs/YYYY-MM-DD.md (today's daily note if exists).
   If no plan exists: skip comparison, note "No plan for today — working from signals only."

2. **Compare plan vs actual:**
   What was planned? What signals show happened (git, tasks, sessions)?
   Identify: completed, skipped, unplanned work.
   Note patterns: "You planned X but signals show Y instead."

3. **Draft carry-forward:**
   Unfinished plan items, "Tomorrow" items from daily note, tasks due within 48h.

4. **Rewrite NOW.md (merge-aware full rewrite):**
   Re-read NOW.md immediately before writing. Preserve bullets added by other sessions.
   - Active Focus: full rewrite from open tasks + active projects. Cross-reference coherence check.
   - Just Happened: rebuild from full day signals (git log --since="midnight"). Include external-session bullets.
   - Upcoming: rebuild for tomorrow (calendar + tasks due next 72h).
   - Notes: NEVER TOUCH.
   Update YAML: `updated:` and `last_heartbeat:` to now.

5. **Daily token cost summary (split by type):**
   Run these two commands:
   
   Bot automation (scheduled jobs):
   `grep -B5 '"cost"' ~/.claude-telegram-bot/logs/bot.log | grep -A5 'job_name' | grep "$(date +%Y-%m-%d)" | grep '"cost"' | awk -F'"cost": ' '{sum += $2; n++} END {printf "Bot: %.2f USD (%d jobs)", sum, n}'`
   
   Interactive sessions (your Telegram chats):
   `grep '"cost"' ~/.claude-telegram-bot/logs/bot.log | grep "$(date +%Y-%m-%d)" | awk -F'"cost": ' '{sum += $2; n++} END {printf "Total: %.2f USD (%d invocations)", sum, n}'`
   
   Report both: "Today's cost: $X.XX total ($Y.YY bot automation, rest was your sessions)"

6. **Deliver wrap-up** to Telegram:
   What got done, what was skipped, carry-forward, token cost.
   If tasks look done from signals: "These look done: [list]. Run /closeday to confirm."
   Do NOT change task statuses. Do NOT prompt reflection. That's /closeday's job.
   Under 300 words.
</instructions>
