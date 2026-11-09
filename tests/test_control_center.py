"""Control Center integration tests. No real Codex or network service required."""
from __future__ import annotations

import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from control_center.server import Settings, create_app, GuardianState, extract_ws_usage
from control_center.codex_appserver import CodexAppServerClient


def event(total: int, window: int = 200):
    return {'timestamp': '2026-11-07T20:00:00Z', 'type': 'event_msg',
            'payload': {'type': 'token_count', 'info': {
                'last_token_usage': {'total_tokens': total},
                'total_token_usage': {'total_tokens': 10000000},
                'model_context_window': window}}}


def rollout(home: Path, project: Path, total: int):
    folder = home / 'sessions' / '2026' / '11' / '08'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'rollout-test-aaa.jsonl'
    lines = [
        {'type': 'session_meta', 'payload': {'id': 'session-aaa', 'cwd': str(project)}},
        {'type': 'response_item', 'payload': {'content': 'SECRET_SHOULD_NEVER_PERSIST'}},
        event(total)]
    path.write_text(''.join(json.dumps(x) + '\n' for x in lines))
    return path


class ControlCenterTests(unittest.TestCase):
    def test_codex_appserver_stdio_snapshot_is_normalized(self):
        responses = [
            {'id': 1, 'result': {'userAgent': 'mock-codex'}},
            {'id': 2, 'result': {'account': {'email': 'private@example.test', 'planType': 'pro'}}},
            {'id': 3, 'result': {'rateLimits': {'rateLimitWindows': [
                {'windowDurationMins': 300, 'usedPercent': 25, 'resetsAt': 123}
            ]}}},
            {'id': 4, 'result': {'usage': {
                'lifetimeTokens': 1000,
                'dailyUsageBuckets': [{'date': '2026-11-09', 'tokens': 100}],
            }}},
        ]

        class FakeProcess:
            def __init__(self):
                self.stdin = io.StringIO()
                self.stdout = io.StringIO('\n'.join(json.dumps(x) for x in responses) + '\n')

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        with CodexAppServerClient(popen=lambda *args, **kwargs: FakeProcess()) as client:
            snapshot = client.read_snapshot()

        self.assertEqual(snapshot['account'], {'authenticated': True, 'plan': 'pro'})
        self.assertEqual(snapshot['rate_limits'][0]['remaining_percent'], 75.0)
        self.assertEqual(snapshot['usage']['lifetime_tokens'], 1000)
        self.assertNotIn('private@example.test', json.dumps(snapshot))

    def test_codex_account_endpoint_is_read_only_demo(self):
        with tempfile.TemporaryDirectory() as td:
            with TestClient(create_app(Settings(Path(td), demo=True))) as c:
                response = c.get('/api/codex/account')
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['ok'])
                self.assertEqual(response.json()['source'], 'DEMO (simulado)')

    def test_web_status_and_docs_in_demo_mode(self):
        with tempfile.TemporaryDirectory() as td:
            s = Settings(Path(td) / '.codex', demo=True)
            with TestClient(create_app(s)) as c:
                health = c.get('/api/health')
                self.assertEqual(health.status_code, 200)
                self.assertTrue(health.json()['read_only'])
                status = c.get('/api/status').json()
                self.assertEqual(status['session_count'], 7)
                self.assertEqual(status['mode'], 'DEMO (simulado)')
                self.assertEqual(c.get('/').status_code, 200)
                self.assertIn('Control Center', c.get('/').text)
                self.assertFalse((Path(td) / '.codex').exists(), 'Demo must not create Codex files')
                self.assertEqual(c.get('/api/alerts').json()['alerts'], [])

    def test_csrf_and_external_host_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            with TestClient(create_app(Settings(Path(td), demo=True))) as c:
                payload = {'session_id': 'demo-000-session'}
                self.assertEqual(c.post('/api/checkpoints', json=payload).status_code, 403)
                token = c.get('/api/status').json()['local_action_token']
                self.assertEqual(c.post('/api/checkpoints', json=payload,
                             headers={'X-Guardian-Token': token, 'Origin': 'https://evil.example'}).status_code, 403)
                self.assertEqual(c.post('/api/checkpoints', json=payload,
                             headers={'X-Guardian-Token': token,
                                      'Sec-Fetch-Site': 'cross-site'}).status_code, 403)
                self.assertEqual(c.get('/api/status', headers={'host': 'evil.example'}).status_code, 400)
                self.assertEqual(c.post('/api/checkpoints', json=payload,
                             headers={'X-Guardian-Token': token}).status_code, 400)

    def test_threshold_alert_only_on_crossing_and_no_transcript(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / '.codex'; project = Path(td) / 'project'; project.mkdir()
            path = rollout(home, project, 115)
            state = GuardianState(Settings(home, limit=10, hours=100))
            asyncio.run(state.scan_once())
            self.assertEqual(len(state.db.recent()), 0)
            with path.open('a') as f:
                f.write(json.dumps(event(141)) + '\n')
            asyncio.run(state.scan_once())
            self.assertEqual(state.db.recent()[0]['tier'], 70)
            asyncio.run(state.scan_once())
            self.assertEqual(len(state.db.recent()), 1)
            with path.open('a') as f:
                f.write(json.dumps(event(25)) + '\n')
            asyncio.run(state.scan_once())
            with path.open('a') as f:
                f.write(json.dumps(event(182)) + '\n')
            asyncio.run(state.scan_once())
            self.assertEqual(state.db.recent()[0]['tier'], 90)
            checkpoint = state.create_checkpoint('session-aaa')
            content = Path(checkpoint['path']).read_text()
            self.assertNotIn('SECRET_SHOULD_NEVER_PERSIST', content)
            self.assertNotIn('SECRET_SHOULD_NEVER_PERSIST',
                             (home / 'context-guardian' / 'control-center.sqlite3').read_bytes().decode('utf-8', 'ignore'))
            state.db.close()

    def test_websocket_usage_distinguishes_last_from_total(self):
        self.assertEqual(extract_ws_usage({'tokenUsage': {
            'last': {'totalTokens': 125}, 'total': {'totalTokens': 999999},
            'modelContextWindow': 500}}), (125, 500))
        self.assertIsNone(extract_ws_usage({'tokenUsage': {
            'total': {'totalTokens': 999999}, 'modelContextWindow': 500}}))
        self.assertIsNone(extract_ws_usage({'tokenUsage': {'last': {'totalTokens': 99}}}))

    def test_appserver_initialize_and_thread_list_mock(self):
        from websockets.asyncio.server import serve
        async def run():
            with tempfile.TemporaryDirectory() as td:
                seen = []
                async def handler(ws):
                    init = json.loads(await ws.recv()); seen.append(init['method'])
                    self.assertEqual(init['method'], 'initialize')
                    await ws.send(json.dumps({'id': 1, 'result': {'userAgent': 'mock'}}))
                    ready = json.loads(await ws.recv()); seen.append(ready['method'])
                    req = json.loads(await ws.recv()); seen.append(req['method'])
                    await ws.send(json.dumps({'id': 2, 'result': {'data': [
                        {'id': 'mock-thread', 'cwd': str(Path(td) / 'workspace'),
                         'status': {'type': 'idle'}}], 'nextCursor': None}}))
                    await ws.send(json.dumps({'method': 'thread/tokenUsage/updated',
                                              'params': {'threadId': 'mock-thread',
                                                         'tokenUsage': {'last': {'totalTokens': 500},
                                                                        'modelContextWindow': 1000}}}))
                    await asyncio.sleep(2)
                async with serve(handler, '127.0.0.1', 0) as server:
                    port = server.sockets[0].getsockname()[1]
                    state = GuardianState(Settings(Path(td) / '.codex',
                                      appserver_url=f'ws://127.0.0.1:{port}'))
                    task = asyncio.create_task(state.appserver_monitor())
                    for _ in range(80):
                        if state.live_threads.get('mock-thread', {}).get('percent_approx') == 50:
                            break
                        await asyncio.sleep(.05)
                    self.assertEqual(state.live_threads['mock-thread']['percent_approx'], 50)
                    self.assertEqual(seen, ['initialize', 'initialized', 'thread/list'])
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    state.db.close()
        asyncio.run(run())

    def test_duplicate_rollout_files_dedup_latest_measured_not_maximum(self):
        """Repeated thread IDs count once, and older 64% cannot mask newer 37%."""
        import os
        import time
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / '.codex'
            project = Path(td) / 'SWAT'
            project.mkdir()
            d = home / 'sessions' / '2026' / '11' / '08'
            d.mkdir(parents=True)
            sid = 'same-codex-thread'
            older = d / 'rollout-older.jsonl'
            newer = d / 'rollout-newer.jsonl'
            def make(path, pct, stamp):
                entries = [
                    {'type': 'session_meta', 'payload': {'id': sid, 'cwd': str(project)}},
                    {'type': 'response_item', 'payload': {'content': 'SECRET_SHOULD_NOT_APPEAR'}},
                    {'timestamp': stamp, 'type': 'event_msg', 'payload': {'type': 'token_count',
                        'info': {'last_token_usage': {'total_tokens': pct},
                                 'model_context_window': 100}}},
                ]
                path.write_text('\n'.join(json.dumps(e) for e in entries) + '\n', encoding='utf-8')
            make(older, 64, '2026-11-07T10:00:00Z')
            make(newer, 37, '2026-11-08T01:00:00Z')
            os.utime(older, (time.time()-7000, time.time()-7000))
            state = GuardianState(Settings(home, limit=20, hours=48))
            asyncio.run(state.scan_once())
            observed = state.overview()
            self.assertEqual(observed['session_count'], 1)
            self.assertEqual(observed['file_count'], 2)
            self.assertEqual(observed['max_percent'], 37.0)
            item = observed['sessions'][0]
            self.assertEqual(item['session_id'], sid)
            self.assertEqual(item['source_file_count'], 2)
            self.assertEqual(item['percent_approx'], 37)
            self.assertEqual(item['session_file'], str(newer))
            self.assertEqual({x['percent_approx'] for x in item['source_files']}, {64.0, 37.0})
            self.assertEqual(item['activity_category'], 'recent')
            self.assertFalse(item['active_verified'])
            self.assertNotIn('SECRET_SHOULD_NOT_APPEAR', json.dumps(observed))
            state.db.close()

    def test_active_only_when_appserver_connected_and_fresh(self):
        from datetime import timedelta, datetime, timezone
        with tempfile.TemporaryDirectory() as td:
            state = GuardianState(Settings(Path(td) / '.codex'))
            state.update_live('session-1', project=str(Path(td)), status='active')
            self.assertEqual(state.listed_sessions()[0]['activity_category'], 'historical')
            state.appserver['connected'] = True
            self.assertEqual(state.listed_sessions()[0]['activity_category'], 'active')
            state.update_live('session-1', observed_activity=True, status='idle')
            self.assertEqual(state.listed_sessions()[0]['activity_category'], 'recent')
            state.update_live('session-1', status='active')
            state.live_threads['session-1']['seen_at'] = (
                datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
            self.assertNotEqual(state.listed_sessions()[0]['activity_category'], 'active')
            state.db.close()

    def test_historical_only_by_file_age_and_open_folder_requires_windows(self):
        import os
        import time
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / '.codex'
            project = Path(td) / 'SWAT'
            project.mkdir()
            path = rollout(home, project, 90)
            old = time.time() - 36 * 3600
            os.utime(path, (old, old))
            state = GuardianState(Settings(home, hours=72))
            asyncio.run(state.scan_once())
            item = state.listed_sessions()[0]
            self.assertEqual(item['activity_category'], 'historical')
            self.assertFalse(item['active_verified'])
            self.assertIsNone(state.overview()['max_current_percent'])
            self.assertEqual(state.overview()['max_percent'], 45.0)
            if __import__('sys').platform != 'win32':
                with self.assertRaisesRegex(ValueError, 'Windows'):
                    state.open_session_folder(item['session_id'])
            state.db.close()



if __name__ == '__main__':
    unittest.main()
