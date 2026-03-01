#!/usr/bin/env python3
"""Verify package configuration before building."""

import sys
from pathlib import Path

def check_files():
    """Check that all required files exist."""
    required = [
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "MANIFEST.in",
        "src/memory_share/__init__.py",
        "src/memory_share/cli.py",
        "src/memory_share/server.py",
    ]
    
    templates = [
        "src/memory_share/templates/cursor_rules.mdc",
        "src/memory_share/templates/claude_md.md",
        "src/memory_share/templates/copilot_instructions.md",
    ]
    
    missing = []
    for f in required + templates:
        if not Path(f).exists():
            missing.append(f)
    
    if missing:
        print("❌ Missing files:")
        for f in missing:
            print(f"   - {f}")
        return False
    
    print("✅ All required files present")
    return True

def check_pyproject():
    """Check pyproject.toml configuration."""
    try:
        import tomli
    except ImportError:
        try:
            import tomllib
        except ImportError:
            print("⚠️  Cannot parse pyproject.toml (need tomli or Python 3.11+)")
            return True
    
    try:
        with open("pyproject.toml", "rb") as f:
            if "tomli" in sys.modules:
                config = tomli.load(f)
            else:
                import tomllib
                config = tomllib.load(f)
        
        # Check package-data
        package_data = config.get("tool", {}).get("setuptools", {}).get("package-data", {})
        if "memory_share" in package_data:
            templates = package_data["memory_share"]
            if "templates/*" in templates:
                print("✅ Templates included in package-data")
            else:
                print("⚠️  Templates not in package-data")
        else:
            print("⚠️  package-data not configured")
        
        # Check scripts
        scripts = config.get("project", {}).get("scripts", {})
        if "memory-share" in scripts:
            print("✅ CLI script configured")
        else:
            print("⚠️  CLI script not configured")
        
        return True
    except Exception as e:
        print(f"⚠️  Error checking pyproject.toml: {e}")
        return True

def check_templates():
    """Check template files exist and can be read."""
    templates = [
        "src/memory_share/templates/cursor_rules.mdc",
        "src/memory_share/templates/claude_md.md",
        "src/memory_share/templates/copilot_instructions.md",
    ]
    
    all_ok = True
    for t_path in templates:
        path = Path(t_path)
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                if len(content) > 0:
                    print(f"✅ Template {path.name} exists and readable")
                else:
                    print(f"⚠️  Template {path.name} is empty")
                    all_ok = False
            except Exception as e:
                print(f"❌ Cannot read template {path.name}: {e}")
                all_ok = False
        else:
            print(f"❌ Template {path.name} not found at {t_path}")
            all_ok = False
    
    return all_ok

if __name__ == "__main__":
    print("🔍 Verifying package configuration...\n")
    
    all_ok = True
    all_ok &= check_files()
    print()
    all_ok &= check_pyproject()
    print()
    all_ok &= check_templates()
    
    print()
    if all_ok:
        print("✅ Package configuration looks good!")
        print("\nNext steps:")
        print("  1. python -m build")
        print("  2. twine check dist/*")
        print("  3. twine upload dist/* (or --repository testpypi)")
    else:
        print("❌ Some issues found. Please fix before building.")
        sys.exit(1)
