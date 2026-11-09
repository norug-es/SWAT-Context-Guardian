"""SWAT Context Guardian Control Center, v0.3.1.

Local dashboard. Read-only for Codex sessions. Writes only its own SQLite database
and explicit metadata checkpoints. No control of external agents, no transcript capture.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import sqlite3
import sys
import threading
import secrets
import time
from dataclasses import asdict, dataclass
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / 'static'
GUARDIAN = PROJECT_ROOT / 'scripts' / 'guardian.py'
spec = importlib.util.spec_from_file_location('swat_existing_guardian', GUARDIAN)
if spec is None or spec.loader is None:
    raise RuntimeError(f'Missing existing guardian module at {GUARDIAN}')
guardian = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guardian
spec.loader.exec_module(guardian)

logger = logging.getLogger('swat-guardian')
THRESHOLDS = (60, 70, 80, 90)
LABELS = {60: 'Aviso', 70: 'Checkpoint recomendado', 80: 'Revisar compactación', 90: 'Preparar relevo'}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def parsed_utc(value: Any) -> datetime | None:
    """Convert a timestamp to aware UTC for safe cross-file ordering."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        date = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        return (date.replace(tzinfo=timezone.utc) if date.tzinfo is None
                else date.astimezone(timezone.utc))
    except ValueError:
        return None


def timestamp_rank(value: Any) -> float:
    date = parsed_utc(value)
    return date.timestamp() if date else float('-inf')


def valid_local_origin(request: Request) -> None:
    """Prevent ordinary cross-origin browser POSTs to a loopback management API."""
    origin = request.headers.get('origin')
    if origin:
        allowed = {f'http://127.0.0.1:{request.app.state.settings.port}',
                   f'http://localhost:{request.app.state.settings.port}'}
        if origin not in allowed:
            raise HTTPException(403, 'Origin not allowed')
    fetch_site = request.headers.get('sec-fetch-site')
    if fetch_site and fetch_site not in ('same-origin', 'none'):
        raise HTTPException(403, 'Cross-origin requests disabled')
    if not secrets.compare_digest(request.headers.get('x-guardian-token', ''),
                                  request.app.state.csrf_token):
        raise HTTPException(403, 'Local action token required')


@dataclass
class Settings:
    codex_home: Path
    port: int = 8765
    interval: float = 5.0
    hours: float = 72.0
    limit: int = 60
    native_toasts: bool = False
    appserver_url: str | None = None
    appserver_token_file: Path | None = None
    demo: bool = False


class AlertsDatabase:
    def __init__(self, path: Path | str):
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute('''CREATE TABLE IF NOT EXISTS alerts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          at TEXT NOT NULL, session_id TEXT NOT NULL,
          project TEXT NOT NULL, percent REAL NOT NULL,
          tier INTEGER NOT NULL, source TEXT NOT NULL)''')
        self.conn.commit()
        if isinstance(path, Path):
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass

    def add(self, session_id: str, project: str, percent: float, tier: int, source: str) -> dict:
        now = utc_now()
        with self.lock:
            cur = self.conn.execute(
                'INSERT INTO alerts(at,session_id,project,percent,tier,source) VALUES(?,?,?,?,?,?)',
                (now, session_id, project, percent, tier, source))
            self.conn.commit()
            return {'id': cur.lastrowid, 'at': now, 'session_id': session_id,
                    'project': project, 'percent': percent, 'tier': tier,
                    'source': source}

    def recent(self, limit: int = 60) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                'SELECT id,at,session_id,project,percent,tier,source FROM alerts ORDER BY id DESC LIMIT ?',
                (min(250, max(1, int(limit))),)).fetchall()
        return [dict(zip(('id', 'at', 'session_id', 'project', 'percent', 'tier', 'source'), row)) for row in rows]

    def close(self) -> None:
        with self.lock:
            self.conn.close()


class NativeToast:
    """Optional winotify; failure does not affect monitoring or web UI."""
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.available = False
        if enabled and sys.platform == 'win32':
            try:
                from winotify import Notification  # noqa
                self.available = True
            except ImportError:
                logger.warning('winotify not installed: browser alerts remain available')

    async def emit(self, title: str, message: str) -> bool:
        if not self.available:
            return False
        def send() -> None:
            from winotify import Notification
            Notification(app_id='SWAT Context Guardian', title=title,
                         msg=message[:230]).show()
        try:
            await asyncio.to_thread(send)
            return True
        except Exception as exc:
            logger.warning('Toast could not be shown: %s', type(exc).__name__)
            return False


def extract_ws_usage(params: dict) -> tuple[int, int] | None:
    """Only trust explicit LAST usage. Never use cumulative totals as context occupancy."""
    if not isinstance(params, dict):
        return None
    usage = params.get('tokenUsage') or params.get('token_usage') or {}
    if not isinstance(usage, dict):
        return None
    last = usage.get('last') or usage.get('lastTokenUsage') or usage.get('last_token_usage')
    window = (params.get('modelContextWindow') or params.get('model_context_window')
              or usage.get('modelContextWindow') or usage.get('model_context_window'))
    if not isinstance(last, dict):
        return None
    active = last.get('totalTokens') if 'totalTokens' in last else last.get('total_tokens')
    if type(active) is int and type(window) is int and active >= 0 and window > 0:
        return active, window
    return None


class GuardianState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.home = settings.codex_home
        self.output = self.home / 'context-guardian'
        self.db = AlertsDatabase(':memory:' if settings.demo else self.output / 'control-center.sqlite3')
        self.toasts = NativeToast(settings.native_toasts)
        self.sessions: list[dict] = []
        self.live_threads: dict[str, dict] = {}
        self.appserver = {'configured': bool(settings.appserver_url), 'connected': False,
                          'url': settings.appserver_url, 'last_event': None,
                          'threads_listed': 0, 'error': None}
        self.marks: dict[str, int] = {}
        self.revisions: dict[str, tuple[tuple[int, int], Any]] = {}
        self.generation = 0
        self.started_at = utc_now()
        self.error: str | None = None
        self.tasks: list[asyncio.Task] = []
        self.lock = threading.RLock()

    def listed_sessions(self) -> list[dict]:
        """Exactly one row per logical Codex thread, including all JSONL source paths.

        The selected *measurement* is the latest measured_at, NEVER the highest
        percentage. The selected JSONL *path* is the most recently modified file.
        Neither a recent mtime nor a thread/list response proves an agent is active.
        """
        with self.lock:
            raw = [dict(s) for s in self.sessions]
            server = {k: dict(v) for k, v in self.live_threads.items()}
            connected = bool(self.appserver.get('connected'))

        grouped: dict[str, list[dict]] = {}
        for row in raw:
            sid = row.get('session_id') or row.get('session_file')
            if isinstance(sid, str) and sid:
                grouped.setdefault(sid, []).append(row)

        result: list[dict] = []
        now = datetime.now(timezone.utc)
        for sid in sorted(set(grouped) | set(server)):
            originals = grouped.get(sid, [])
            files = sorted(originals, key=lambda x: timestamp_rank(x.get('last_file_modified_at')),
                           reverse=True)
            newest_file = files[0] if files else {}
            measured = [f for f in files if f.get('percent_approx') is not None and
                        parsed_utc(f.get('measured_at'))]
            latest_measurement = (max(measured, key=lambda x: timestamp_rank(x.get('measured_at')))
                                  if measured else {})
            live = server.get(sid) or {}

            source_files = [
                {'session_file': f.get('session_file'),
                 'last_file_modified_at': f.get('last_file_modified_at'),
                 'file_size': f.get('file_size'),
                 'measured_at': f.get('measured_at'),
                 'percent_approx': f.get('percent_approx')}
                for f in files
            ]
            item = {
                'session_id': sid,
                'session_file': newest_file.get('session_file'),
                'source_file_count': len(source_files),
                'source_files': source_files,
                'project': newest_file.get('project') or latest_measurement.get('project')
                           or live.get('project'),
                'last_file_modified_at': newest_file.get('last_file_modified_at'),
                'active_tokens_approx': latest_measurement.get('active_tokens_approx'),
                'context_window': latest_measurement.get('context_window'),
                'percent_approx': latest_measurement.get('percent_approx'),
                'measured_at': latest_measurement.get('measured_at'),
                'source': 'JSONL + App Server' if files and live else
                          ('JSONL' if files else 'App Server'),
                'server_status': live.get('status'),
                'server_seen_at': live.get('seen_at'),
                'server_last_event_at': live.get('last_event_at'),
            }
            # Current WS token usage can override disk only when the connection is
            # actually alive. A stale disconnected status must never impersonate live.
            if (connected and live.get('active_tokens_approx') is not None
                    and timestamp_rank(live.get('usage_seen_at')) >=
                        timestamp_rank(item.get('measured_at'))):
                item.update(active_tokens_approx=live['active_tokens_approx'],
                            context_window=live.get('context_window'),
                            percent_approx=live.get('percent_approx'),
                            measured_at=live.get('usage_seen_at') or live.get('seen_at'))

            last_event = parsed_utc(live.get('last_event_at'))
            disk_modified = parsed_utc(item.get('last_file_modified_at'))
            activity_dates = [x for x in (last_event, disk_modified) if x is not None]
            last_activity = max(activity_dates) if activity_dates else None
            age = now - last_activity if last_activity else None
            server_fresh = parsed_utc(live.get('seen_at'))
            live_verified = (connected and live.get('status') == 'active'
                             and server_fresh is not None
                             and timedelta(0) <= now - server_fresh <= timedelta(seconds=60))
            # "recent" means evidence dated within 24 hours, not verified activity.
            recent = (age is not None and timedelta(0) <= age <= timedelta(hours=24))
            category = 'active' if live_verified else ('recent' if recent else 'historical')
            item.update(activity_category=category,
                        activity_label={'active': 'Activa verificada',
                                        'recent': 'Reciente (sin actividad verificada)',
                                        'historical': 'Histórica / sin actividad verificada'}[category],
                        active_verified=live_verified,
                        last_activity_at=last_activity.isoformat(timespec='seconds') if last_activity else None,
                        activity_basis=('App Server conectado' if live_verified else
                                        'Última modificación JSONL / evento' if last_activity else
                                        'Sin fecha de actividad comprobable'),
                        recently_modified=recent)
            result.append(item)

        order = {'active': 0, 'recent': 1, 'historical': 2}
        return sorted(result, key=lambda x: (
            order[x['activity_category']],
            -timestamp_rank(x.get('last_activity_at')),
            -(x.get('percent_approx') or 0)
        ))

    async def scan_once(self) -> list[dict]:
        """Incremental cache: never reparse unchanged large rollout files."""
        def collect() -> list[dict]:
            paths = guardian.discover(self.home, self.settings.limit, self.settings.hours)
            fresh: dict[str, tuple[tuple[int, int], Any]] = {}
            result: list[dict] = []
            now = time.time()
            for path in paths:
                key = str(path)
                try:
                    stat = path.stat()
                    sig = (stat.st_size, stat.st_mtime_ns)
                    cached = self.revisions.get(key)
                    snap = cached[1] if cached and cached[0] == sig else guardian.inspect_session(path)
                    fresh[key] = (sig, snap)
                    data = asdict(snap)
                    data['recently_modified'] = now - stat.st_mtime <= 180
                    data['last_file_modified_at'] = datetime.fromtimestamp(
                        stat.st_mtime, timezone.utc).isoformat(timespec='seconds')
                    data['file_size'] = stat.st_size
                    result.append(data)
                except (OSError, PermissionError) as exc:
                    logger.warning('Skipped inaccessible rollout: %s', type(exc).__name__)
            self.revisions = fresh
            return result

        session_dicts = await asyncio.to_thread(collect)
        with self.lock:
            self.sessions = session_dicts
            self.generation += 1
        await self.check_thresholds(self.listed_sessions())
        return session_dicts

    async def check_thresholds(self, sessions: list[dict]) -> None:
        """Only transitions AFTER initial observation produce notifications."""
        for item in sessions:
            pct = item.get('percent_approx')
            sid = item.get('session_id')
            if not sid or not isinstance(pct, (int, float)):
                continue
            level = max((t for t in THRESHOLDS if pct >= t), default=0)
            if sid not in self.marks:
                self.marks[sid] = level
                continue
            previous = self.marks[sid]
            self.marks[sid] = level
            if level <= previous or level == 0:
                continue
            record = self.db.add(sid, item.get('project') or 'Sin proyecto', float(pct), level,
                                 item.get('source') or 'unknown')
            self.generation += 1
            label = LABELS[level]
            title = f'Context Guardian · {level}% · {label}'
            message = f"{Path(item.get('project') or 'Sin proyecto').name}: {pct:.1f}% de contexto estimado."
            logger.info('%s | %s', title, message)
            if self.settings.native_toasts:
                await self.toasts.emit(title, message)

    async def watcher(self) -> None:
        while True:
            try:
                await self.scan_once()
                self.error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.error = f'{type(exc).__name__}: {exc}'[:150]
                logger.exception('Scan failed')
            await asyncio.sleep(self.settings.interval)

    def update_live(self, sid: str, *, observed_activity: bool = False, **values: Any) -> None:
        if not isinstance(sid, str) or not sid or len(sid) > 256:
            return
        with self.lock:
            current = self.live_threads.setdefault(sid, {})
            current.update(values)
            current['seen_at'] = utc_now()
            if observed_activity:
                current['last_event_at'] = current['seen_at']
                if values.get('active_tokens_approx') is not None:
                    current['usage_seen_at'] = current['seen_at']
            self.generation += 1

    async def appserver_monitor(self) -> None:
        """Optional protocol observer: initialize + thread/list. No resuming/controlling turns."""
        from websockets.asyncio.client import connect
        url = self.settings.appserver_url
        if not url:
            return
        if not (url.startswith('ws://127.0.0.1:') or url.startswith('ws://localhost:')):
            self.appserver['error'] = 'Only loopback WS endpoints are permitted'
            return
        delay = 2
        while True:
            try:
                headers = {}
                if self.settings.appserver_token_file:
                    token = self.settings.appserver_token_file.read_text(encoding='utf-8').strip()
                    if not token:
                        raise ValueError('App Server token file empty')
                    headers['Authorization'] = f'Bearer {token}'
                async with connect(url, additional_headers=headers, open_timeout=5,
                                   max_size=2 * 1024 * 1024, ping_interval=20) as ws:
                    self.appserver.update(connected=False, error=None, threads_listed=0)
                    delay = 2
                    await ws.send(json.dumps({
                        'method': 'initialize', 'id': 1,
                        'params': {'clientInfo': {'name': 'swat_context_guardian',
                                                  'title': 'SWAT Context Guardian', 'version': '0.3.1'},
                                   'capabilities': {'optOutNotificationMethods': [
                                       'item/agentMessage/delta', 'item/reasoning/textDelta',
                                       'item/reasoning/summaryTextDelta',
                                       'item/commandExecution/outputDelta',
                                       'turn/diff/updated', 'turn/plan/updated']}}}))
                    response = None
                    for _ in range(8):
                        candidate = json.loads(await asyncio.wait_for(ws.recv(), 10))
                        if candidate.get('id') == 1:
                            response = candidate
                            break
                    if response is None or response.get('error'):
                        raise RuntimeError('App Server initialization rejected')
                    await ws.send(json.dumps({'method': 'initialized', 'params': {}}))
                    # Reset snapshots from older connections. A previous active
                    # status/usage must not be treated as current after reconnect.
                    with self.lock:
                        self.live_threads.clear()
                    self.appserver.update(connected=True, error=None)
                    self.generation += 1
                    last_list = 0.0
                    while True:
                        if time.monotonic() - last_list > 20:
                            await ws.send(json.dumps({'method': 'thread/list', 'id': 2,
                                                      'params': {'limit': 100}}))
                            last_list = time.monotonic()
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=2)
                        except asyncio.TimeoutError:
                            continue
                        event = json.loads(raw)
                        if event.get('id') == 2:
                            if event.get('error'):
                                self.appserver['error'] = 'thread/list rejected (check Codex version)'
                                continue
                            threads = (event.get('result') or {}).get('data') or []
                            self.appserver['threads_listed'] = len(threads)
                            for entry in threads:
                                if not isinstance(entry, dict):
                                    continue
                                st = entry.get('status') or {}
                                self.update_live(entry.get('id', ''),
                                                 project=entry.get('cwd'),
                                                 status=st.get('type') if isinstance(st, dict) else str(st))
                            continue
                        method = event.get('method')
                        params = event.get('params') or {}
                        if not isinstance(params, dict):
                            continue
                        if method in ('thread/tokenUsage/updated', 'thread/status/changed',
                                      'thread/started', 'turn/started', 'turn/completed'):
                            sid = params.get('threadId') or (params.get('thread') or {}).get('id')
                            if method == 'thread/tokenUsage/updated':
                                usage = extract_ws_usage(params)
                                if usage:
                                    active, window = usage
                                    self.update_live(sid, observed_activity=True, active_tokens_approx=active,
                                                     context_window=window,
                                                     percent_approx=round(100 * active / window, 1))
                                else:
                                    self.update_live(sid, observed_activity=True)
                            elif method == 'thread/status/changed':
                                status = params.get('status') or {}
                                self.update_live(sid, observed_activity=True, status=status.get('type') if isinstance(status, dict) else str(status))
                            else:
                                self.update_live(sid, observed_activity=True)
                            self.appserver['last_event'] = utc_now()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.appserver['error'] = f'{type(exc).__name__}: connection or protocol unavailable'[:110]
                logger.warning('App Server offline: %s', type(exc).__name__)
            finally:
                self.appserver['connected'] = False
                self.generation += 1
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    def overview(self) -> dict:
        data = self.listed_sessions()
        paths = {s.get('project') for s in data if s.get('project')}
        measured = [s['percent_approx'] for s in data if s.get('percent_approx') is not None]
        current_measured = [s['percent_approx'] for s in data
                            if s.get('percent_approx') is not None
                            and s.get('activity_category') in ('active', 'recent')]
        return {
            'version': '0.3.1', 'mode': 'DEMO (simulado)' if self.settings.demo else 'LOCAL READ ONLY',
            'started_at': self.started_at, 'generation': self.generation,
            'scanned_at': utc_now(), 'session_count': len(data), 'project_count': len(paths),
            'max_percent': max(measured) if measured else None,
            'max_current_percent': max(current_measured) if current_measured else None,
            'sessions': data,
            'file_count': sum(s.get('source_file_count', 0) for s in data),
            'activity_counts': {category: sum(s['activity_category'] == category for s in data)
                                for category in ('active', 'recent', 'historical')},
            'appserver': dict(self.appserver),
            'notifications': {'native_enabled': self.settings.native_toasts,
                              'native_available': self.toasts.available},
            'codex_home': str(self.home), 'scan_error': self.error,
        }

    def checkpoints(self) -> list[dict]:
        folder = self.output / 'checkpoints'
        if not folder.is_dir():
            return []
        found = []
        for path in sorted(folder.glob('*.json'), reverse=True)[:50]:
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                found.append({'name': path.name, 'date': data.get('timestamp'),
                              'project': data.get('project'),
                              'session': (data.get('session') or {}).get('session_id')})
            except (OSError, ValueError):
                continue
        return found

    def open_session_folder(self, sid: str) -> dict:
        """Open only a known Codex session file's folder on Windows, on explicit click."""
        if self.settings.demo:
            raise ValueError('Opening folders disabled in demo mode')
        if sys.platform != 'win32':
            raise ValueError('Abrir carpeta solo está disponible en Windows; copia la ruta')
        item = next((s for s in self.listed_sessions() if s['session_id'] == sid), None)
        if not item or not item.get('session_file'):
            raise ValueError('No existe archivo local para esa sesión')
        path = Path(item['session_file']).resolve()
        sessions_dir = (self.home / 'sessions').resolve()
        if not path.is_relative_to(sessions_dir) or not path.is_file() or path.suffix != '.jsonl':
            raise ValueError('Archivo fuera del directorio Codex permitido')
        os.startfile(str(path.parent))  # type: ignore[attr-defined]
        return {'opened': True, 'folder': str(path.parent)}

    def create_checkpoint(self, sid: str) -> dict:
        if self.settings.demo:
            raise ValueError('Checkpoints disabled in demo mode')
        item = next((s for s in self.listed_sessions() if s['session_id'] == sid), None)
        if not item:
            raise ValueError('Session not found')
        project = item.get('project')
        if not project or not Path(project).is_dir():
            raise ValueError('Project directory not found; metadata checkpoint not created')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        path = self.output / 'checkpoints' / f'{stamp}-{sid[-12:]}.json'
        record = {
            'kind': 'context-guardian-checkpoint-v1', 'timestamp': utc_now(),
            'project': project, 'git': guardian.git_info(Path(project)),
            'session': {k: item.get(k) for k in ('session_id', 'session_file', 'project',
                                                       'active_tokens_approx', 'context_window',
                                                       'percent_approx', 'measured_at')},
            'operator_provided': {'summary': '', 'verified_decisions': '',
                                  'verified_evidence': '', 'pending': '',
                                  'next_step': '', 'safety_constraints': ''},
            'disclaimer': 'Metadata-only checkpoint. The conversation was not summarized or copied.'
        }
        guardian.safe_write_json(path, record)
        return {'name': path.name, 'path': str(path),
                'message': 'Checkpoint created (metadata only; fill decisions using the skill)'}


class CheckpointRequest(BaseModel):
    session_id: str


class OpenLocationRequest(BaseModel):
    session_id: str


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = app.state.guardian
        if settings.demo:
            state.sessions = demo_sessions()
        else:
            await state.scan_once()
            state.tasks.append(asyncio.create_task(state.watcher(), name='jsonl-scanner'))
            if settings.appserver_url:
                state.tasks.append(asyncio.create_task(state.appserver_monitor(), name='appserver-monitor'))
        try:
            yield
        finally:
            for task in state.tasks:
                task.cancel()
            if state.tasks:
                await asyncio.gather(*state.tasks, return_exceptions=True)
            state.db.close()

    app = FastAPI(title='SWAT Context Guardian Control Center', version='0.3.1', docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])
    app.state.settings = settings
    app.state.csrf_token = secrets.token_urlsafe(32)
    app.state.guardian = GuardianState(settings)

    @app.get('/')
    async def index():
        return FileResponse(STATIC / 'index.html')

    @app.get('/assets/guardian-banner.png')
    async def banner():
        return FileResponse(PROJECT_ROOT / 'assets' / 'banner-swat-context-guardian.png')

    @app.get('/api/health')
    async def health():
        return {'ok': True, 'version': '0.3.1', 'read_only': True}

    @app.get('/api/status')
    async def status():
        return {**app.state.guardian.overview(), 'local_action_token': app.state.csrf_token}

    @app.get('/api/alerts')
    async def alerts():
        return {'alerts': app.state.guardian.db.recent(75)}

    @app.get('/api/checkpoints')
    async def checkpoints():
        return {'checkpoints': app.state.guardian.checkpoints()}

    @app.post('/api/checkpoints')
    async def checkpoint(request: Request, body: CheckpointRequest):
        valid_local_origin(request)
        try:
            return await asyncio.to_thread(app.state.guardian.create_checkpoint, body.session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/sessions/open-folder')
    async def open_folder(request: Request, body: OpenLocationRequest):
        valid_local_origin(request)
        try:
            return await asyncio.to_thread(app.state.guardian.open_session_folder, body.session_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/notifications/test')
    async def test_notification(request: Request):
        valid_local_origin(request)
        notifier = app.state.guardian.toasts
        if not notifier.available:
            return JSONResponse({'sent': False,
                                 'message': 'Native popup unavailable. Enable --native-toasts and install winotify on Windows.'})
        success = await notifier.emit('SWAT Context Guardian', 'Notificación de prueba · Monitor en ejecución')
        return {'sent': success, 'message': 'Notificación enviada' if success else 'Windows notification failed'}

    return app


def demo_sessions() -> list[dict]:
    samples = [
        ('Dark-Intelligence-Gateway', 64.0, 165306),
        ('Dark-Intelligence-Gateway', 48.2, 124478),
        ('Dark-Intelligence-Gateway', 52.9, 136721),
        ('SWAT-Forense-Avatar', 47.6, 122886),
        ('SWAT-Forense-Avatar', 37.5, 96935),
        ('SWAT-Forense-Avatar', 25.2, 65000),
        ('SWAT-Kathon-Solana', None, None),
    ]
    return [{
        'session_id': f'demo-{i:03d}-session', 'session_file': None,
        'project': f'C:\\Dev\\SWAT\\{name}', 'context_window': 258400 if pct is not None else None,
        'active_tokens_approx': used, 'percent_approx': pct, 'measured_at': utc_now() if pct is not None else None,
        'recently_modified': i in (0, 3),
        'last_file_modified_at': utc_now() if i in (0, 3) else None,
        'file_size': None,
    } for i, (name, pct, used) in enumerate(samples)]


def main() -> None:
    parser = argparse.ArgumentParser(description='SWAT Context Guardian Control Center (localhost only)')
    parser.add_argument('--codex-home', type=Path,
                        default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')))
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--interval', type=float, default=5)
    parser.add_argument('--hours', type=float, default=72)
    parser.add_argument('--limit', type=int, default=60)
    parser.add_argument('--native-toasts', action='store_true', help='Enable optional Windows toast notifications')
    parser.add_argument('--appserver-url', default=os.environ.get('GUARDIAN_APP_SERVER_URL'))
    parser.add_argument('--appserver-token-file', type=Path,
                        default=Path(os.environ['GUARDIAN_APP_SERVER_TOKEN_FILE'])
                        if os.environ.get('GUARDIAN_APP_SERVER_TOKEN_FILE') else None)
    parser.add_argument('--demo', action='store_true', help='Explicitly simulated demo for UI preview')
    args = parser.parse_args()
    if not (1024 <= args.port <= 65535):
        parser.error('Port must be 1024-65535')
    if not (1 <= args.interval <= 3600 and 1 <= args.limit <= 1000 and args.hours > 0):
        parser.error('Invalid polling/limit/lookback values')
    if args.appserver_url and not (args.appserver_url.startswith('ws://127.0.0.1:') or
                                   args.appserver_url.startswith('ws://localhost:')):
        parser.error('App Server URL must be local ws://127.0.0.1:PORT')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    settings = Settings(codex_home=args.codex_home.expanduser(), port=args.port,
                        interval=args.interval, hours=args.hours, limit=args.limit,
                        native_toasts=args.native_toasts, appserver_url=args.appserver_url,
                        appserver_token_file=args.appserver_token_file, demo=args.demo)
    import uvicorn
    print(f'SWAT Context Guardian Control Center -> http://127.0.0.1:{args.port}')
    print('Codex sessions: READ ONLY. No compaction or session changes.')
    uvicorn.run(create_app(settings), host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
