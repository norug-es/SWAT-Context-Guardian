#!/usr/bin/env python3
"""SWAT Context Guardian. Passive Codex rollout monitor + deliberate handoff helpers.

Python 3.11+. stdlib only. Never sends data to the network or invokes compaction.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "0.3.1"
THRESHOLDS = (60, 70, 80, 90)
MAX_TAIL_BYTES = 4 * 1024 * 1024
ACTIONS = {
    60: "AVISO",
    70: "PREPARAR_CHECKPOINT",
    80: "REVISAR_COMPACTACION_NATIVA",
    90: "RECOMENDAR_RELEVO",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def codex_home(args: argparse.Namespace) -> Path:
    return Path(args.codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def guardian_home(args: argparse.Namespace) -> Path:
    return codex_home(args) / "context-guardian"


def parse_event(line: bytes) -> dict[str, Any] | None:
    try:
        obj = json.loads(line)
    except (ValueError, UnicodeError):
        return None
    return obj if isinstance(obj, dict) else None


def update_meta(event: dict[str, Any], current: dict[str, Any]) -> None:
    if event.get("type") != "session_meta":
        return
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        current["project"] = cwd
    session_id = payload.get("id")
    if isinstance(session_id, str) and session_id:
        current["session_id"] = session_id


def extract_measurement(event: dict[str, Any]) -> tuple[int, int] | None:
    """Only last model-call usage, never cumulative total_token_usage.

    This percentage is *approximate*. Codex can use a different usable window,
    prefill or asynchronous compaction; its internal number is authoritative.
    """
    if event.get("type") != "event_msg":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    usage = info.get("last_token_usage")
    if not isinstance(usage, dict):
        return None
    active = usage.get("total_tokens")
    window = info.get("model_context_window")
    if type(active) is not int or type(window) is not int:
        return None
    if active < 0 or window <= 0:
        return None
    return active, window


@dataclass
class Snapshot:
    session_file: str
    session_id: str
    project: str | None = None
    active_tokens_approx: int | None = None
    context_window: int | None = None
    percent_approx: float | None = None
    measured_at: str | None = None


def new_snapshot(path: Path) -> Snapshot:
    return Snapshot(session_file=str(path), session_id=path.stem)


def apply_event(event: dict[str, Any], snapshot: Snapshot) -> bool:
    meta: dict[str, Any] = {}
    update_meta(event, meta)
    if meta.get("project"):
        snapshot.project = meta["project"]
    if meta.get("session_id"):
        snapshot.session_id = meta["session_id"]
    usage = extract_measurement(event)
    if usage is None:
        return False
    active, window = usage
    snapshot.active_tokens_approx = active
    snapshot.context_window = window
    snapshot.percent_approx = round(100 * active / window, 1)
    timestamp = event.get("timestamp")
    snapshot.measured_at = timestamp if isinstance(timestamp, str) else utc_now()
    return True


def inspect_session(path: Path, tail_bytes: int = MAX_TAIL_BYTES) -> Snapshot:
    snapshot = new_snapshot(path)
    with path.open("rb") as f:
        # Only read session_meta from the start. Do not parse or store prompt text.
        for _ in range(4):
            event = parse_event(f.readline(256 * 1024))
            if event:
                apply_event(event, snapshot)
                if event.get("type") == "session_meta":
                    break
        size = f.seek(0, 2)
        start = max(0, size - tail_bytes)
        f.seek(start)
        if start:
            f.readline()  # discard partial first line
        for line in f:
            # Most entries are unrelated to token usage; parse but never retain text.
            if len(line) > 2 * 1024 * 1024:
                continue
            if b'"token_count"' not in line and b'"session_meta"' not in line:
                continue
            event = parse_event(line)
            if event:
                apply_event(event, snapshot)
    return snapshot


def discover(home: Path, max_sessions: int = 12, hours: float = 72) -> list[Path]:
    sessions_dir = home / "sessions"
    if not sessions_dir.is_dir():
        return []
    cutoff = time.time() - hours * 3600
    paths: list[tuple[float, Path]] = []
    for p in sessions_dir.rglob("rollout-*.jsonl"):
        try:
            stat = p.stat()
            if p.is_file() and stat.st_mtime >= cutoff:
                paths.append((stat.st_mtime, p))
        except OSError:
            continue
    paths.sort(key=lambda pair: pair[0], reverse=True)
    return [p for _, p in paths[:max_sessions]]


def snapshots(home: Path, max_sessions: int, hours: float) -> list[Snapshot]:
    found: list[Snapshot] = []
    for path in discover(home, max_sessions, hours):
        try:
            found.append(inspect_session(path))
        except (OSError, PermissionError) as exc:
            print(f"WARN unable to inspect {path.name}: {exc}", file=sys.stderr)
    return found


def tier(percent: float | None) -> int:
    if percent is None:
        return 0
    return max((threshold for threshold in THRESHOLDS if percent >= threshold), default=0)


def display(snapshot: Snapshot) -> str:
    value = "N/A" if snapshot.percent_approx is None else f"{snapshot.percent_approx:.1f}%"
    project = snapshot.project or "unknown-project"
    return f"{value:>7}  {snapshot.session_id}  {project}"


def command_status(args: argparse.Namespace) -> int:
    found = snapshots(codex_home(args), args.limit, args.hours)
    if args.json:
        print(json.dumps([asdict(s) for s in found], ensure_ascii=False, indent=2))
        return 0
    if not found:
        print("No recent Codex rollout sessions found. Check CODEX_HOME and CLI usage.")
        return 0
    for s in found:
        print(display(s))
    print("Percentages are estimates from last_token_usage, not Codex's internal compaction meter.")
    return 0


def safe_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite: {path}")
    created = False
    try:
        with path.open("x", encoding="utf-8") as out:
            created = True
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.write("\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise


def append_alert(home: Path, snapshot: Snapshot, level: int) -> None:
    folder = home / "context-guardian"
    folder.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": utc_now(),
        "session_id": snapshot.session_id,
        "project": snapshot.project,
        "percent_approx": snapshot.percent_approx,
        "tier": level,
        "action": ACTIONS[level],
        "measurement": "last_token_usage.total_tokens/model_context_window",
        "read_only": True,
    }
    with (folder / "alerts.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[ALERTA {level}%] {display(snapshot)} -> {ACTIONS[level]}", flush=True)


def command_watch(args: argparse.Namespace) -> int:
    home = codex_home(args)
    print("Context Guardian: passive, read-only. No automatic compaction or process controls.")
    last_tier: dict[str, int] = {}
    last_updated: dict[str, tuple[int, int]] = {}
    while True:
        for path in discover(home, args.limit, args.hours):
            try:
                stat = path.stat()
                sig = (stat.st_size, stat.st_mtime_ns)
                if last_updated.get(str(path)) == sig:
                    continue
                last_updated[str(path)] = sig
                snap = inspect_session(path)
            except (OSError, PermissionError) as exc:
                print(f"WARN {path.name}: {exc}", file=sys.stderr)
                continue
            key = str(path)
            new_tier = tier(snap.percent_approx)
            old_tier = last_tier.get(key, 0)
            if new_tier > old_tier and new_tier:
                append_alert(home, snap, new_tier)
            if old_tier >= 70 and new_tier < 60:
                print(f"[CAMBIO] {snap.session_id}: contexto estimado reducido o modelo cambiado; verificar.")
            last_tier[key] = new_tier
        if args.once:
            return 0
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nGuardian stopped")
            return 0


def git_info(path: Path) -> dict[str, Any]:
    def command(*parts: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "--no-optional-locks", "-C", str(path), *parts],
                capture_output=True, text=True, timeout=4, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    status = command("status", "--porcelain")
    return {
        "repository_root": command("rev-parse", "--show-toplevel"),
        "branch": command("symbolic-ref", "--short", "HEAD"),
        "head": command("rev-parse", "HEAD"),
        "dirty": (bool(status) if status is not None else None),
        "untracked_files_checked": True if status is not None else None,
    }


def select_snapshot(args: argparse.Namespace) -> Snapshot | None:
    existing = snapshots(codex_home(args), args.limit, args.hours)
    if args.session:
        matched = [s for s in existing if s.session_id == args.session or Path(s.session_file).stem == args.session]
        return matched[0] if matched else None
    target = Path(args.project).expanduser().resolve() if args.project else Path.cwd().resolve()
    matches = [s for s in existing if s.project and Path(s.project).resolve() == target]
    return matches[0] if matches else None


def command_checkpoint(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve() if args.project else Path.cwd().resolve()
    if not project.exists() or not project.is_dir():
        print("ERROR: project is not a directory", file=sys.stderr)
        return 2
    snap = select_snapshot(args)
    if args.session and snap is None:
        print("ERROR: specified session was not found within lookback; no checkpoint created", file=sys.stderr)
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = snap.session_id[-12:] if snap else "manual"
    path = guardian_home(args) / "checkpoints" / f"{stamp}-{suffix}.json"
    record = {
        "kind": "context-guardian-checkpoint-v1",
        "timestamp": utc_now(),
        "project": str(project),
        "git": git_info(project),
        "session": asdict(snap) if snap else None,
        "operator_provided": {
            "summary": args.summary or "",
            "verified_decisions": args.decisions or "",
            "verified_evidence": args.evidence or "",
            "pending": args.pending or "",
            "next_step": args.next_step or "",
            "safety_constraints": args.safety or "",
        },
        "disclaimer": "Local metadata and explicitly provided text only. No transcript mining. Review for sensitive data before sharing.",
    }
    try:
        safe_write_json(path, record)
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"CHECKPOINT={path}")
    if not any(record["operator_provided"].values()):
        print("NOTE: metadata-only; use the skill to add a verified semantic handoff separately.")
    return 0


def command_handoff(args: argparse.Namespace) -> int:
    path = Path(args.checkpoint).expanduser().resolve()
    if not path.is_file():
        print("ERROR: checkpoint not found", file=sys.stderr)
        return 2
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if record.get("kind") != "context-guardian-checkpoint-v1":
        print("ERROR: unknown checkpoint schema", file=sys.stderr)
        return 2
    user = record.get("operator_provided") or {}
    git = record.get("git") or {}
    sess = record.get("session") or {}
    sections = [
        "# Relevo de contexto — SWAT Context Guardian",
        "",
        "> Documento generado a partir de metadatos locales y campos proporcionados expresamente. No equivale a una validación técnica independiente.",
        "",
        f"- Fecha UTC: {record.get('timestamp', 'unknown')}",
        f"- Proyecto: `{record.get('project')}`",
        f"- Rama observada: `{git.get('branch') or 'sin verificar'}`",
        f"- HEAD observado: `{git.get('head') or 'sin verificar'}`",
        f"- Cambios locales detectados: `{git.get('dirty')}`",
        f"- Sesión Codex: `{sess.get('session_id') or 'sin verificar'}`",
        f"- Ocupación aproximada: `{sess.get('percent_approx')}`",
        "",
    ]
    labels = (
        ("Resumen", "summary"), ("Decisiones confirmadas", "verified_decisions"),
        ("Evidencias confirmadas", "verified_evidence"),
        ("Pendientes", "pending"), ("Siguiente paso", "next_step"),
        ("Restricciones de seguridad", "safety_constraints"),
    )
    for label, key in labels:
        sections += [f"## {label}", "", user.get(key) or "SIN REGISTRAR — revisar manualmente.", ""]
    sections += [
        "## Instrucciones para la próxima sesión", "",
        "1. Revalidar rama, HEAD, árbol de trabajo y evidencias antes de actuar.",
        "2. No tratar decisiones no verificadas como aprobaciones.",
        "3. No ejecutar migraciones, despliegues, comandos destructivos o modificaciones de seguridad sin autorización.",
        "4. No inferir que el relevo fue automático ni que el contexto completo fue preservado.",
        "5. Revisar y retirar secretos antes de adjuntar este documento a un chat externo.", "",
    ]
    result = "\n".join(sections)
    out = Path(args.output).expanduser() if args.output else path.with_suffix(".md")
    if out.exists() and not args.overwrite:
        print(f"ERROR: already exists: {out} (use --overwrite after review)", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.overwrite:
        out.write_text(result, encoding="utf-8")
    else:
        with out.open("x", encoding="utf-8") as handle:
            handle.write(result)
    print(f"HANDOFF={out}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    home = codex_home(args)
    skill = Path.home() / ".agents" / "skills" / "swat-context-guardian" / "SKILL.md"
    codex_bin = shutil.which("codex")
    version = "not found"
    if codex_bin:
        try:
            proc = subprocess.run([codex_bin, "--version"], capture_output=True, text=True, timeout=5)
            version = (proc.stdout or proc.stderr).strip() or "unknown"
        except (OSError, subprocess.TimeoutExpired):
            version = "unable to query"
    print(f"SWAT_CONTEXT_GUARDIAN={VERSION}")
    print(f"PYTHON={sys.version.split()[0]}")
    print(f"CODEX_VERSION={version}")
    print(f"CODEX_HOME={home}")
    print(f"SESSIONS_PRESENT={(home / 'sessions').is_dir()}")
    print(f"GLOBAL_SKILL_PRESENT={skill.is_file()}")
    print(f"CONFIG_PRESENT={(home / 'config.toml').is_file()}")
    print(f"RECENT_SESSIONS={len(discover(home, args.limit, args.hours))}")
    print("MODE=PASSIVE_READ_ONLY")
    print("AUTO_COMPACT_BY_GUARDIAN=DISABLED")
    print("To configure native compaction, review references/COMPACTACION.md and your Codex build.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SWAT Context Guardian: observability + safe context handoff")
    parser.add_argument("--codex-home", help="Override CODEX_HOME")
    parser.add_argument("--limit", type=int, default=12, help="Max recently modified sessions (default 12)")
    parser.add_argument("--hours", type=float, default=72, help="Lookback hours (default 72)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check Codex paths without modifying anything")
    status = sub.add_parser("status", help="Show recent token usage estimates")
    status.add_argument("--json", action="store_true")
    watch = sub.add_parser("watch", help="Continuously poll recent sessions, log threshold crossings")
    watch.add_argument("--interval", type=float, default=10)
    watch.add_argument("--once", action="store_true", help="One poll only")
    checkpoint = sub.add_parser("checkpoint", help="Save explicit metadata + supplied decisions, no transcript")
    checkpoint.add_argument("--project")
    checkpoint.add_argument("--session", help="Explicit session ID from status")
    checkpoint.add_argument("--summary")
    checkpoint.add_argument("--decisions")
    checkpoint.add_argument("--evidence")
    checkpoint.add_argument("--pending")
    checkpoint.add_argument("--next-step")
    checkpoint.add_argument("--safety")
    handoff = sub.add_parser("handoff", help="Render checkpoint as reusable Markdown handoff")
    handoff.add_argument("--checkpoint", required=True)
    handoff.add_argument("--output")
    handoff.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.limit < 1 or args.hours <= 0:
        parser.error("--limit must be >= 1 and --hours must be positive")
    if args.command == "watch" and args.interval < 1:
        parser.error("--interval must be >= 1")
    handlers = {
        "doctor": command_doctor,
        "status": command_status,
        "watch": command_watch,
        "checkpoint": command_checkpoint,
        "handoff": command_handoff,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
