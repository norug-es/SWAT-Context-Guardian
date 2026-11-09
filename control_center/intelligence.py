"""Read-only, bounded Codex telemetry analytics for SWAT Context Guardian.

No transcripts, prompts, API tokens or auth files are retained. Counter deltas are
derived from Codex JSONL; unlike billing reports, they are not invoice-grade.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import json
import os
import shutil
import subprocess
import threading
import time

MAX_FILES = 600
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SCAN_BYTES = 128 * 1024 * 1024
MAX_EVENTS = 120_000
CACHE_SECONDS = 60


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _number(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or value > 10**15:
        return None
    return int(value)


def _counters(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    input_tokens = _number(value.get("input_tokens"))
    output_tokens = _number(value.get("output_tokens"))
    cached = _number(value.get("cached_input_tokens"))
    total = _number(value.get("total_tokens"))
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    if total is None:
        return None
    return {"tokens": total, "input_tokens": input_tokens or 0,
            "output_tokens": output_tokens or 0, "cached_tokens": cached or 0}


def _empty_day(date: str) -> dict[str, Any]:
    return {"date": date, "tokens": 0, "input_tokens": 0, "output_tokens": 0,
            "cached_tokens": 0, "events": 0, "sessions": 0, "cost_usd": None}


def _safename(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    # Project path is deliberately reduced to its basename; never send secrets.
    return value.replace("\\", "/").rstrip("/").split("/")[-1][:90] or fallback


def _source_files(home: Path, since: datetime) -> tuple[list[tuple[Path, os.stat_result]], int]:
    root = home / "sessions"
    if not root.is_dir():
        return [], 0
    entries: list[tuple[Path, os.stat_result]] = []
    missing = 0
    # Bounded discovery. Neither follow directory nor file symlinks.
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
        for name in names:
            if not (name.startswith("rollout-") and name.endswith(".jsonl")):
                continue
            path = Path(directory) / name
            try:
                if path.is_symlink():
                    continue
                stat = path.stat()
                if datetime.fromtimestamp(stat.st_mtime, timezone.utc) < since:
                    continue
                entries.append((path, stat))
            except OSError:
                missing += 1
    entries.sort(key=lambda e: e[1].st_mtime_ns, reverse=True)
    if len(entries) > MAX_FILES:
        missing += len(entries) - MAX_FILES
    return entries[:MAX_FILES], missing


def _read_file(path: Path, stat: os.stat_result) -> tuple[str, str, list[tuple[datetime, dict[str, int], str]], int, bool]:
    """Extract only session metadata and token counters. Other event lines are ignored."""
    session_id = path.stem
    project = "Sin proyecto"
    model = "Sin identificar"
    events: list[tuple[datetime, dict[str, int], str]] = []
    budget = min(stat.st_size, MAX_FILE_BYTES)
    truncated = stat.st_size > MAX_FILE_BYTES
    with path.open("rb") as fh:
        if truncated:
            fh.seek(stat.st_size - budget)
            fh.readline()  # Discard the incomplete leading line.
        for line in fh:
            if not (b'"session_meta"' in line or b'"token_count"' in line or
                    b'"turn_context"' in line):
                continue
            if len(line) > 256 * 1024:
                truncated = True
                continue
            try:
                item = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            if kind == "session_meta":
                identity = payload.get("id")
                if isinstance(identity, str) and 0 < len(identity) <= 160:
                    session_id = identity
                project = _safename(payload.get("cwd"), project)
            elif kind == "turn_context":
                model = _safename(payload.get("model"), model)
            elif kind == "event_msg" and payload.get("type") == "token_count":
                at = _date(item.get("timestamp"))
                info = payload.get("info")
                if not at or not isinstance(info, dict):
                    continue
                model = _safename(info.get("model"), model)
                total = _counters(info.get("total_token_usage"))
                if total:
                    events.append((at, total, model))
    return session_id, project, events, budget, truncated


def aggregate_codex(home: Path, days: int = 90) -> dict[str, Any]:
    """Aggregate counter increases once per logical session, within an explicit lookback."""
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")
    now = datetime.now(timezone.utc)
    start_date = now.date() - timedelta(days=days - 1)
    # One extra day catches files modified at the window edge.
    since = datetime.combine(start_date, datetime.min.time(), timezone.utc)
    paths, skipped = _source_files(home, since)
    scanned_bytes = 0
    truncated_files = 0
    errors = 0
    processed_files = 0
    event_total = 0
    # Dedup by session/timestamp/counter, even across multiple rollout paths.
    sessions: dict[str, list[tuple[datetime, dict[str, int], str, str]]] = defaultdict(list)
    session_projects: dict[str, str] = {}
    for path, stat in paths:
        if scanned_bytes >= MAX_SCAN_BYTES:
            skipped += 1
            continue
        try:
            sid, project, records, used, truncated = _read_file(path, stat)
        except (OSError, ValueError):
            errors += 1
            continue
        scanned_bytes += used
        processed_files += 1
        truncated_files += int(truncated)
        if project != "Sin proyecto":
            session_projects[sid] = project
        available = max(0, MAX_EVENTS - event_total)
        if len(records) > available:
            skipped += 1
        records = records[:available]
        event_total += len(records)
        for at, counters, model in records:
            sessions[sid].append((at, counters, model, project))
    day_map: dict[str, dict[str, Any]] = {}
    day_sessions: dict[str, set[str]] = defaultdict(set)
    hour_map: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: {"tokens": 0, "events": 0})
    models: dict[str, dict[str, Any]] = {}
    projects: dict[str, dict[str, Any]] = {}
    observed_sessions: set[str] = set()
    for sid, records in sessions.items():
        seen: set[tuple[str, int, int, int, int]] = set()
        previous: dict[str, int] | None = None
        for at, counters, model, raw_project in sorted(records, key=lambda x: x[0]):
            identity = (at.isoformat(), counters["tokens"], counters["input_tokens"],
                        counters["output_tokens"], counters["cached_tokens"])
            if identity in seen:
                continue
            seen.add(identity)
            # Reset or discontinuity: do not assume the new total is fresh billable usage.
            if previous is None:
                delta = dict(counters)
            elif counters["tokens"] < previous["tokens"]:
                delta = {key: 0 for key in counters}
            else:
                delta = {key: max(0, counters[key] - previous[key]) for key in counters}
            previous = counters
            date = at.date()
            if date < start_date or date > now.date() or not delta["tokens"]:
                continue
            ds = date.isoformat()
            day = day_map.setdefault(ds, _empty_day(ds))
            for key in ("tokens", "input_tokens", "output_tokens", "cached_tokens"):
                day[key] += delta[key]
            day["events"] += 1
            day_sessions[ds].add(sid)
            hour = hour_map[(at.weekday(), at.hour)]
            hour["tokens"] += delta["tokens"]
            hour["events"] += 1
            observed_sessions.add(sid)
            m = models.setdefault(model, {"name": model, "tokens": 0, "events": 0})
            m["tokens"] += delta["tokens"]
            m["events"] += 1
            project = session_projects.get(sid) or raw_project
            p = projects.setdefault(project, {"name": project, "tokens": 0, "sessions": set()})
            p["tokens"] += delta["tokens"]
            p["sessions"].add(sid)
    dates = [(start_date + timedelta(days=i)).isoformat() for i in range(days)]
    daily = [day_map.get(d, _empty_day(d)) for d in dates]
    for row in daily:
        row["sessions"] = len(day_sessions.get(row["date"], ()))
    hour_rows = [{"weekday": d, "hour": h, **hour_map[(d, h)]}
                 for d in range(7) for h in range(24)]
    projects_safe = [{"name": x["name"], "tokens": x["tokens"], "sessions": len(x["sessions"])}
                     for x in projects.values()]
    total = sum(x["tokens"] for x in daily)
    coverage = {"files_scanned": processed_files,
                "files_skipped": skipped, "file_errors": errors,
                "truncated_files": truncated_files, "bytes_read_approx": scanned_bytes,
                "partial": bool(skipped or errors or truncated_files),
                "timezone": "UTC", "cost_accuracy": "No se calcula coste desde JSONL"}
    return {
        "source": "Codex JSONL local (estimación; no facturación)",
        "mode": "LOCAL READ ONLY", "generated_at": now.isoformat(timespec="seconds"),
        "days": days, "coverage": coverage,
        "summary": {"tokens": total, "sessions": len(observed_sessions),
                    "projects": len(projects_safe), "events": sum(d["events"] for d in daily),
                    "cost_usd": None},
        "daily": daily, "calendar": daily,
        "hours": hour_rows,
        "models": sorted(models.values(), key=lambda x: -x["tokens"])[:24],
        "projects": sorted(projects_safe, key=lambda x: -x["tokens"])[:24],
    }


def demo_analytics(days: int = 90) -> dict[str, Any]:
    """Deterministic synthetic metrics, visibly and repeatedly labeled as a demo."""
    today = datetime.now(timezone.utc).date()
    daily = []
    for i in range(days):
        date = today - timedelta(days=days - 1 - i)
        tokens = ((i * 37 + 19) % 14 + 1) * 16000 if i % 9 != 0 else 0
        daily.append({"date": date.isoformat(), "tokens": tokens,
                      "input_tokens": int(tokens * .75), "output_tokens": int(tokens * .25),
                      "cached_tokens": int(tokens * .33), "events": tokens // 4000,
                      "sessions": (i % 5 + 1) if tokens else 0, "cost_usd": None})
    total = sum(x["tokens"] for x in daily)
    hours = [{"weekday": d, "hour": h, "tokens": (d + 1) * (h % 9 + 1) * 3000
              if 7 <= h <= 22 else 0, "events": (h % 6) if 7 <= h <= 22 else 0}
             for d in range(7) for h in range(24)]
    return {"source": "DEMO SIMULADA — no son datos reales", "mode": "DEMO (simulado)",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "days": days, "coverage": {"files_scanned": 0, "files_skipped": 0,
               "file_errors": 0, "truncated_files": 0, "partial": False,
               "timezone": "UTC", "cost_accuracy": "Datos inventados de demostración"},
            "summary": {"tokens": total, "sessions": days * 2, "projects": 3,
                        "events": sum(d["events"] for d in daily), "cost_usd": None},
            "daily": daily, "calendar": daily, "hours": hours,
            "models": [{"name": "gpt-6 (DEMO)", "tokens": int(total * .65), "events": 100},
                       {"name": "gpt-5.6 (DEMO)", "tokens": total - int(total * .65), "events": 40}],
            "projects": [{"name": "SWAT · DEMO", "tokens": int(total * .55), "sessions": 15},
                         {"name": "Guardian · DEMO", "tokens": total - int(total * .55), "sessions": 8}]}


class IntelligenceService:
    """Cache only sanitized aggregate data; never persist raw conversation events."""
    def __init__(self, home: Path, demo: bool = False):
        self.home = home
        self.demo = demo
        self._cache: dict[int, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def snapshot(self, days: int = 90) -> dict[str, Any]:
        if not 1 <= days <= 365:
            raise ValueError("days must be 1..365")
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(days)
            if cached and now - cached[0] < CACHE_SECONDS:
                return cached[1]
        result = demo_analytics(days) if self.demo else aggregate_codex(self.home, days)
        with self._lock:
            self._cache[days] = (time.monotonic(), result)
        return result

    def ccusage_report(self) -> dict[str, Any]:
        """Optional local CLI adapter. Never invokes npx or downloads executable code."""
        if self.demo:
            return {"available": False, "source": "DEMO (simulado)",
                    "message": "ccusage no se ejecuta en modo demo", "daily": []}
        binary = shutil.which("ccusage")
        if not binary:
            return {"available": False, "source": "ccusage local",
                    "message": "CLI ccusage no instalada o fuera de PATH", "daily": []}
        try:
            process = subprocess.run([binary, "daily", "--by-agent", "--json"],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25,
                     text=True, encoding="utf-8", errors="replace", check=False)
        except (OSError, subprocess.TimeoutExpired):
            return {"available": False, "source": "ccusage local",
                    "message": "ccusage no respondió dentro del límite", "daily": []}
        if process.returncode != 0 or len(process.stdout) > 2_000_000:
            return {"available": False, "source": "ccusage local",
                    "message": "No hay informe JSON válido disponible", "daily": []}
        try:
            payload = json.loads(process.stdout)
        except ValueError:
            return {"available": False, "source": "ccusage local",
                    "message": "La versión instalada no produjo JSON válido", "daily": []}
        # Current unified schema: {"daily": [{"period":"YYYY-MM-DD",
        # "agents":[...], "totalTokens":N, "totalCost":X}], "totals":{...}}.
        # Older versions may emit "date" instead of "period".
        collection: list[Any] = []
        if isinstance(payload, list):
            collection = payload
        elif isinstance(payload, dict):
            for key in ("daily", "data", "days"):
                if isinstance(payload.get(key), list):
                    collection = payload[key]
                    break
        rows: list[dict[str, Any]] = []
        agent_totals: dict[str, dict[str, Any]] = {}
        for raw in collection:
            if not isinstance(raw, dict):
                continue
            day = raw.get("date") or raw.get("period")
            if not isinstance(day, str) or len(day) != 10:
                continue
            try:
                date.fromisoformat(day)
            except ValueError:
                continue
            tokens = _number(raw.get("totalTokens", raw.get("total_tokens")))
            cost_value = raw.get("totalCost", raw.get("costUSD", raw.get("cost")))
            cost = (round(float(cost_value), 6)
                    if isinstance(cost_value, (int, float)) and not isinstance(cost_value, bool)
                    and 0 <= cost_value < 10**10 else None)
            if tokens is None and cost is None:
                continue
            rows.append({"date": day, "tokens": tokens, "cost_usd": cost})
            for agent in raw.get("agents", []) if isinstance(raw.get("agents"), list) else []:
                if not isinstance(agent, dict):
                    continue
                name = _safename(agent.get("agent"), "Desconocido")
                entry = agent_totals.setdefault(name, {"name": name, "tokens": 0,
                                                        "cost_usd": None})
                entry["tokens"] += _number(agent.get("totalTokens")) or 0
                item_cost = agent.get("totalCost")
                if isinstance(item_cost, (int, float)) and not isinstance(item_cost, bool) and 0 <= item_cost < 10**10:
                    entry["cost_usd"] = round((entry["cost_usd"] or 0) + float(item_cost), 6)
        unpriced = []
        if isinstance(payload, dict) and isinstance(payload.get("totals"), dict):
            maybe = payload["totals"].get("unpricedModels")
            if isinstance(maybe, list):
                unpriced = [_safename(x, "Sin nombre") for x in maybe if isinstance(x, str)][:20]
        return {"available": True, "source": "ccusage CLI local",
                "message": "Fuente independiente: NO sumar con Codex JSONL",
                "daily": sorted(rows, key=lambda r: r["date"])[-365:],
                "agents": sorted(agent_totals.values(), key=lambda x: -x["tokens"]),
                "unpriced_models": unpriced,
                "rows": len(rows)}
