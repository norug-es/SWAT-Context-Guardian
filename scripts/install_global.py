#!/usr/bin/env python3
"""Opt-in installer for global Codex skill. Dry-run by default."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import shutil

NAME = "swat-context-guardian"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the skill for all Codex projects")
    parser.add_argument("--apply", action="store_true", help="Actually copy files (default: preview)")
    parser.add_argument("--replace", action="store_true", help="Backup and replace existing skill")
    parser.add_argument("--destination", type=Path, help="Override for testing; omit for global")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent.parent
    target = (args.destination or (Path.home() / ".agents" / "skills" / NAME)).expanduser()
    if not (source / "SKILL.md").is_file():
        parser.error("SKILL.md missing next to installer")
    print(f"SOURCE={source}")
    print(f"TARGET={target}")
    print(f"EXISTS={target.exists()}")
    if not args.apply:
        print("DRY_RUN=YES; no files changed. Add --apply to install.")
        return 0
    backup = None
    if target.exists():
        if not args.replace:
            print("BLOCKED: existing skill found. Inspect first; use --replace for backup + replacement.")
            return 2
        backup = target.with_name(f"{target.name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        if backup.exists():
            print("BLOCKED: backup destination already exists")
            return 2
        target.rename(backup)
        print(f"BACKUP={backup}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        if backup and backup.exists():
            backup.rename(target)
        raise
    print(f"INSTALLED={target / 'SKILL.md'}")
    print("Restart Codex or open a fresh session to discover the global skill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
