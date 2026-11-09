"""Regression tests for the optional intelligence module (no external services)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json

from fastapi.testclient import TestClient
from control_center.intelligence import (
    IntelligenceService, aggregate_codex, demo_analytics,
)
from control_center.server import Settings, create_app


def _line(at, counters, model="gpt-test"):
    return {"timestamp": at.isoformat(), "type": "event_msg",
            "payload": {"type": "token_count", "info": {
                "model": model, "total_token_usage": counters,
                "last_token_usage": counters}}}


class IntelligenceTests(TestCase):
    def test_cumulative_counters_dedup_same_session_across_files(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / ".codex"
            folder = home / "sessions" / "2026" / "11" / "09"
            folder.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            a = now - timedelta(hours=2)
            b = now - timedelta(hours=1)
            first = {"input_tokens": 80, "output_tokens": 20,
                     "cached_input_tokens": 30, "total_tokens": 100}
            second = {"input_tokens": 120, "output_tokens": 30,
                      "cached_input_tokens": 40, "total_tokens": 150}
            meta = {"type": "session_meta", "payload": {
                "id": "logical-session", "cwd": "C:\\Dev\\SWAT\\ProjectAlpha"}}
            (folder / "rollout-a.jsonl").write_text("\n".join(map(json.dumps, [
                meta, {"type": "response_item", "payload": {"content": "TOP_SECRET_TRANSCRIPT"}},
                _line(a, first), _line(b, second)
            ])) + "\n", encoding="utf-8")
            (folder / "rollout-b.jsonl").write_text("\n".join(map(json.dumps, [
                meta, _line(a, first), _line(b, second)
            ])) + "\n", encoding="utf-8")
            result = aggregate_codex(home, 7)
            self.assertEqual(result["summary"]["tokens"], 150)
            self.assertEqual(result["summary"]["sessions"], 1)
            self.assertEqual(result["summary"]["projects"], 1)
            self.assertEqual(result["models"][0]["name"], "gpt-test")
            self.assertEqual(result["projects"][0]["name"], "ProjectAlpha")
            self.assertEqual(sum(d["cached_tokens"] for d in result["daily"]), 40)
            self.assertEqual(len(result["hours"]), 168)
            self.assertNotIn("TOP_SECRET_TRANSCRIPT", json.dumps(result))
            self.assertNotIn("C:\\Dev\\SWAT", json.dumps(result))

    def test_new_session_does_not_assume_live_process(self):
        with TemporaryDirectory() as tmp:
            result = aggregate_codex(Path(tmp) / ".codex", 30)
            self.assertEqual(result["summary"]["sessions"], 0)
            self.assertEqual(result["summary"]["tokens"], 0)
            self.assertFalse(result["coverage"]["partial"])
            self.assertEqual(len(result["calendar"]), 30)

    def test_invalid_period_rejected(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                aggregate_codex(Path(tmp), 0)
            with self.assertRaises(ValueError):
                aggregate_codex(Path(tmp), 366)

    def test_demo_is_unmistakably_simulated_and_non_persistent(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "missing-codex"
            service = IntelligenceService(root, demo=True)
            result = service.snapshot(90)
            self.assertEqual(len(result["daily"]), 90)
            self.assertIn("DEMO", result["source"])
            self.assertEqual(result["summary"]["cost_usd"], None)
            self.assertFalse(root.exists())

    def test_ccusage_parses_unified_json_without_exposing_raw_paths(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            today = datetime.now(timezone.utc).date().isoformat()
            payload = {"daily": [{"period": today, "agent": "all",
                "totalTokens": 1000, "totalCost": 0.52,
                "agents": [
                    {"agent": "codex", "totalTokens": 700, "totalCost": 0.31},
                    {"agent": "hermes", "totalTokens": 300, "totalCost": 0.21}],
                "path": "/secret/prompt/transcript"}],
                "totals": {"unpricedModels": ["unlisted"]}}
            class Result:
                returncode = 0
                stdout = json.dumps(payload)
                stderr = ""
            with patch("control_center.intelligence.shutil.which", return_value="/mock/ccusage"):
                with patch("control_center.intelligence.subprocess.run", return_value=Result()) as run:
                    report = IntelligenceService(home).ccusage_report()
            self.assertEqual(report["daily"][0]["tokens"], 1000)
            self.assertEqual(report["daily"][0]["cost_usd"], 0.52)
            self.assertEqual(len(report["agents"]), 2)
            self.assertEqual(report["agents"][0]["name"], "codex")
            self.assertEqual(report["unpriced_models"], ["unlisted"])
            self.assertNotIn("/secret", json.dumps(report))
            self.assertEqual(run.call_args.args[0], ["/mock/ccusage", "daily", "--by-agent", "--json"])

    def test_ccusage_not_installed_has_explicit_state(self):
        with patch("control_center.intelligence.shutil.which", return_value=None):
            report = IntelligenceService(Path(".")).ccusage_report()
        self.assertFalse(report["available"])
        self.assertEqual(report["daily"], [])

    def test_api_demo_and_html_are_available_without_real_codex(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "not-created"
            with TestClient(create_app(Settings(home, demo=True))) as client:
                page = client.get("/intelligence")
                self.assertEqual(page.status_code, 200)
                self.assertIn("Mapa de calor", page.text)
                self.assertIn("hours-chart", page.text.replace("hour-chart", "hours-chart"))
                response = client.get("/api/intelligence?days=30")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mode"], "DEMO (simulado)")
                self.assertEqual(len(response.json()["calendar"]), 30)
                self.assertEqual(client.get("/api/intelligence?days=999").status_code, 422)
                self.assertFalse(client.get("/api/intelligence/ccusage").json()["available"])
            self.assertFalse(home.exists())
