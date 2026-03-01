"""MCP Server implementation using FastMCP framework.

Provides:
- Tools: memory_sync, memory_add_decision, memory_manage_task, memory_query
- Prompts: sync_memory (guides LLM through smart sync workflow)
- Resources: memory://briefing, memory://tasks, memory://decisions
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

from fastmcp import FastMCP
from pydantic import Field

from .consistency import ConsistencyLayer
from .models import (
    Decision,
    IDESource,
    MemoryEvent,
    SessionDigest,
    Task,
    TaskPriority,
    TaskStatus,
)
from .storage import StorageEngine
from .sync import SyncEngine


# ─── Global Server State ────────────────────────────────────────────────────

def _get_project_dir() -> Path:
    """Resolve project directory from env or cwd."""
    project_dir = os.environ.get("MEMORY_PROJECT_DIR")
    if project_dir:
        return Path(project_dir).resolve()
    return Path.cwd()


def _detect_ide() -> IDESource:
    """Detect current IDE from environment variable MEMORY_IDE.
    
    Falls back to SYSTEM if not set. LLMs should explicitly pass ide parameter
    in tool calls based on the IDE rule templates.
    """
    ide_str = os.environ.get("MEMORY_IDE", "").lower()
    if ide_str == "cursor":
        return IDESource.CURSOR
    elif ide_str == "claude_code":
        return IDESource.CLAUDE_CODE
    elif ide_str == "copilot":
        return IDESource.COPILOT
    return IDESource.SYSTEM


class _ServerState:
    """Lazily initialized server state (storage, sync engine, sessions)."""

    def __init__(self):
        self._storage: StorageEngine | None = None
        self._consistency: ConsistencyLayer | None = None
        self._sync: SyncEngine | None = None
        self._sessions: dict[str, str] = {}  # ide_value -> session_id

    def _init(self):
        project_dir = _get_project_dir()
        self._storage = StorageEngine(project_dir)
        self._consistency = ConsistencyLayer(self._storage)
        self._sync = SyncEngine(self._storage, self._consistency)
        self._storage.initialize()
        ok, err = self._consistency.check_and_fix_consistency()
        if not ok and err:
            print(f"Warning: {err}", file=sys.stderr)

    @property
    def storage(self) -> StorageEngine:
        if self._storage is None:
            self._init()
        return self._storage  # type: ignore[return-value]

    @property
    def consistency(self) -> ConsistencyLayer:
        if self._consistency is None:
            self._init()
        return self._consistency  # type: ignore[return-value]

    @property
    def sync(self) -> SyncEngine:
        if self._sync is None:
            self._init()
        return self._sync  # type: ignore[return-value]

    def ensure_session(self, ide: IDESource | None = None) -> str:
        if ide is None:
            ide = _detect_ide()
        key = ide.value
        if key not in self._sessions:
            self._sessions[key] = self.sync.register_session(ide)
        return self._sessions[key]


_state = _ServerState()

# ─── FastMCP Instance ───────────────────────────────────────────────────────

mcp = FastMCP(
    "memory-share",
    instructions=(
        "Memory Share is a cross-IDE memory sharing system. "
        "It lets multiple AI IDEs (Cursor, Claude Code, GitHub Copilot) "
        "share conversation history, decisions, tasks, and project context. "
        "When the user says 'sync memory', use the sync_memory prompt to "
        "follow the smart sync workflow."
    ),
)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool(
    description=(
        "Smart bidirectional memory sync. "
        "Call WITHOUT summary to auto-detect & pull new events from other IDEs. "
        "Call WITH summary to push your session progress (LLM-generated digest). "
        "The system auto-detects sync direction based on version comparison. "
        "IMPORTANT: Only push summaries that contain project-relevant information. "
        "Use skip_if_irrelevant=true to skip syncing irrelevant sessions."
    ),
)
def memory_sync(
    summary: Annotated[
        Optional[str],
        Field(description=(
            "LLM-generated summary of the current session's work. "
            "MUST be filtered to only include project-relevant information: "
            "code changes, architecture decisions, bug fixes, task updates, "
            "project-related discussions. EXCLUDE: personal questions, "
            "unrelated topics, temporary explorations, casual chat. "
            "If provided, pushes this as a digest to shared memory. "
            "If omitted, only pulls new events and returns sync status."
        )),
    ] = None,
    content: Annotated[
        Optional[str],
        Field(description="Detailed content for the push (optional)"),
    ] = None,
    tags: Annotated[
        Optional[list[str]],
        Field(description="Tags for the pushed event (optional)"),
    ] = None,
    skip_if_irrelevant: Annotated[
        bool,
        Field(
            description=(
                "If true and this session contains no project-relevant information, "
                "skip pushing. Use this for sessions that are purely personal questions, "
                "unrelated topics, or temporary explorations."
            ),
        ),
    ] = False,
    ide: Annotated[
        Optional[str],
        Field(description="IDE identifier: cursor / claude_code / copilot"),
    ] = None,
) -> str:
    """Smart sync: auto-detects direction, pulls new events, optionally pushes LLM summary."""
    ide_enum = IDESource(ide) if ide else _detect_ide()
    session_id = _state.ensure_session(ide_enum)

    state = _state.storage.read_state()
    session_info = state.sessions.get(session_id)
    if session_info is None:
        return "Error: session not registered"

    local_version = session_info.last_sync_version
    remote_version = state.version
    has_new_remote = remote_version > local_version

    lines: list[str] = []

    # ── Phase 1: Pull (always) ──────────────────────────────────────────────
    pulled = _state.sync.pull_events(session_id)
    if pulled:
        lines.append(f"📥 Pulled {len(pulled)} new events from shared memory:")
        for evt in pulled[:10]:
            lines.append(f"  - [{evt.source.value}] {evt.summary}")
        if len(pulled) > 10:
            lines.append(f"  ... and {len(pulled) - 10} more")
    else:
        lines.append("📥 No new events from other IDEs.")

    # ── Phase 2: Push (if summary provided) or Skip ─────────────────────────
    if skip_if_irrelevant:
        # User explicitly marked session as irrelevant
        lines.append(
            "\n⏭️  Skipped push: Session marked as irrelevant to project. "
            "No memory updated."
        )
    elif summary:
        # Summary provided → push it
        success, new_ver, error = _state.sync.push_summary(
            session_id=session_id,
            summary=summary,
            content=content or "",
            tags=tags,
        )
        if success:
            lines.append(f"\n📤 Pushed session digest (version {new_ver}):")
            lines.append(f"  \"{summary[:120]}{'...' if len(summary) > 120 else ''}\"")
        else:
            lines.append(f"\n❌ Push failed: {error}")
    else:
        # No summary provided → tell LLM what to do
        lines.append("")
        lines.append("─── Sync Status ───")
        lines.append(f"Session checkpoint: {local_version}")
        lines.append(f"Shared memory version: {remote_version}")
        if has_new_remote:
            lines.append("⚡ New content pulled above.")
        lines.append("")
        lines.append(
            "💡 To push your session progress, call memory_sync again with a "
            "'summary' parameter containing a concise digest of what you "
            "accomplished in this session. Use the sync_memory prompt for guidance."
        )
        lines.append(
            "   If this session is irrelevant to the project, call "
            "memory_sync(skip_if_irrelevant=true) to skip pushing."
        )

    return "\n".join(lines)


@mcp.tool(
    description="Record an architecture or design decision with reasoning and alternatives.",
)
def memory_add_decision(
    title: Annotated[str, Field(description="Brief decision title")],
    decision: Annotated[str, Field(description="What was decided")],
    reasoning: Annotated[
        Optional[str],
        Field(description="Why this decision was made"),
    ] = None,
    alternatives: Annotated[
        Optional[str],
        Field(description="What alternatives were considered"),
    ] = None,
    tags: Annotated[Optional[list[str]], Field(description="Tags")] = None,
    related_files: Annotated[
        Optional[list[str]], Field(description="Related file paths")
    ] = None,
    ide: Annotated[
        Optional[str],
        Field(description="IDE identifier: cursor / claude_code / copilot"),
    ] = None,
) -> str:
    """Record architecture / design decision."""
    ide_enum = IDESource(ide) if ide else _detect_ide()

    dec = Decision(
        source=ide_enum,
        title=title,
        decision=decision,
        reasoning=reasoning or "",
        alternatives=alternatives or "",
        tags=tags or [],
        related_files=related_files or [],
    )

    with _state.consistency.lock():
        decisions = _state.storage.read_decisions()
        decisions.append(dec)
        state = _state.storage.read_state()
        state.version += 1
        _state.storage.write_state(state)
        _state.storage.write_decisions(decisions)

    return f"✅ Decision recorded: {dec.title} (ID: {dec.id})"


@mcp.tool(
    description="Create, update, complete, or cancel a task.",
)
def memory_manage_task(
    action: Annotated[
        str,
        Field(description="Action: create / update / complete / cancel"),
    ],
    task_id: Annotated[
        Optional[str], Field(description="Task ID (required for update/complete/cancel)")
    ] = None,
    title: Annotated[Optional[str], Field(description="Task title")] = None,
    description: Annotated[Optional[str], Field(description="Task description")] = None,
    status: Annotated[
        Optional[str],
        Field(description="Status: pending / in_progress / completed / cancelled"),
    ] = None,
    priority: Annotated[
        Optional[str], Field(description="Priority: high / medium / low")
    ] = None,
    tags: Annotated[Optional[list[str]], Field(description="Tags")] = None,
    related_files: Annotated[
        Optional[list[str]], Field(description="Related file paths")
    ] = None,
    ide: Annotated[
        Optional[str],
        Field(description="IDE identifier: cursor / claude_code / copilot"),
    ] = None,
) -> str:
    """Manage tasks across IDE sessions."""
    ide_enum = IDESource(ide) if ide else _detect_ide()

    with _state.consistency.lock():
        tasks = _state.storage.read_tasks()
        state = _state.storage.read_state()

        if action == "create":
            if not title:
                return "Error: title required for create"
            task = Task(
                created_by=ide_enum,
                updated_by=ide_enum,
                title=title,
                description=description or "",
                status=TaskStatus(status) if status else TaskStatus.PENDING,
                priority=TaskPriority(priority) if priority else TaskPriority.MEDIUM,
                tags=tags or [],
                related_files=related_files or [],
            )
            tasks.append(task)
            state.version += 1
            result = f"✅ Task created: {task.title} (ID: {task.id})"

        elif action in ("update", "complete", "cancel"):
            if not task_id:
                return "Error: task_id required"
            task = next((t for t in tasks if t.id == task_id), None)
            if not task:
                return f"Error: Task {task_id} not found"

            task.updated_by = ide_enum
            task.updated_at = datetime.now(timezone.utc).isoformat()
            if action == "update":
                if title:
                    task.title = title
                if description:
                    task.description = description
                if status:
                    task.status = TaskStatus(status)
                if priority:
                    task.priority = TaskPriority(priority)
            elif action == "complete":
                task.status = TaskStatus.COMPLETED
            elif action == "cancel":
                task.status = TaskStatus.CANCELLED
            state.version += 1
            result = f"✅ Task {action}d: {task.title}"
        else:
            return f"Error: Unknown action '{action}'"

        _state.storage.write_state(state)
        _state.storage.write_tasks(tasks)

    return result


@mcp.tool(
    description="Search shared memories by keyword, tags, or source IDE.",
)
def memory_query(
    keyword: Annotated[
        Optional[str], Field(description="Keyword to search for")
    ] = None,
    tags: Annotated[
        Optional[list[str]], Field(description="Filter by tags")
    ] = None,
    source: Annotated[
        Optional[str],
        Field(description="Filter by IDE source: cursor / claude_code / copilot"),
    ] = None,
    limit: Annotated[int, Field(description="Max results")] = 20,
) -> str:
    """Search events and digests in shared memory."""
    events = _state.storage.read_events_reverse(max_age_hours=48 * 7)
    results: list[str] = []

    for event in events:
        if keyword and keyword.lower() not in (
            event.summary.lower() + " " + event.content.lower()
        ):
            continue
        if tags and not any(t in event.tags for t in tags):
            continue
        if source and event.source.value != source:
            continue
        results.append(f"[{event.source.value}] {event.summary}")
        if len(results) >= limit:
            break

    digests = _state.storage.read_digests()
    for digest in digests:
        if keyword and keyword.lower() not in digest.summary.lower():
            continue
        if tags and not any(t in digest.tags for t in tags):
            continue
        if source and digest.source.value != source:
            continue
        results.append(f"[digest:{digest.source.value}] {digest.summary}")
        if len(results) >= limit:
            break

    if not results:
        return "No matching memories found."

    header = f"Found {len(results)} result(s):\n"
    return header + "\n".join(f"  - {r}" for r in results)


@mcp.tool(
    description="Update project context (current focus, tech stack, description, etc.).",
)
def memory_update_context(
    project_name: Annotated[
        Optional[str], Field(description="Project name")
    ] = None,
    description: Annotated[
        Optional[str], Field(description="Project description")
    ] = None,
    current_focus: Annotated[
        Optional[str], Field(description="What is currently being worked on")
    ] = None,
    tech_stack: Annotated[
        Optional[list[str]], Field(description="Technology stack list")
    ] = None,
    architecture: Annotated[
        Optional[str], Field(description="Architecture overview")
    ] = None,
    key_files: Annotated[
        Optional[list[str]], Field(description="Important files in the project")
    ] = None,
    notes: Annotated[
        Optional[str], Field(description="Additional context notes")
    ] = None,
    ide: Annotated[
        Optional[str],
        Field(description="IDE identifier: cursor / claude_code / copilot"),
    ] = None,
) -> str:
    """Update project context."""
    ide_enum = IDESource(ide) if ide else _detect_ide()
    
    with _state.consistency.lock():
        context = _state.storage.read_context()
        state = _state.storage.read_state()
        
        # Update fields if provided
        if project_name is not None:
            context.project_name = project_name
        if description is not None:
            context.description = description
        if current_focus is not None:
            context.current_focus = current_focus
        if tech_stack is not None:
            context.tech_stack = tech_stack
        if architecture is not None:
            context.architecture = architecture
        if key_files is not None:
            context.key_files = key_files
        if notes is not None:
            context.notes = notes
        
        context.updated_by = ide_enum
        context.updated_at = datetime.now(timezone.utc).isoformat()
        
        state.version += 1
        _state.storage.write_state(state)
        _state.storage.write_context(context)
        
        # Regenerate context.md
        from .compaction import CompactionEngine
        compactor = CompactionEngine(_state.storage, _state.sync)
        compactor._update_context_md()
    
    return f"✅ Project context updated (version {state.version})"


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPTS  (guide the LLM through workflows)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.prompt(
    description=(
        "Smart sync workflow. Use this when the user says "
        "'sync memory' / '同步记忆' / '更新记忆'. "
        "It guides you (the LLM) through the full pull→summarize→push cycle."
    ),
)
def sync_memory() -> str:
    """Return a structured prompt that guides the LLM through smart sync."""
    ide = _detect_ide()
    session_id = _state.ensure_session(ide)
    state = _state.storage.read_state()
    session_info = state.sessions.get(session_id)
    local_ver = session_info.last_sync_version if session_info else 0
    remote_ver = state.version

    return f"""## Memory Sync Workflow

You are performing a smart memory sync for session `{session_id}`.

**Current Status:**
- Your last synced version: {local_ver}
- Shared memory version: {remote_ver}
- {"⚡ There are new events to pull!" if remote_ver > local_ver else "✅ You are up to date."}

**Step 1: Pull**
Call `memory_sync()` WITHOUT a summary parameter to pull any new events from other IDEs.
Review the pulled events to understand what other IDEs have done.

**Step 2: Evaluate Session Relevance**
Before summarizing, evaluate if this session contains **project-relevant information**:

✅ **KEEP (Important):**
- Code changes (files created/modified/deleted)
- Architecture or design decisions
- Bug fixes or issue resolutions
- Task status updates (created/completed/cancelled)
- Project-related discussions that affect future work
- Configuration changes
- Dependencies added/removed
- Test cases added or modified

❌ **SKIP (Irrelevant):**
- Personal questions unrelated to the project
- Casual chat or greetings
- Questions about general programming concepts (not project-specific)
- Temporary explorations that didn't lead to changes
- Questions about unrelated topics (weather, news, etc.)
- Sessions where user just asked "how does X work?" without making changes
- Sessions that are purely for learning/exploration without implementation

**Step 3: Summarize & Push (or Skip)**
- **If session is relevant**: Generate a concise summary (2-5 sentences) capturing:
  - What problems were discussed or solved?
  - What code changes were made?
  - What decisions were reached?
  - What is the current status of ongoing tasks?
  Then call `memory_sync(summary="<your filtered summary>")` to push it.

- **If session is irrelevant**: Call `memory_sync(skip_if_irrelevant=true)` to skip pushing.
  This prevents cluttering shared memory with non-project information.

**Summary Guidelines (ONLY for relevant sessions):**
- Start with the main accomplishment: "Implemented X / Discussed Y / Fixed Z"
- Mention key files modified (if any)
- Note any unresolved issues or next steps
- **Filter out**: personal questions, unrelated topics, temporary explorations
- Keep it under 200 words — this will be read by another AI in a different IDE

**Example Relevant Summary:**
"Implemented the FastMCP-based MCP server rewrite (server.py). Replaced raw mcp SDK with
FastMCP decorators. Added smart sync with auto-direction detection — pull first, then push
with LLM-generated summary. Added MCP prompts and resources. Next: update IDE rule templates."

**Example Irrelevant Session:**
User asked: "How does Python's async work?" → No code changes, no decisions → 
Call `memory_sync(skip_if_irrelevant=true)` to skip.
"""


@mcp.prompt(
    description=(
        "Generate a session digest from old events. Use when the user says "
        "'compress memory' / '压缩记忆' / 'create digest'."
    ),
)
def compress_memory() -> str:
    """Guide the LLM through memory compression."""
    events = _state.storage.read_events_reverse(max_age_hours=48 * 7)
    old_events = [e for e in events if _is_older_than_hours(e.timestamp, 48)]

    if not old_events:
        return "No events older than 48 hours found. Nothing to compress."

    event_list = "\n".join(
        f"  - [{e.source.value}] {e.summary}" for e in old_events[:30]
    )

    return f"""## Memory Compression Workflow

There are {len(old_events)} events older than 48 hours that can be compressed.

**Events to compress (showing up to 30):**
{event_list}

**Your Task:**
1. Read through the events above
2. **Filter out irrelevant events** — Only include events that contain:
   - Code changes or file modifications
   - Architecture/design decisions
   - Bug fixes or issue resolutions
   - Task status updates
   - Project-relevant discussions
   
   **Exclude events that are:**
   - Personal questions
   - Unrelated topics
   - Temporary explorations without outcomes
   - Casual chat

3. Generate a comprehensive summary that captures **ONLY the filtered, relevant events**:
   - Key decisions and their reasoning
   - Important milestones or changes
   - Any patterns or themes across relevant events
   - **Skip** events that don't contribute to project understanding

4. Call `memory_sync(summary="<your filtered compressed digest>", tags=["digest", "compressed"])`
   to save the digest

**Guidelines:**
- **Filter first, then summarize** — Don't include irrelevant information
- Group related events together in your summary
- Preserve critical details (file names, decision rationale, error causes)
- Be concise but don't lose important context
- Aim for 3-8 sentences covering only project-relevant information
- If all events are irrelevant, call `memory_sync(skip_if_irrelevant=true)` instead
"""


def _is_older_than_hours(timestamp_str: str, hours: float) -> bool:
    """Check if a timestamp is older than N hours."""
    from datetime import timedelta
    try:
        event_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return event_time < cutoff
    except (ValueError, TypeError):
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# RESOURCES  (expose memory state as browsable data)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.resource(
    "memory://briefing",
    name="Memory Briefing",
    description="Full context briefing: active tasks, decisions, recent events, project context.",
    mime_type="text/markdown",
)
def get_briefing() -> str:
    """Return a complete memory briefing as Markdown."""
    ide = _detect_ide()
    session_id = _state.ensure_session(ide)
    briefing = _state.sync.get_briefing(session_id)

    lines = [
        f"# Memory Briefing (v{briefing['checkpoint']})",
        "",
        "## Active Tasks",
    ]
    for t in briefing["active_tasks"]:
        lines.append(f"- [{t['status']}] **{t['title']}** ({t['priority']})")
        if t.get("description"):
            lines.append(f"  {t['description'][:120]}")

    lines.extend(["", "## Active Decisions"])
    for d in briefing["active_decisions"]:
        lines.append(f"- **{d['title']}**: {d['decision']}")
        if d.get("reasoning"):
            lines.append(f"  _Reasoning_: {d['reasoning'][:120]}")

    lines.extend(["", "## Recent Events (last 48h)"])
    for e in briefing["recent_events"][:15]:
        lines.append(f"- [{e['source']}] {e['summary']}")

    ctx = briefing["context"]
    lines.extend([
        "",
        "## Project Context",
        f"**Name**: {ctx.get('project_name', 'Unknown')}",
        f"**Description**: {ctx.get('description', 'No description')}",
        f"**Tech Stack**: {', '.join(ctx.get('tech_stack', []))}",
        f"**Current Focus**: {ctx.get('current_focus', 'None')}",
    ])

    return "\n".join(lines)


@mcp.resource(
    "memory://tasks",
    name="All Tasks",
    description="All tracked tasks with their current status.",
    mime_type="text/markdown",
)
def get_tasks() -> str:
    """Return all tasks as Markdown."""
    tasks = _state.storage.read_tasks()
    if not tasks:
        return "# Tasks\n\nNo tasks tracked yet."

    lines = ["# Tasks", ""]

    for status_label, statuses in [
        ("🔴 In Progress", [TaskStatus.IN_PROGRESS]),
        ("🟡 Pending", [TaskStatus.PENDING]),
        ("🟢 Completed", [TaskStatus.COMPLETED]),
        ("⚫ Cancelled / Blocked", [TaskStatus.CANCELLED, TaskStatus.BLOCKED]),
    ]:
        group = [t for t in tasks if t.status in statuses]
        if group:
            lines.append(f"## {status_label}")
            for t in group:
                lines.append(f"- **{t.title}** (ID: {t.id}, priority: {t.priority.value})")
                if t.description:
                    lines.append(f"  {t.description[:150]}")
            lines.append("")

    return "\n".join(lines)


@mcp.resource(
    "memory://decisions",
    name="All Decisions",
    description="All recorded architecture and design decisions.",
    mime_type="text/markdown",
)
def get_decisions() -> str:
    """Return all decisions as Markdown."""
    decisions = _state.storage.read_decisions()
    if not decisions:
        return "# Decisions\n\nNo decisions recorded yet."

    lines = ["# Decisions", ""]
    for d in decisions:
        status_icon = {"active": "🟢", "superseded": "🔴", "reverted": "⚪"}.get(
            d.status.value, "❓"
        )
        lines.append(f"### {status_icon} {d.title}")
        lines.append(f"- **Decision**: {d.decision}")
        if d.reasoning:
            lines.append(f"- **Reasoning**: {d.reasoning}")
        if d.alternatives:
            lines.append(f"- **Alternatives**: {d.alternatives}")
        lines.append(f"- _Source_: {d.source.value} | _Date_: {d.timestamp[:10]}")
        lines.append("")

    return "\n".join(lines)


@mcp.resource(
    "memory://status",
    name="Sync Status",
    description="Current sync status: version, sessions, health info.",
    mime_type="text/markdown",
)
def get_status() -> str:
    """Return sync status as Markdown."""
    state = _state.storage.read_state()
    lines = [
        "# Memory Sync Status",
        "",
        f"**Global Version**: {state.version}",
        f"**Active Sessions**: {len(state.sessions)}",
        "",
        "## Sessions",
    ]
    for sid, sinfo in state.sessions.items():
        behind = state.version - sinfo.last_sync_version
        lines.append(
            f"- `{sid}` ({sinfo.ide.value}) — "
            f"synced to v{sinfo.last_sync_version}"
            f"{f' ⚠️ {behind} behind' if behind > 0 else ' ✅ up to date'}"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    """Run the MCP server via stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
