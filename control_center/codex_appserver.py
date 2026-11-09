"""Read-only Codex App Server client used by the local Control Center.

The Codex CLI owns authentication and upstream network access. This module only
starts ``codex app-server`` locally, performs account/rate-limit/usage reads, and
returns a small normalized snapshot. It never reads auth.json or sends mutating
App Server methods.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import json
import queue
import subprocess
import threading
from typing import Any


class CodexAppServerError(RuntimeError):
    """The local Codex App Server could not provide a read-only response."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _payload(result: Any, key: str) -> dict[str, Any]:
    result = _dict(result)
    nested = result.get(key)
    return _dict(nested) if isinstance(nested, dict) else result


def _safe_account(result: Any) -> dict[str, Any]:
    account = _payload(result, "account")
    # Deliberately omit email, account IDs, tokens, and raw response bodies.
    plan = account.get("planType") or account.get("plan") or account.get("plan_type")
    return {
        "authenticated": bool(account),
        "plan": plan if isinstance(plan, str) else None,
    }


def _safe_rate_limits(result: Any) -> list[dict[str, Any]]:
    data = _payload(result, "rateLimits")
    windows = data.get("rateLimitWindows") or data.get("windows") or data.get("limits")
    if not isinstance(windows, list):
        windows = []
    safe: list[dict[str, Any]] = []
    for window in windows:
        item = _dict(window)
        duration = item.get("windowDurationMins")
        used = item.get("usedPercent")
        reset = item.get("resetsAt")
        row: dict[str, Any] = {}
        if type(duration) is int:
            row["window_duration_mins"] = duration
        if isinstance(used, (int, float)) and not isinstance(used, bool):
            row["used_percent"] = used
            row["remaining_percent"] = max(0.0, min(100.0, 100.0 - float(used)))
        if type(reset) is int:
            row["resets_at"] = reset
        if row:
            safe.append(row)
    return safe


def _safe_usage(result: Any) -> dict[str, Any]:
    usage = _payload(result, "usage")
    safe: dict[str, Any] = {}
    for source, target in (
        ("lifetimeTokens", "lifetime_tokens"),
        ("peakDailyTokens", "peak_daily_tokens"),
        ("currentStreak", "current_streak"),
        ("longestTaskDuration", "longest_task_duration"),
    ):
        value = usage.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            safe[target] = value
    buckets = usage.get("dailyUsageBuckets")
    if isinstance(buckets, list):
        safe["daily_usage_buckets"] = [
            {key: item[key] for key in ("date", "tokens") if key in item}
            for item in buckets
            if isinstance(item, dict)
        ]
    return safe


def normalize_snapshot(account: Any, rate_limits: Any, usage: Any) -> dict[str, Any]:
    """Return safe, presentation-ready data without raw Codex responses."""
    return {
        "source": "Codex App Server stdio",
        "measured_at": _now(),
        "account": _safe_account(account),
        "rate_limits": _safe_rate_limits(rate_limits),
        "usage": _safe_usage(usage),
    }


class CodexAppServerClient:
    """Small synchronous JSON-lines client for the local Codex App Server."""

    def __init__(
        self,
        command: Sequence[str] = ("codex", "app-server"),
        timeout: float = 10.0,
        popen: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self.command = list(command)
        self.timeout = timeout
        self._popen = popen
        self._process: Any = None
        self._messages: queue.Queue[Any] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._next_id = 0

    def __enter__(self) -> "CodexAppServerClient":
        try:
            self._process = self._popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise CodexAppServerError(f"No se pudo iniciar Codex App Server: {exc}") from exc
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        try:
            self._request("initialize", {
                "clientInfo": {
                    "name": "swat_context_guardian",
                    "title": "SWAT Context Guardian",
                    "version": "0.4.0-dev",
                },
                "capabilities": {},
            })
            self._notify("initialized", {})
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _read_stdout(self) -> None:
        stdout = getattr(self._process, "stdout", None)
        if stdout is None:
            self._messages.put(CodexAppServerError("Codex App Server no expuso stdout"))
            return
        try:
            for line in stdout:
                if line.strip():
                    try:
                        self._messages.put(json.loads(line))
                    except json.JSONDecodeError:
                        self._messages.put(CodexAppServerError("Respuesta no JSON de Codex App Server"))
        finally:
            self._messages.put(None)

    def _send(self, message: dict[str, Any]) -> None:
        stdin = getattr(self._process, "stdin", None)
        if stdin is None:
            raise CodexAppServerError("Codex App Server no tiene stdin disponible")
        stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        stdin.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        self._next_id += 1
        request_id = self._next_id
        self._send({"method": method, "id": request_id, "params": params})
        while True:
            try:
                message = self._messages.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise CodexAppServerError(f"Timeout esperando {method}") from exc
            if message is None:
                raise CodexAppServerError("Codex App Server cerró la conexión")
            if isinstance(message, Exception):
                raise message
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                error = _dict(message["error"])
                raise CodexAppServerError(str(error.get("message") or f"Método rechazado: {method}"))
            return message.get("result")

    def read_snapshot(self) -> dict[str, Any]:
        account = self._request("account/read", {"refreshToken": False})
        rate_limits = self._request("account/rateLimits/read", {})
        usage = self._request("account/usage/read", {})
        return normalize_snapshot(account, rate_limits, usage)

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if getattr(process, "stdin", None) is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
