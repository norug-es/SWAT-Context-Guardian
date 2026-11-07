import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from argparse import Namespace

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'scripts' / 'guardian.py'
spec = importlib.util.spec_from_file_location('guardian', PATH)
guardian = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guardian
spec.loader.exec_module(guardian)


def write_rollout(home: Path, events):
    p = home / 'sessions' / '2026' / '11' / '07' / 'rollout-test.jsonl'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events), encoding='utf-8')
    return p


def sample_events(total=160, window=200):
    return [
        {'type': 'session_meta', 'payload': {'id': 'test-session', 'cwd': '/test/repo', 'originator': 'codex'}},
        {'timestamp': '2026-11-07T20:00:00Z', 'type': 'event_msg', 'payload': {
            'type': 'token_count', 'info': {
                'last_token_usage': {'total_tokens': total},
                'total_token_usage': {'total_tokens': 100000},
                'model_context_window': window
            }}}
    ]


class GuardianTest(unittest.TestCase):
    def test_parses_last_usage_not_cumulative(self):
        with tempfile.TemporaryDirectory() as td:
            path = write_rollout(Path(td), sample_events(160, 200))
            s = guardian.inspect_session(path)
            self.assertEqual(s.session_id, 'test-session')
            self.assertEqual(s.project, '/test/repo')
            self.assertEqual(s.active_tokens_approx, 160)
            self.assertEqual(s.percent_approx, 80.0)
            self.assertEqual(guardian.tier(s.percent_approx), 80)

    def test_missing_usage_means_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            events = sample_events()
            del events[1]['payload']['info']['last_token_usage']
            path = write_rollout(Path(td), events)
            s = guardian.inspect_session(path)
            self.assertIsNone(s.percent_approx)
            self.assertEqual(guardian.tier(s.percent_approx), 0)

    def test_does_not_store_transcript_content(self):
        with tempfile.TemporaryDirectory() as td:
            events = sample_events()
            events.insert(1, {'type': 'response_item', 'payload': {'content': 'SECRET_NOT_FOR_LOG'}})
            path = write_rollout(Path(td), events)
            snapshot = guardian.inspect_session(path)
            self.assertNotIn('SECRET_NOT_FOR_LOG', json.dumps(guardian.asdict(snapshot)))

    def test_discover_rollouts_and_checkpoint_no_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / '.codex'
            write_rollout(home, sample_events())
            found = guardian.discover(home, 12, 9999)
            self.assertEqual(len(found), 1)
            arguments = Namespace(
                codex_home=str(home), limit=12, hours=9999,
                project=td, session=None, summary='Resumen comprobado',
                decisions='Aprobado: diseño', evidence='PASS: unit tests',
                pending='Pendiente: revisión', next_step='Inspeccionar logs',
                safety='Sin acceso a producción'
            )
            self.assertEqual(guardian.command_checkpoint(arguments), 0)
            files = list((home / 'context-guardian' / 'checkpoints').glob('*.json'))
            self.assertEqual(len(files), 1)
            contents = files[0].read_text(encoding='utf-8')
            self.assertIn('Resumen comprobado', contents)
            output = files[0].with_suffix('.md')
            args = Namespace(checkpoint=str(files[0]), output=str(output), overwrite=False)
            self.assertEqual(guardian.command_handoff(args), 0)
            self.assertTrue(output.is_file())
            self.assertEqual(guardian.command_handoff(args), 2)

    def test_read_only_watch_once(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            write_rollout(home, sample_events(140, 200))
            args = Namespace(codex_home=str(home), limit=12, hours=9999, interval=10, once=True)
            self.assertEqual(guardian.command_watch(args), 0)
            log = home / 'context-guardian' / 'alerts.jsonl'
            events = [json.loads(s) for s in log.read_text().splitlines()]
            self.assertEqual(events[0]['tier'], 70)
            self.assertEqual(events[0]['action'], 'PREPARAR_CHECKPOINT')
            self.assertTrue(events[0]['read_only'])

    def test_installer_dry_run_then_apply(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'global' / 'swat-context-guardian'
            script = ROOT / 'scripts' / 'install_global.py'
            preview = subprocess.run([sys.executable, str(script), '--destination', str(target)], capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertFalse(target.exists())
            applied = subprocess.run([sys.executable, str(script), '--destination', str(target), '--apply'], capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertTrue((target / 'SKILL.md').is_file())
            again = subprocess.run([sys.executable, str(script), '--destination', str(target), '--apply'], capture_output=True, text=True)
            self.assertEqual(again.returncode, 2)

    def test_compaction_preview_then_explicit_apply(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            config = home / 'config.toml'
            original = b'# do not change me\r\n[features]\r\nexample = true\r\n'
            config.write_bytes(original)
            script = ROOT / 'scripts' / 'native_compaction.py'
            cmd = [sys.executable, str(script), '--codex-home', str(home)]
            preview = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(config.read_bytes(), original)
            blocked = subprocess.run(cmd + ['--apply'], capture_output=True, text=True)
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(config.read_bytes(), original)
            applied = subprocess.run(cmd + ['--apply', '--acknowledge-compatibility'], capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertIn(b'model_post_turn_compact_threshold_percent = 80', config.read_bytes())
            self.assertTrue(config.read_bytes().endswith(original), 'Existing bytes must be preserved verbatim')
            backups = list(home.glob('config.toml.bak-context-guardian-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
