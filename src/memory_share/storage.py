"""Storage engine for reading/writing memory files with NFS-safe locking."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from .models import (
    Decision,
    MemoryEvent,
    ProjectContext,
    SessionDigest,
    SyncState,
    Task,
)


class StorageEngine:
    """Storage engine for .memory/ directory with NFS-safe operations."""

    SCHEMA_VERSION = 1

    def __init__(self, project_dir: Path):
        """Initialize storage engine for a project.

        Args:
            project_dir: Root directory of the project (where .memory/ will be)
        """
        self.project_dir = Path(project_dir).resolve()
        self.memory_dir = self.project_dir / ".memory"
        self.lock_dir = self.memory_dir / ".lock"
        self.archive_dir = self.memory_dir / "archive"
        self.backup_dir = self.memory_dir / "backup"

    def initialize(self) -> None:
        """Initialize .memory/ directory structure."""
        self.memory_dir.mkdir(exist_ok=True)
        self.archive_dir.mkdir(exist_ok=True)
        self.backup_dir.mkdir(exist_ok=True)

        # Initialize default files if they don't exist
        if not (self.memory_dir / "state.json").exists():
            self.write_state(SyncState(version=0, sessions={}))

        if not (self.memory_dir / "decisions.json").exists():
            self.write_decisions([])

        if not (self.memory_dir / "tasks.json").exists():
            self.write_tasks([])

        if not (self.memory_dir / "context.json").exists():
            self.write_context(ProjectContext())

        if not (self.memory_dir / "config.json").exists():
            self.write_config({
                "briefing_token_budget": 3000,
                "hot_memory_hours": 48,
                "warm_memory_days": 30,
                "session_ttl_days": 7,
                "max_sessions_per_ide": 3,
            })

    # ─── Lock Management (NFS-safe) ───────────────────────────────────────────

    def acquire_lock(self, timeout: float = 5.0) -> bool:
        """Acquire mkdir-based lock (NFS-safe).

        Args:
            timeout: Maximum time to wait for lock

        Returns:
            True if lock acquired, False if timeout

        Raises:
            TimeoutError: If lock cannot be acquired within timeout
        """
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.lock_dir.mkdir(parents=True, exist_ok=False)
                # Write owner info
                owner_file = self.lock_dir / "owner"
                owner_file.write_text(f"{os.getpid()}:{time.time()}\n")
                return True
            except FileExistsError:
                # Check if lock is stale
                if self._is_stale_lock(max_age=30):
                    try:
                        shutil.rmtree(self.lock_dir)
                        continue
                    except OSError:
                        pass
                time.sleep(0.05)
        raise TimeoutError("Failed to acquire memory lock")

    def release_lock(self) -> None:
        """Release the lock."""
        try:
            shutil.rmtree(self.lock_dir)
        except OSError:
            pass  # Lock may not exist

    def _is_stale_lock(self, max_age: float = 30.0) -> bool:
        """Check if lock is stale (older than max_age seconds)."""
        import time

        owner_file = self.lock_dir / "owner"
        if not owner_file.exists():
            return True

        try:
            content = owner_file.read_text().strip()
            _, timestamp_str = content.split(":")
            timestamp = float(timestamp_str)
            return (time.time() - timestamp) > max_age
        except (ValueError, OSError):
            return True

    # ─── Atomic Write Helpers ──────────────────────────────────────────────────

    def _atomic_write_json(
        self, filepath: Path, data: Any, ensure_dir: bool = True
    ) -> None:
        """Atomically write JSON file (tmp -> fsync -> rename).

        Args:
            filepath: Target file path
            data: Data to serialize as JSON
            ensure_dir: Create parent directory if needed
        """
        if ensure_dir:
            filepath.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first
        fd, tmp_path = tempfile.mkstemp(
            dir=filepath.parent, prefix=f".{filepath.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Ensure written to disk

            # Atomic rename
            os.rename(tmp_path, filepath)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _atomic_append_jsonl(self, filepath: Path, data: dict) -> None:
        """Atomically append to JSONL file.

        Args:
            filepath: Target JSONL file
            data: Dictionary to append as JSON line
        """
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Append mode (atomic on most filesystems)
        with open(filepath, "a") as f:
            json.dump(data, f, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

    # ─── State Management ─────────────────────────────────────────────────────

    def read_state(self) -> SyncState:
        """Read sync state."""
        state_file = self.memory_dir / "state.json"
        if not state_file.exists():
            return SyncState(version=0, sessions={})

        with open(state_file) as f:
            data = json.load(f)

        # Handle schema version migration (basic)
        schema_version = data.get("schema_version", 1)
        if schema_version != self.SCHEMA_VERSION:
            # TODO: Call migration engine
            pass

        return SyncState(**data)

    def write_state(self, state: SyncState) -> None:
        """Write sync state atomically."""
        state_file = self.memory_dir / "state.json"
        data = state.model_dump()
        self._atomic_write_json(state_file, data)

    # ─── Events (JSONL) ───────────────────────────────────────────────────────

    def read_events_reverse(
        self, max_age_hours: float = 48.0, limit: Optional[int] = None
    ) -> list[MemoryEvent]:
        """Read events in reverse order (from newest), stopping at max_age.

        Args:
            max_age_hours: Maximum age in hours to include
            limit: Maximum number of events to return

        Returns:
            List of events (newest first)
        """
        from datetime import datetime, timedelta, timezone

        events_file = self.memory_dir / "events.jsonl"
        if not events_file.exists():
            return []

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        events = []

        # Read file in reverse (from end)
        try:
            with open(events_file, "rb") as f:
                # Seek to end
                f.seek(0, 2)
                file_size = f.tell()

                # Read backwards in chunks
                chunk_size = 8192
                buffer = b""
                position = file_size

                while position > 0 and (limit is None or len(events) < limit):
                    # Read chunk
                    read_size = min(chunk_size, position)
                    position -= read_size
                    f.seek(position)
                    chunk = f.read(read_size) + buffer

                    # Split into lines
                    lines = chunk.split(b"\n")
                    buffer = lines[0]  # Incomplete line at start

                    # Process complete lines (in reverse)
                    for line_bytes in reversed(lines[1:]):
                        if not line_bytes.strip():
                            continue

                        try:
                            line_data = json.loads(line_bytes.decode("utf-8"))
                            event = MemoryEvent(**line_data)

                            # Check timestamp
                            event_time = datetime.fromisoformat(
                                event.timestamp.replace("Z", "+00:00")
                            )
                            if event_time < cutoff_time:
                                # Stop reading older events
                                return list(reversed(events))

                            events.append(event)
                            if limit and len(events) >= limit:
                                return list(reversed(events))
                        except (json.JSONDecodeError, ValueError, KeyError):
                            continue  # Skip malformed lines

                # Process remaining buffer
                if buffer.strip():
                    try:
                        line_data = json.loads(buffer.decode("utf-8"))
                        event = MemoryEvent(**line_data)
                        event_time = datetime.fromisoformat(
                            event.timestamp.replace("Z", "+00:00")
                        )
                        if event_time >= cutoff_time:
                            events.append(event)
                    except (json.JSONDecodeError, ValueError, KeyError):
                        pass

        except OSError:
            return []

        return list(reversed(events))

    def append_event(self, event: MemoryEvent) -> None:
        """Append event to events.jsonl."""
        events_file = self.memory_dir / "events.jsonl"
        data = event.model_dump()
        self._atomic_append_jsonl(events_file, data)

    def check_consistency(self) -> tuple[bool, Optional[str]]:
        """Check consistency between events.jsonl and state.json.

        Returns:
            (is_consistent, error_message)
        """
        events_file = self.memory_dir / "events.jsonl"
        if not events_file.exists():
            return True, None

        # Read last event version
        last_event_version = None
        try:
            with open(events_file, "rb") as f:
                f.seek(0, 2)  # Seek to end
                file_size = f.tell()
                if file_size == 0:
                    return True, None

                # Read last line
                chunk_size = min(4096, file_size)
                f.seek(max(0, file_size - chunk_size))
                chunk = f.read(chunk_size).decode("utf-8", errors="ignore")
                lines = chunk.split("\n")
                for line in reversed(lines):
                    if line.strip():
                        try:
                            data = json.loads(line)
                            last_event_version = data.get("version")
                            break
                        except json.JSONDecodeError:
                            continue
        except OSError:
            return True, None

        # Compare with state version
        state = self.read_state()
        if last_event_version is not None and last_event_version > state.version:
            # Inconsistency detected - auto-fix
            state.version = last_event_version
            self.write_state(state)
            return False, (
                f"Inconsistency detected: state version {state.version} < "
                f"last event version {last_event_version}. Auto-fixed."
            )

        return True, None

    # ─── Decisions ────────────────────────────────────────────────────────────

    def read_decisions(self) -> list[Decision]:
        """Read all decisions."""
        decisions_file = self.memory_dir / "decisions.json"
        if not decisions_file.exists():
            return []

        with open(decisions_file) as f:
            data = json.load(f)

        return [Decision(**item) for item in data]

    def write_decisions(self, decisions: list[Decision]) -> None:
        """Write decisions atomically."""
        decisions_file = self.memory_dir / "decisions.json"
        data = [d.model_dump() for d in decisions]
        self._atomic_write_json(decisions_file, data)

    # ─── Tasks ─────────────────────────────────────────────────────────────────

    def read_tasks(self) -> list[Task]:
        """Read all tasks."""
        tasks_file = self.memory_dir / "tasks.json"
        if not tasks_file.exists():
            return []

        with open(tasks_file) as f:
            data = json.load(f)

        return [Task(**item) for item in data]

    def write_tasks(self, tasks: list[Task]) -> None:
        """Write tasks atomically."""
        tasks_file = self.memory_dir / "tasks.json"
        data = [t.model_dump() for t in tasks]
        self._atomic_write_json(tasks_file, data)

    # ─── Context ──────────────────────────────────────────────────────────────

    def read_context(self) -> ProjectContext:
        """Read project context."""
        context_file = self.memory_dir / "context.json"
        if not context_file.exists():
            return ProjectContext()

        with open(context_file) as f:
            data = json.load(f)

        return ProjectContext(**data)

    def write_context(self, context: ProjectContext) -> None:
        """Write project context atomically."""
        context_file = self.memory_dir / "context.json"
        data = context.model_dump()
        self._atomic_write_json(context_file, data)

    # ─── Digests ───────────────────────────────────────────────────────────────

    def read_digests(self) -> list[SessionDigest]:
        """Read all session digests."""
        digests_file = self.memory_dir / "digests.jsonl"
        if not digests_file.exists():
            return []

        digests = []
        with open(digests_file) as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        digests.append(SessionDigest(**data))
                    except (json.JSONDecodeError, ValueError, KeyError):
                        continue

        return digests

    def append_digest(self, digest: SessionDigest) -> None:
        """Append digest to digests.jsonl."""
        digests_file = self.memory_dir / "digests.jsonl"
        data = digest.model_dump()
        self._atomic_append_jsonl(digests_file, data)

    # ─── Config ───────────────────────────────────────────────────────────────

    def read_config(self) -> dict[str, Any]:
        """Read configuration."""
        config_file = self.memory_dir / "config.json"
        if not config_file.exists():
            return {
                "briefing_token_budget": 3000,
                "hot_memory_hours": 48,
                "warm_memory_days": 30,
                "session_ttl_days": 7,
                "max_sessions_per_ide": 3,
            }

        with open(config_file) as f:
            return json.load(f)

    def write_config(self, config: dict[str, Any]) -> None:
        """Write configuration atomically."""
        config_file = self.memory_dir / "config.json"
        self._atomic_write_json(config_file, config)
