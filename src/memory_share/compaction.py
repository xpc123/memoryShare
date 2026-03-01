"""Compaction engine: summarize old events, archive, prune, clean sessions."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import IDESource, MemoryEvent, ProjectContext, SessionDigest
from .storage import StorageEngine
from .sync import SyncEngine


class CompactionEngine:
    """Compaction engine for hot -> warm -> cold memory lifecycle."""

    def __init__(self, storage: StorageEngine, sync_engine: SyncEngine):
        """Initialize compaction engine.

        Args:
            storage: Storage engine instance
            sync_engine: Sync engine instance
        """
        self.storage = storage
        self.sync_engine = sync_engine

    def compact(self) -> dict[str, Any]:
        """Run full compaction process.

        Returns:
            Compaction statistics
        """
        stats = {
            "digests_created": 0,
            "events_archived": 0,
            "tasks_archived": 0,
            "sessions_cleaned": 0,
        }

        config = self.storage.read_config()
        hot_hours = config.get("hot_memory_hours", 48)
        warm_days = config.get("warm_memory_days", 30)

        # 1. Create digests from old events
        stats["digests_created"] = self._create_digests(hot_hours)

        # 2. Archive old tasks
        stats["tasks_archived"] = self._archive_old_tasks(warm_days)

        # 3. Clean stale sessions
        stats["sessions_cleaned"] = self.sync_engine.cleanup_stale_sessions()

        # 4. Update context.md (dynamic generation)
        self._update_context_md()

        return stats

    def _create_digests(self, hot_hours: float) -> int:
        """Create session digests from events older than hot_hours.

        Args:
            hot_hours: Hot memory window in hours

        Returns:
            Number of digests created
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hot_hours)
        cutoff_str = cutoff.isoformat()

        # Read all events
        events_file = self.storage.memory_dir / "events.jsonl"
        if not events_file.exists():
            return 0

        # Group events by session
        session_events: dict[str, list[MemoryEvent]] = defaultdict(list)

        with open(events_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    event = MemoryEvent(**data)

                    # Only process events older than cutoff
                    event_time = datetime.fromisoformat(
                        event.timestamp.replace("Z", "+00:00")
                    )
                    if event_time >= cutoff:
                        continue  # Still in hot memory

                    if event.session_id:
                        session_events[event.session_id].append(event)
                except (json.JSONDecodeError, ValueError, KeyError):
                    continue

        # Create digests
        digests_created = 0
        for session_id, events in session_events.items():
            if not events:
                continue

            # Sort by timestamp
            events.sort(key=lambda e: e.timestamp)

            # Generate summary
            sources = set(e.source for e in events)
            source = sources.pop() if len(sources) == 1 else IDESource.SYSTEM

            # Aggregate tags
            all_tags = set()
            for event in events:
                all_tags.update(event.tags)

            # Create summary text
            summaries = [e.summary for e in events if e.summary]
            summary = ". ".join(summaries[:3])  # First 3 summaries
            if len(summaries) > 3:
                summary += f" ... ({len(events)} events total)"

            period = f"{events[0].timestamp}/{events[-1].timestamp}"

            digest = SessionDigest(
                period=period,
                source=source,
                summary=summary,
                event_count=len(events),
                tags=list(all_tags),
            )

            self.storage.append_digest(digest)
            digests_created += 1

        # Archive processed events (move to archive directory)
        if session_events:
            # Read all events to filter out processed ones
            events_file = self.storage.memory_dir / "events.jsonl"
            if events_file.exists():
                archived_events = []
                remaining_events = []
                processed_event_ids = {e.id for events in session_events.values() for e in events}
                
                with open(events_file, "r") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            event = MemoryEvent(**data)
                            event_time = datetime.fromisoformat(
                                event.timestamp.replace("Z", "+00:00")
                            )
                            
                            # Archive if older than cutoff and processed
                            if event_time < cutoff and event.id in processed_event_ids:
                                archived_events.append(data)
                            else:
                                remaining_events.append(line)
                        except (json.JSONDecodeError, ValueError, KeyError):
                            remaining_events.append(line)  # Keep malformed lines
                
                # Write archived events
                if archived_events:
                    archive_file = (
                        self.storage.archive_dir
                        / f"events_{datetime.now(timezone.utc).strftime('%Y-%m')}.jsonl"
                    )
                    with open(archive_file, "a") as f:
                        for event_data in archived_events:
                            json.dump(event_data, f, ensure_ascii=False)
                            f.write("\n")
                    
                    # Rewrite events.jsonl with remaining events
                    with open(events_file, "w") as f:
                        f.writelines(remaining_events)

        return digests_created

    def _archive_old_tasks(self, warm_days: int) -> int:
        """Archive completed tasks older than warm_days.

        Args:
            warm_days: Warm memory window in days

        Returns:
            Number of tasks archived
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=warm_days)
        cutoff_str = cutoff.isoformat()

        tasks = self.storage.read_tasks()
        active_tasks = []
        archived_tasks = []

        for task in tasks:
            if task.status.value == "completed":
                # Check if old enough to archive
                try:
                    updated_time = datetime.fromisoformat(
                        task.updated_at.replace("Z", "+00:00")
                    )
                    if updated_time < cutoff:
                        archived_tasks.append(task)
                        continue
                except (ValueError, AttributeError):
                    pass

            active_tasks.append(task)

        if archived_tasks:
            # Write archived tasks
            archive_file = (
                self.storage.archive_dir
                / f"tasks_completed_{datetime.now(timezone.utc).strftime('%Y-%m')}.json"
            )
            archive_data = [t.model_dump() for t in archived_tasks]

            # Append to archive (or create new)
            if archive_file.exists():
                with open(archive_file) as f:
                    existing = json.load(f)
                existing.extend(archive_data)
                archive_data = existing

            with open(archive_file, "w") as f:
                json.dump(archive_data, f, indent=2)

            # Update active tasks
            self.storage.write_tasks(active_tasks)

        return len(archived_tasks)

    def _update_context_md(self) -> None:
        """Dynamically generate context.md from context.json."""
        context = self.storage.read_context()
        context_md = self.storage.memory_dir / "context.md"

        lines = [
            "# Project Context",
            "",
            f"**Project:** {context.project_name or 'Unnamed'}",
            f"**Updated:** {context.updated_at}",
            "",
            "## Description",
            context.description or "*No description*",
            "",
            "## Architecture",
            context.architecture or "*No architecture documented*",
            "",
            "## Tech Stack",
        ]

        if context.tech_stack:
            for tech in context.tech_stack:
                lines.append(f"- {tech}")
        else:
            lines.append("*No tech stack specified*")

        lines.extend([
            "",
            "## Current Focus",
            context.current_focus or "*No current focus*",
            "",
            "## Key Files",
        ])

        if context.key_files:
            for file in context.key_files:
                lines.append(f"- `{file}`")
        else:
            lines.append("*No key files listed*")

        if context.notes:
            lines.extend([
                "",
                "## Notes",
                context.notes,
            ])

        lines.append("")
        lines.append("---")
        lines.append(f"*Auto-generated from context.json at {datetime.now(timezone.utc).isoformat()}*")

        context_md.write_text("\n".join(lines), encoding="utf-8")
