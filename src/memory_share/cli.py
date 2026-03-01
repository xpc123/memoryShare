"""CLI tool for memory-share."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from .compaction import CompactionEngine
from .consistency import ConsistencyLayer
from .models import IDESource
from .scanner import ProjectScanner
from .storage import StorageEngine
from .sync import SyncEngine


def get_storage_engine(project_dir: Path | None = None) -> StorageEngine:
    """Get storage engine instance."""
    if project_dir is None:
        project_dir = Path.cwd()
    return StorageEngine(project_dir)


def get_sync_engine(storage: StorageEngine) -> SyncEngine:
    """Get sync engine instance."""
    consistency = ConsistencyLayer(storage)
    return SyncEngine(storage, consistency)


@click.group()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Project directory (defaults to current directory)",
)
@click.pass_context
def cli(ctx: click.Context, project_dir: Path | None):
    """Memory Share - Cross-IDE memory sharing system."""
    ctx.ensure_object(dict)
    ctx.obj["project_dir"] = project_dir or Path.cwd()


@cli.command()
@click.pass_context
def init(ctx: click.Context):
    """Initialize .memory/ directory and IDE configurations."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)
    storage.initialize()

    # Scan project
    scanner = ProjectScanner(project_dir)
    context = scanner.scan()
    storage.write_context(context)

    # Install Git hooks
    from .git_hooks import GitHooksManager
    sync_engine = get_sync_engine(storage)
    hooks_manager = GitHooksManager(project_dir, storage, sync_engine)
    hooks_installed = hooks_manager.install_hooks()

    # Install IDE rule files (using importlib.resources for package_data)
    try:
        from importlib import resources
        templates_pkg = "memory_share.templates"
    except ImportError:
        # Fallback for Python < 3.9
        templates_pkg = None
    
    def read_template(name: str) -> str:
        """Read template file from package_data."""
        if templates_pkg:
            try:
                return resources.read_text(templates_pkg, name, encoding="utf-8")
            except (ImportError, FileNotFoundError):
                pass
        # Fallback: try relative path (for development)
        fallback_path = Path(__file__).parent.parent.parent / "templates" / name
        if fallback_path.exists():
            return fallback_path.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Template {name} not found")

    # Cursor
    cursor_rules_dir = project_dir / ".cursor" / "rules"
    cursor_rules_dir.mkdir(parents=True, exist_ok=True)
    try:
        cursor_template_content = read_template("cursor_rules.mdc")
        cursor_rules_file = cursor_rules_dir / "memory-share.mdc"
        cursor_rules_file.write_text(cursor_template_content)
        click.echo("✓ Installed Cursor rules")
    except FileNotFoundError:
        click.echo("⚠ Cursor template not found", err=True)

    # Claude Code
    try:
        claude_template_content = read_template("claude_md.md")
        claude_file = project_dir / "CLAUDE.md"
        if claude_file.exists():
            # Append to existing file
            content = claude_file.read_text()
            if "Memory Share Integration" not in content:
                claude_file.write_text(
                    content + "\n\n" + claude_template_content
                )
                click.echo("✓ Updated CLAUDE.md")
        else:
            claude_file.write_text(claude_template_content)
            click.echo("✓ Created CLAUDE.md")
    except FileNotFoundError:
        click.echo("⚠ Claude template not found", err=True)

    # Copilot
    try:
        copilot_template_content = read_template("copilot_instructions.md")
        copilot_dir = project_dir / ".github"
        copilot_dir.mkdir(parents=True, exist_ok=True)
        copilot_file = copilot_dir / "copilot-instructions.md"
        # Append to existing file (like CLAUDE.md)
        if copilot_file.exists():
            content = copilot_file.read_text()
            if "Memory Share Integration" not in content:
                copilot_file.write_text(
                    content + "\n\n" + copilot_template_content
                )
                click.echo("✓ Updated Copilot instructions")
        else:
            copilot_file.write_text(copilot_template_content)
            click.echo("✓ Installed Copilot instructions")
    except FileNotFoundError:
        click.echo("⚠ Copilot template not found", err=True)

    # Auto-generate MCP config files
    project_dir_abs = str(project_dir.resolve())
    
    # Cursor MCP config
    cursor_mcp_dir = project_dir / ".cursor"
    cursor_mcp_dir.mkdir(exist_ok=True)
    cursor_mcp_file = cursor_mcp_dir / "mcp.json"
    cursor_config = {
        "mcpServers": {
            "memory-share": {
                "command": "fastmcp",
                "args": ["run", "memory_share.server:mcp"],
                "env": {
                    "MEMORY_PROJECT_DIR": project_dir_abs,
                    "MEMORY_IDE": "cursor"
                }
            }
        }
    }
    if cursor_mcp_file.exists():
        # Merge with existing config
        existing = json.loads(cursor_mcp_file.read_text())
        if "mcpServers" not in existing:
            existing["mcpServers"] = {}
        existing["mcpServers"]["memory-share"] = cursor_config["mcpServers"]["memory-share"]
        cursor_config = existing
    cursor_mcp_file.write_text(json.dumps(cursor_config, indent=2))
    click.echo("✓ Created/updated .cursor/mcp.json")
    
    # Claude Code MCP config (uses .mcp.json in project root)
    claude_mcp_file = project_dir / ".mcp.json"
    claude_config = {
        "mcpServers": {
            "memory-share": {
                "command": "fastmcp",
                "args": ["run", "memory_share.server:mcp"],
                "env": {
                    "MEMORY_PROJECT_DIR": project_dir_abs,
                    "MEMORY_IDE": "claude_code"
                }
            }
        }
    }
    if claude_mcp_file.exists():
        existing = json.loads(claude_mcp_file.read_text())
        if "mcpServers" not in existing:
            existing["mcpServers"] = {}
        existing["mcpServers"]["memory-share"] = claude_config["mcpServers"]["memory-share"]
        claude_config = existing
    claude_mcp_file.write_text(json.dumps(claude_config, indent=2))
    click.echo("✓ Created/updated .mcp.json")
    
    # GitHub Copilot MCP config (uses .vscode/mcp.json)
    vscode_mcp_dir = project_dir / ".vscode"
    vscode_mcp_dir.mkdir(exist_ok=True)
    vscode_mcp_file = vscode_mcp_dir / "mcp.json"
    copilot_config = {
        "mcpServers": {
            "memory-share": {
                "command": "fastmcp",
                "args": ["run", "memory_share.server:mcp"],
                "env": {
                    "MEMORY_PROJECT_DIR": project_dir_abs,
                    "MEMORY_IDE": "copilot"
                }
            }
        }
    }
    if vscode_mcp_file.exists():
        existing = json.loads(vscode_mcp_file.read_text())
        if "mcpServers" not in existing:
            existing["mcpServers"] = {}
        existing["mcpServers"]["memory-share"] = copilot_config["mcpServers"]["memory-share"]
        copilot_config = existing
    vscode_mcp_file.write_text(json.dumps(copilot_config, indent=2))
    click.echo("✓ Created/updated .vscode/mcp.json")

    # Update .gitignore
    gitignore = project_dir / ".gitignore"
    gitignore_content = ""
    if gitignore.exists():
        gitignore_content = gitignore.read_text()

    if ".memory/.lock" not in gitignore_content:
        gitignore_content += "\n# Memory Share\n.memory/.lock/\n.memory/context.md\n"
        gitignore.write_text(gitignore_content)
        click.echo("✓ Updated .gitignore")

    click.echo(f"\n✓ Initialized .memory/ in {project_dir}")
    click.echo(f"✓ Scanned project: {context.project_name}")
    if hooks_installed:
        click.echo("✓ Installed Git post-commit hook")
    else:
        click.echo("⚠ Git hooks not installed (not a git repository)")


@cli.command()
@click.pass_context
def status(ctx: click.Context):
    """Show memory health panel."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)

    if not storage.memory_dir.exists():
        click.echo("Error: .memory/ not initialized. Run 'memory-share init' first.")
        sys.exit(1)

    storage.initialize()

    # Read data
    events = storage.read_events_reverse(max_age_hours=48)
    tasks = storage.read_tasks()
    decisions = storage.read_decisions()
    digests = storage.read_digests()
    state = storage.read_state()
    context = storage.read_context()

    # Count active tasks
    active_tasks = [t for t in tasks if t.status.value in ["pending", "in_progress"]]

    # Calculate sizes
    events_file = storage.memory_dir / "events.jsonl"
    events_size = events_file.stat().st_size if events_file.exists() else 0

    # Format output
    click.echo(f"📊 Memory Status — {context.project_name or project_dir.name}")
    click.echo("─" * 50)
    click.echo(f"  Hot:   {len(events)} events (48h) | {len(active_tasks)} active tasks | {len(decisions)} decisions")
    click.echo(f"  Warm:  {len(digests)} digests (30d)")
    click.echo(f"  Size:  {events_size / 1024:.1f}KB total")
    click.echo("─" * 50)
    click.echo(f"  Sessions: {len(state.sessions)} active")
    click.echo(f"  Version:  v{state.version}")

    # Warnings
    if events_size > 200 * 1024:  # > 200KB
        click.echo(f"  ⚠️  events.jsonl has {len(events)}+ raw events → suggest: memory-share compact")


@cli.command()
@click.pass_context
def log(ctx: click.Context):
    """Show recent event log."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)
    storage.initialize()

    events = storage.read_events_reverse(max_age_hours=48, limit=20)

    for event in events:
        click.echo(f"[{event.timestamp[:19]}] [{event.source.value}] {event.summary}")


@cli.command()
@click.argument("keyword")
@click.pass_context
def search(ctx: click.Context, keyword: str):
    """Search memories by keyword."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)
    storage.initialize()

    events = storage.read_events_reverse(max_age_hours=48 * 7)
    results = [
        e for e in events
        if keyword.lower() in (e.summary.lower() + " " + e.content.lower())
    ]

    click.echo(f"Found {len(results)} results:")
    for event in results[:20]:
        click.echo(f"  - [{event.source.value}] {event.summary}")


@cli.command()
@click.pass_context
def tasks(ctx: click.Context):
    """List all tasks."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)
    storage.initialize()

    tasks = storage.read_tasks()

    for task in tasks:
        status_icon = {
            "pending": "○",
            "in_progress": "◐",
            "completed": "✓",
            "cancelled": "✗",
        }.get(task.status.value, "○")

        click.echo(f"{status_icon} [{task.status.value}] {task.title}")
        if task.description:
            click.echo(f"    {task.description[:80]}")


@cli.command()
@click.pass_context
def context(ctx: click.Context):
    """Show project context."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)
    storage.initialize()

    context = storage.read_context()

    # Generate and display context.md
    from .compaction import CompactionEngine
    sync_engine = get_sync_engine(storage)
    compactor = CompactionEngine(storage, sync_engine)
    compactor._update_context_md()

    context_md = storage.memory_dir / "context.md"
    if context_md.exists():
        click.echo(context_md.read_text())


@cli.command()
@click.option("--both", is_flag=True, help="Pull and push")
@click.option("--pull", is_flag=True, help="Pull only")
@click.option("--push", is_flag=True, help="Push only")
@click.option("--summary", help="Summary for push")
@click.pass_context
def sync(ctx: click.Context, both: bool, pull: bool, push: bool, summary: str | None):
    """Sync memory (pull/push/both)."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)
    storage.initialize()

    sync_engine = get_sync_engine(storage)

    # Determine direction
    if both:
        direction = "both"
    elif pull:
        direction = "pull"
    elif push:
        direction = "push"
    else:
        direction = "both"

    # Register session
    session_id = sync_engine.register_session(IDESource.USER)

    result = sync_engine.sync(
        session_id=session_id,
        direction=direction,
        push_summary=summary or "Manual sync",
    )

    if result["pulled_events"]:
        click.echo(f"Pulled {len(result['pulled_events'])} events")
        for event in result["pulled_events"][:5]:
            click.echo(f"  - [{event['source']}] {event['summary']}")

    if result["pushed_version"]:
        click.echo(f"Pushed: version {result['pushed_version']}")

    if result["error"]:
        click.echo(f"Error: {result['error']}", err=True)


@cli.command()
@click.pass_context
def compact(ctx: click.Context):
    """Compact memory: archive old events, create digests."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)
    storage.initialize()

    sync_engine = get_sync_engine(storage)
    compactor = CompactionEngine(storage, sync_engine)

    stats = compactor.compact()

    click.echo("Compaction complete:")
    click.echo(f"  - Created {stats['digests_created']} digests")
    click.echo(f"  - Archived {stats['tasks_archived']} tasks")
    click.echo(f"  - Cleaned {stats['sessions_cleaned']} stale sessions")


@cli.command()
@click.pass_context
def doctor(ctx: click.Context):
    """Check system health and configuration."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)

    click.echo("🔍 Memory Share Doctor")
    click.echo("─" * 50)

    # Check .memory/ exists
    if not storage.memory_dir.exists():
        click.echo("❌ .memory/ not initialized")
        click.echo("   Run: memory-share init")
        return

    click.echo("✓ .memory/ directory exists")

    # Check consistency
    storage.initialize()
    consistency = ConsistencyLayer(storage)
    is_consistent, error = consistency.check_and_fix_consistency()
    if is_consistent:
        click.echo("✓ Data consistency OK")
    else:
        click.echo(f"⚠ {error}")

    # Check lock
    lock_dir = storage.lock_dir
    if lock_dir.exists():
        click.echo("⚠ Lock directory exists (may indicate stale lock)")
    else:
        click.echo("✓ No stale locks")

    # Check Git hooks
    git_hooks = project_dir / ".git" / "hooks" / "post-commit"
    if git_hooks.exists():
        click.echo("✓ Git post-commit hook installed")
    else:
        click.echo("⚠ Git post-commit hook not installed")


@cli.command()
@click.option("--check", is_flag=True, help="Check only, don't migrate")
@click.option("--from", "from_version", type=int, help="Source version")
@click.option("--to", "to_version", type=int, help="Target version")
@click.pass_context
def migrate(ctx: click.Context, check: bool, from_version: int | None, to_version: int | None):
    """Migrate schema versions."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)
    storage.initialize()

    state = storage.read_state()
    current_version = state.schema_version

    if check:
        click.echo(f"Current schema version: {current_version}")
        click.echo("Target version: 1")
        return

    if from_version is None or to_version is None:
        click.echo("Error: --from and --to required for migration", err=True)
        return

    # TODO: Implement actual migration logic
    click.echo(f"Migration from {from_version} to {to_version} not yet implemented")


@cli.command()
@click.pass_context
def merge_fix(ctx: click.Context):
    """Fix Git merge conflicts in memory files."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)
    storage.initialize()

    # TODO: Implement merge conflict resolution
    click.echo("Merge conflict resolution not yet implemented")


@cli.command()
@click.pass_context
def export(ctx: click.Context):
    """Export memories as readable Markdown."""
    project_dir = ctx.obj["project_dir"]
    storage = get_storage_engine(project_dir)
    storage.initialize()

    # TODO: Implement export with security scanning
    click.echo("Export not yet implemented")


if __name__ == "__main__":
    cli()
