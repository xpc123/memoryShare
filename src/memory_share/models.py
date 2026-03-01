"""Data models for the Memory Share system."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IDESource(str, Enum):
    """Supported IDE sources."""
    CURSOR = "cursor"
    CLAUDE_CODE = "claude_code"
    COPILOT = "copilot"
    USER = "user"
    SYSTEM = "system"


class EventType(str, Enum):
    """Types of memory events."""
    CONVERSATION = "conversation"      # Conversation summary
    ACTION = "action"                  # Code action performed
    MILESTONE = "milestone"            # Important milestone reached
    NOTE = "note"                      # General note
    SESSION_START = "session_start"    # New session started
    SESSION_END = "session_end"        # Session ended with summary
    ERROR = "error"                    # Error or issue encountered


class TaskStatus(str, Enum):
    """Task status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class TaskPriority(str, Enum):
    """Task priority levels."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DecisionStatus(str, Enum):
    """Decision status."""
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVERTED = "reverted"


# ─── Memory Event ───────────────────────────────────────────────────────────

class MemoryEvent(BaseModel):
    """A single memory event - the atomic unit of shared memory."""
    schema_version: int = Field(default=1, description="Schema version for migration")
    version: Optional[int] = Field(default=None, description="Monotonic version number")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    idempotency_key: Optional[str] = Field(
        default=None, description="Idempotency key for deduplication"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source: IDESource
    event_type: EventType
    summary: str = Field(description="Brief 1-2 sentence summary")
    content: str = Field(default="", description="Detailed content")
    tags: list[str] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    session_id: Optional[str] = None


# ─── Decision ───────────────────────────────────────────────────────────────

class Decision(BaseModel):
    """A recorded design/architecture decision."""
    schema_version: int = Field(default=1, description="Schema version for migration")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source: IDESource
    title: str
    decision: str = Field(description="What was decided")
    reasoning: str = Field(default="", description="Why this decision was made")
    alternatives: str = Field(
        default="", description="What alternatives were considered"
    )
    status: DecisionStatus = DecisionStatus.ACTIVE
    tags: list[str] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    superseded_by: Optional[str] = Field(
        default=None, description="ID of decision that supersedes this one"
    )


# ─── Task ────────────────────────────────────────────────────────────────────

class Task(BaseModel):
    """A tracked task that persists across IDE sessions."""
    schema_version: int = Field(default=1, description="Schema version for migration")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    created_by: IDESource
    updated_by: IDESource
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    tags: list[str] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    subtasks: list[str] = Field(
        default_factory=list, description="Sub-task descriptions"
    )
    needs_manual_resolution: bool = Field(
        default=False, description="Flag for Git merge conflicts requiring manual review"
    )


# ─── Project Context ────────────────────────────────────────────────────────

class ProjectContext(BaseModel):
    """The current project context summary, maintained across sessions."""
    schema_version: int = Field(default=1, description="Schema version for migration")
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_by: IDESource = IDESource.SYSTEM
    project_name: str = ""
    description: str = ""
    architecture: str = Field(
        default="", description="Architecture overview"
    )
    tech_stack: list[str] = Field(default_factory=list)
    current_focus: str = Field(
        default="", description="What is currently being worked on"
    )
    key_files: list[str] = Field(
        default_factory=list, description="Important files in the project"
    )
    notes: str = Field(default="", description="Additional context notes")


# ─── Session Digest ───────────────────────────────────────────────────────────

class SessionDigest(BaseModel):
    """Compressed session digest for warm memory."""
    schema_version: int = Field(default=1, description="Schema version for migration")
    id: str = Field(default_factory=lambda: f"dg_{uuid.uuid4().hex[:8]}")
    period: str = Field(description="Time period: start/end ISO timestamps")
    source: IDESource
    summary: str = Field(description="Compressed summary of session")
    event_count: int = Field(description="Number of events compressed into this digest")
    tags: list[str] = Field(default_factory=list)


# ─── Sync State ───────────────────────────────────────────────────────────────

class SessionInfo(BaseModel):
    """Information about an active session."""
    ide: IDESource
    started_at: str
    last_active_at: str
    last_sync_version: int


class SyncState(BaseModel):
    """Global sync state with version counter and session checkpoints."""
    schema_version: int = Field(default=1, description="Schema version for migration")
    version: int = Field(default=0, description="Monotonic global version counter")
    sessions: dict[str, SessionInfo] = Field(
        default_factory=dict, description="Active sessions by session_id"
    )
