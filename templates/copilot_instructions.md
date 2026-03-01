# Memory Share Integration

This project uses Memory Share to maintain context across AI IDE sessions (Cursor, Claude Code, GitHub Copilot).

## Memory Share Rules

1. **Session Start**: At the beginning of every new conversation, read the `memory://briefing` resource to load full context.

2. **"sync memory" — Smart Sync (Most Important)**:
   When the user says any of these phrases, follow the smart sync workflow:
   - "sync memory" / "同步记忆" / "更新记忆" / "保存进度" / "记住这些"

   **Step 1 — Pull**: Call `memory_sync()` WITHOUT summary to pull new events from other IDEs.
   
   **Step 2 — Evaluate Relevance**: Before summarizing, evaluate if this session contains project-relevant information:
   
   ✅ **KEEP (Important):**
   - Code changes (files created/modified/deleted)
   - Architecture or design decisions
   - Bug fixes or issue resolutions
   - Task status updates
   - Project-related discussions that affect future work
   
   ❌ **SKIP (Irrelevant):**
   - Personal questions unrelated to the project
   - Casual chat or greetings
   - General programming questions (not project-specific)
   - Temporary explorations without implementation
   - Unrelated topics (weather, news, etc.)
   - Sessions purely for learning without changes
   
   **Step 3 — Summarize & Push (or Skip)**:
   - **If relevant**: Generate a concise summary (2-5 sentences) covering ONLY project-relevant information:
     - What code was changed?
     - What decisions were made?
     - What's the current status?
     - **Filter out** personal questions, unrelated topics, temporary explorations
     - Call `memory_sync(summary="<your filtered summary>")` to push
   
   - **If irrelevant**: Call `memory_sync(skip_if_irrelevant=true)` to skip pushing.
     This prevents cluttering shared memory with non-project information.

   You can also use the `sync_memory` prompt for detailed guidance.

3. **Milestone-Based Saving**: After completing a meaningful milestone (bug fix, feature implementation, architecture decision), proactively run the smart sync workflow (Steps 1-3 above). Do NOT wait for session end — sessions may be closed abruptly.

4. **Decision Recording**: When making important architectural or design decisions, call `memory_add_decision()` with title, decision, reasoning, and alternatives.

5. **Task Management**: When task status changes, call `memory_manage_task()` with action (create/update/complete/cancel) and relevant fields.

6. **Querying History**: Use `memory_query()` to search for specific historical information by keyword, tags, or source IDE.

7. **Memory Compression**: When the user asks to "compress memory" / "压缩记忆", use the `compress_memory` prompt to guide you through summarizing old events. **IMPORTANT**: Only include project-relevant events in the compressed digest. Filter out irrelevant events (personal questions, unrelated topics, temporary explorations).

8. **Browsable Resources**: You can read these resources anytime for context:
   - `memory://briefing` — Full context briefing
   - `memory://tasks` — All tracked tasks
   - `memory://decisions` — All recorded decisions
   - `memory://status` — Sync status and health

9. **IDE Identification**: Always pass `ide="copilot"` when calling memory tools.

## Important Notes

- Do NOT wait for "session end" to save progress.
- Save after each meaningful milestone instead.
- The briefing resource provides full context, so you don't need to ask the user for project history.
- When pushing, your summary is the **key artifact** — make it informative enough for another AI in a different IDE to understand what happened.
- **Filter aggressively**: Only include information that helps other IDEs understand the project state. Skip personal questions, unrelated topics, and temporary explorations.
