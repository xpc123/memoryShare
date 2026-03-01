"""Project scanner for initial context generation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import ProjectContext


class ProjectScanner:
    """Scanner for analyzing project structure and generating initial context."""

    def __init__(self, project_dir: Path):
        """Initialize scanner.

        Args:
            project_dir: Project root directory
        """
        self.project_dir = Path(project_dir).resolve()

    def scan(self) -> ProjectContext:
        """Scan project and generate initial context.

        Returns:
            ProjectContext with scanned information
        """
        context = ProjectContext()

        # 1. Analyze directory structure
        context.project_name = self.project_dir.name
        context.description = self._read_description()
        context.tech_stack = self._detect_tech_stack()
        context.key_files = self._find_key_files()

        # 2. Read git log (if available)
        git_info = self._read_git_log()
        if git_info:
            context.notes = f"Recent git activity: {git_info}"

        return context

    def _read_description(self) -> str:
        """Read project description from README or similar files."""
        readme_files = ["README.md", "README.rst", "README.txt", "README"]
        for readme_name in readme_files:
            readme_path = self.project_dir / readme_name
            if readme_path.exists():
                try:
                    content = readme_path.read_text(encoding="utf-8", errors="ignore")
                    # Extract first paragraph
                    lines = content.split("\n")
                    desc_lines = []
                    for line in lines[:10]:  # First 10 lines
                        line = line.strip()
                        if line and not line.startswith("#"):
                            desc_lines.append(line)
                        if len(desc_lines) >= 3:
                            break
                    return " ".join(desc_lines[:3])
                except Exception:
                    pass

        return ""

    def _detect_tech_stack(self) -> list[str]:
        """Detect technology stack from project files."""
        tech_stack = []

        # Check for common files
        if (self.project_dir / "package.json").exists():
            tech_stack.append("Node.js")
        if (self.project_dir / "requirements.txt").exists() or (
            self.project_dir / "pyproject.toml"
        ).exists():
            tech_stack.append("Python")
        if (self.project_dir / "Cargo.toml").exists():
            tech_stack.append("Rust")
        if (self.project_dir / "go.mod").exists():
            tech_stack.append("Go")
        if (self.project_dir / "pom.xml").exists():
            tech_stack.append("Java")
        if (self.project_dir / "Gemfile").exists():
            tech_stack.append("Ruby")

        # Check for frameworks
        if (self.project_dir / "package.json").exists():
            try:
                import json
                pkg = json.loads((self.project_dir / "package.json").read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "react" in deps:
                    tech_stack.append("React")
                if "vue" in deps:
                    tech_stack.append("Vue")
                if "express" in deps:
                    tech_stack.append("Express")
            except Exception:
                pass

        if (self.project_dir / "requirements.txt").exists():
            try:
                req = (self.project_dir / "requirements.txt").read_text()
                if "django" in req.lower():
                    tech_stack.append("Django")
                if "flask" in req.lower():
                    tech_stack.append("Flask")
                if "fastapi" in req.lower():
                    tech_stack.append("FastAPI")
            except Exception:
                pass

        return tech_stack

    def _find_key_files(self) -> list[str]:
        """Find key files in project."""
        key_files = []

        # Common entry points
        entry_points = [
            "main.py",
            "app.py",
            "index.js",
            "index.ts",
            "src/main.rs",
            "main.go",
        ]

        for entry in entry_points:
            if (self.project_dir / entry).exists():
                key_files.append(entry)

        # Config files
        config_files = [
            "pyproject.toml",
            "package.json",
            "Cargo.toml",
            "go.mod",
        ]

        for config in config_files:
            if (self.project_dir / config).exists():
                key_files.append(config)

        return key_files[:10]  # Limit to 10

    def _read_git_log(self) -> str:
        """Read recent git log entries.

        Returns:
            Summary of recent commits
        """
        import subprocess

        try:
            result = subprocess.run(
                ["git", "log", "-10", "--oneline"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")[:5]
                return "; ".join(lines)
        except Exception:
            pass

        return ""
