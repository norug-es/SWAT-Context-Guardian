#!/usr/bin/env python3
"""Preview or explicitly enable Codex native post-turn compaction.

Never overwrites existing settings silently. Python 3.11+. No network calls.
"""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path

KEY = "model_post_turn_compact_threshold_percent"


def main() -> int:
    p = argparse.ArgumentParser(description="Codex native compaction setting — preview first")
    p.add_argument("--codex-home", type=Path)
    p.add_argument("--percent", type=int, default=80)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--acknowledge-compatibility", action="store_true",
                   help="Confirm you verified this option in your installed Codex version")
    args = p.parse_args()
    if not 1 <= args.percent <= 100:
        p.error("percent must be between 1 and 100")
    home = args.codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    config = home / "config.toml"
    original_bytes = config.read_bytes() if config.exists() else b""
    try:
        original = original_bytes.decode("utf-8")
        parsed = tomllib.loads(original)
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        print(f"BLOCKED: existing config.toml invalid UTF-8/TOML: {exc}")
        return 2
    if KEY in parsed:
        print(f"CONFIG={config}")
        print(f"EXISTING={KEY}={parsed[KEY]} — no modification performed")
        return 0
    newline = "\r\n" if b"\r\n" in original_bytes else "\n"
    new_text = f"{KEY} = {args.percent}{newline}{newline}" + original
    tomllib.loads(new_text)
    print(f"CONFIG={config}")
    print(f"PROPOSED={KEY} = {args.percent}")
    print("CAUTION: the option is version-dependent; existing auto-compaction settings also apply.")
    if not args.apply:
        print("DRY_RUN=YES; no files changed. Add --apply --acknowledge-compatibility after verification.")
        return 0
    if not args.acknowledge_compatibility:
        print("BLOCKED: explicitly acknowledge installed-version compatibility.")
        return 2
    home.mkdir(parents=True, exist_ok=True)
    backup = None
    if config.exists():
        backup = config.with_name(f"config.toml.bak-context-guardian-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        if backup.exists():
            print("BLOCKED: backup already exists")
            return 2
        shutil.copy2(config, backup)
        print(f"BACKUP={backup}")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=str(home), prefix=".context-guardian-config-",
                                         suffix=".tmp", delete=False) as f:
            temp_path = Path(f.name)
            f.write(new_text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        if config.exists():
            shutil.copymode(config, temp_path)
        os.replace(temp_path, config)
    except OSError as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        print(f"ERROR: {exc}; original config was not replaced")
        return 1
    print(f"UPDATED={config}")
    print("Restart Codex and verify post-turn compaction; setting alone is not proof it ran.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
