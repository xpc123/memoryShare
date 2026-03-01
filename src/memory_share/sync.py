"""Checkpoint-based sync engine for incremental pull/push."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .consistency import ConsistencyLayer
from .models import IDESource, MemoryEvent, SessionInfo, SyncState
from .storage import StorageEngine


class SyncEngine:
    """Checkpoint-based sync engine for incremental memory synchronization."""

    def __init__(self, storage: StorageEngine, consistency: ConsistencyLayer):
        """Initialize sync engine.

        Args:
            storage: Storage engine instance
            consistency: Consistency layer instance
        """
        self.storage = storage
        self.consistency = consistency

    def register_session(
        self, ide: IDESource, session_id: Optional[str] = None
    ) -> str:
        """Register a new session and return session_id.

        Args:
            ide: IDE source
            session_id: Optional session ID (if None, generates new)

        Returns:
            Session ID
        """
        if session_id is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            session_id = f"{ide.value}_{timestamp}_{uuid.uuid4().hex[:8]}"

        with self.consistency.lock():
            state = self.storage.read_state()
            now = datetime.now(timezone.utc).isoformat()

            # Clean up old sessions for this IDE
            self._cleanup_old_sessions(state, ide)

            # Register new session
            state.sessions[session_id] = SessionInfo(
                ide=ide,
                started_at=now,
                last_active_at=now,
                last_sync_version=state.version,
            )

            self.storage.write_state(state)
            return session_id

    def update_session_activity(self, session_id: str) -> None:
        """Update last_active_at for a session.

        Args:
            session_id: Session ID
        """
        with self.consistency.lock():
            state = self.storage.read_state()
            if session_id in state.sessions:
                state.sessions[session_id].last_active_at = (
                    datetime.now(timezone.utc).isoformat()
                )
                self.storage.write_state(state)

    def _cleanup_old_sessions(self, state: SyncState, ide: IDESource) -> None:
        """Clean up old sessions for an IDE (keep only recent N).

        Args:
            state: Current sync state
            ide: IDE to clean up sessions for
        """
        config = self.storage.read_config()
        max_sessions = config.get("max_sessions_per_ide", 3)

        # Get sessions for this IDE
        ide_sessions = [
            (sid, sinfo)
            for sid, sinfo in state.sessions.items()
            if sinfo.ide == ide
        ]

        # Sort by last_active_at (newest first)
        ide_sessions.sort(
            key=lambda x: x[1].last_active_at, reverse=True
        )

        # Remove excess sessions
        if len(ide_sessions) >= max_sessions:
            for sid, _ in ide_sessions[max_sessions:]:
                del state.sessions[sid]

    def get_briefing(
        self, session_id: str, token_budget: Optional[int] = None
    ) -> dict:
        """Get full briefing for a session.

        Args:
            session_id: Session ID
            token_budget: Optional token budget limit

        Returns:
            Briefing dictionary
        """
        self.update_session_activity(session_id)

        config = self.storage.read_config()
        if token_budget is None:
            token_budget = config.get("briefing_token_budget", 3000)
        hot_hours = config.get("hot_memory_hours", 48)

        # Read hot memory
        events = self.storage.read_events_reverse(max_age_hours=hot_hours)
        tasks = self.storage.read_tasks()
        decisions = self.storage.read_decisions()
        context = self.storage.read_context()

        # Filter active tasks
        active_tasks = [t for t in tasks if t.status.value in ["pending", "in_progress"]]

        # Filter active decisions
        active_decisions = [d for d in decisions if d.status.value == "active"]

        # Get state for checkpoint
        state = self.storage.read_state()
        session_info = state.sessions.get(session_id)
        checkpoint = session_info.last_sync_version if session_info else state.version

        briefing = {
            "checkpoint": checkpoint,
            "session_id": session_id,
            "active_tasks": [t.model_dump() for t in active_tasks],
            "active_decisions": [d.model_dump() for d in active_decisions],
            "recent_events": [e.model_dump() for e in events[:20]],  # Limit events
            "context": context.model_dump(),
        }

        # Apply token budget trimming
        briefing = self._trim_briefing_to_budget(briefing, token_budget)

        return briefing
    
    def _trim_briefing_to_budget(self, briefing: dict, token_budget: int) -> dict:
        """Trim briefing content to fit within token budget.
        
        Uses simple token estimation: ~4 characters per token.
        Priority: context > active_tasks > active_decisions > recent_events
        """
        def estimate_tokens(text: str) -> int:
            """Rough token estimation: ~4 chars per token."""
            return len(text) // 4
        
        def serialize_briefing(b: dict) -> str:
            """Serialize briefing to text for token counting."""
            import json
            return json.dumps(b, ensure_ascii=False)
        
        current_tokens = estimate_tokens(serialize_briefing(briefing))
        if current_tokens <= token_budget:
            return briefing
        
        # Trim in priority order (least important first)
        trimmed = briefing.copy()
        
        # 1. Trim events (least important)
        if trimmed["recent_events"]:
            while estimate_tokens(serialize_briefing(trimmed)) > token_budget and trimmed["recent_events"]:
                trimmed["recent_events"] = trimmed["recent_events"][:-1]
        
        # 2. Trim decision details
        if trimmed["active_decisions"]:
            while estimate_tokens(serialize_briefing(trimmed)) > token_budget and trimmed["active_decisions"]:
                dec = trimmed["active_decisions"][-1]
                # Truncate reasoning/alternatives
                if dec.get("reasoning"):
                    dec["reasoning"] = dec["reasoning"][:100] + "..."
                if dec.get("alternatives"):
                    dec["alternatives"] = dec["alternatives"][:100] + "..."
                if estimate_tokens(serialize_briefing(trimmed)) <= token_budget:
                    break
                trimmed["active_decisions"] = trimmed["active_decisions"][:-1]
        
        # 3. Trim task descriptions
        if trimmed["active_tasks"]:
            while estimate_tokens(serialize_briefing(trimmed)) > token_budget and trimmed["active_tasks"]:
                task = trimmed["active_tasks"][-1]
                if task.get("description"):
                    task["description"] = task["description"][:80] + "..."
                if estimate_tokens(serialize_briefing(trimmed)) <= token_budget:
                    break
                trimmed["active_tasks"] = trimmed["active_tasks"][:-1]
        
        # 4. Trim context notes (last resort)
        if trimmed["context"].get("notes") and estimate_tokens(serialize_briefing(trimmed)) > token_budget:
            trimmed["context"]["notes"] = trimmed["context"]["notes"][:200] + "..."
        
        return trimmed

    def pull_events(
        self, session_id: str, since_version: Optional[int] = None
    ) -> list[MemoryEvent]:
        """Pull events since checkpoint (excluding events from the same session).

        Args:
            session_id: Session ID
            since_version: Version to pull from (if None, uses session checkpoint)

        Returns:
            List of new events from other sessions (not from this session)
        """
        self.update_session_activity(session_id)

        state = self.storage.read_state()
        session_info = state.sessions.get(session_id)
        if session_info is None:
            return []

        if since_version is None:
            since_version = session_info.last_sync_version

        # Read all events since checkpoint
        all_events = self.storage.read_events_reverse(max_age_hours=48 * 7)  # 1 week
        new_events = [
            e for e in all_events
            if e.version is not None
            and e.version > since_version
            and e.session_id != session_id  # Exclude events from the same session
        ]

        return new_events

    def push_summary(
        self,
        session_id: str,
        summary: str,
        content: str = "",
        tags: Optional[list[str]] = None,
        related_files: Optional[list[str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> tuple[bool, int, Optional[str]]:
        """Push session summary as event.

        Args:
            session_id: Session ID
            summary: Summary text
            content: Detailed content
            tags: Optional tags
            related_files: Optional related files
            idempotency_key: Optional idempotency key

        Returns:
            (success, new_version, error_message)
        """
        self.update_session_activity(session_id)

        state = self.storage.read_state()
        session_info = state.sessions.get(session_id)
        if session_info is None:
            return False, state.version, "Session not found"

        # Generate idempotency key if not provided
        if idempotency_key is None:
            checkpoint = session_info.last_sync_version
            idempotency_key = self.consistency.generate_idempotency_key(
                source=session_info.ide.value,
                session_id=session_id,
                checkpoint_range=(checkpoint, state.version),
                summary_hash=hash(summary).__str__()[:8],
            )

        # Check idempotency
        cached = self.consistency.idempotency.get(idempotency_key)
        if cached is not None:
            # Return cached version
            return True, cached, None

        # Create event
        new_version = state.version + 1
        event = MemoryEvent(
            schema_version=1,
            version=new_version,
            idempotency_key=idempotency_key,
            source=session_info.ide,
            event_type="conversation",
            summary=summary,
            content=content,
            tags=tags or [],
            related_files=related_files or [],
            session_id=session_id,
        )

        # Append event FIRST (before updating state)
        # This ensures that if we crash, consistency check can detect
        # events with version > state.version and auto-fix
        self.storage.append_event(event)

        # Then update state with CAS
        def update_state(s: SyncState) -> SyncState:
            s.version = new_version
            if session_id in s.sessions:
                s.sessions[session_id].last_sync_version = new_version
            return s

        success, result = self.consistency.cas_with_idempotency(
            idempotency_key=idempotency_key,
            expected_version=state.version,
            update_fn=update_state,
        )

        if not success:
            # Event was appended but state update failed
            # This is recoverable: consistency check will auto-fix on next startup
            # But we should still return error to caller
            return False, state.version, str(result)

        # Cache result
        self.consistency.idempotency.set(idempotency_key, new_version)

        return True, new_version, None

    def sync(
        self,
        session_id: str,
        direction: str = "both",
        push_summary: Optional[str] = None,
        push_content: str = "",
        push_tags: Optional[list[str]] = None,
    ) -> dict:
        """Perform sync operation (pull, push, or both).

        Args:
            session_id: Session ID
            direction: "pull", "push", "both", or "status"
            push_summary: Summary for push (required if direction includes push)
            push_content: Detailed content for push
            push_tags: Tags for push

        Returns:
            Sync result dictionary
        """
        result = {
            "pulled_events": [],
            "pushed_version": None,
            "checkpoint": None,
            "error": None,
        }

        state = self.storage.read_state()
        session_info = state.sessions.get(session_id)
        if session_info is None:
            result["error"] = "Session not found"
            return result

        result["checkpoint"] = session_info.last_sync_version

        # Pull
        if direction in ("pull", "both", "status"):
            pulled = self.pull_events(session_id)
            result["pulled_events"] = [e.model_dump() for e in pulled]

        # Push
        if direction in ("push", "both"):
            if push_summary is None:
                result["error"] = "push_summary required for push direction"
                return result

            success, new_version, error = self.push_summary(
                session_id=session_id,
                summary=push_summary,
                content=push_content,
                tags=push_tags,
            )

            if success:
                result["pushed_version"] = new_version
                result["checkpoint"] = new_version
            else:
                result["error"] = error

        return result

    def cleanup_stale_sessions(self, ttl_days: Optional[int] = None) -> int:
        """Clean up stale sessions (older than TTL).

        Args:
            ttl_days: TTL in days (if None, uses config)

        Returns:
            Number of sessions cleaned up
        """
        if ttl_days is None:
            config = self.storage.read_config()
            ttl_days = config.get("session_ttl_days", 7)

        cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        cutoff_str = cutoff.isoformat()

        with self.consistency.lock():
            state = self.storage.read_state()
            removed = 0

            for session_id, session_info in list(state.sessions.items()):
                if session_info.last_active_at < cutoff_str:
                    del state.sessions[session_id]
                    removed += 1

            if removed > 0:
                self.storage.write_state(state)

            return removed
