"""External monitoring must detect outages and tolerate a Free-service cold start."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location("monitor", Path(__file__).resolve().parents[1] / "scripts/check_public_service.py")
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)
incident_spec = importlib.util.spec_from_file_location("incident", Path(__file__).resolve().parents[1] / "scripts/report_monitor_issue.py")
incident = importlib.util.module_from_spec(incident_spec)
incident_spec.loader.exec_module(incident)


class PublicMonitorTests(unittest.TestCase):
    def test_healthy_service(self):
        with patch.object(monitor, "read", side_effect=[{"status": "ok"}, {"status": "ok"}, {"points": [{"id": 1}]}]):
            self.assertEqual(monitor.check("https://example.com", delay=0)["status"], "ok")

    def test_cold_start_recovers(self):
        with patch.object(monitor, "read", side_effect=[TimeoutError("cold start"), {"status": "ok"}, {"status": "ok"}, {"clusters": [{"count": 2}]}]):
            result = monitor.check("https://example.com", delay=0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["attempts"]), 1)

    def test_bad_readiness(self):
        with patch.object(monitor, "read", side_effect=[{"status": "failed"}, {"status": "ok"}, {"points": [1]}]):
            result = monitor.check("https://example.com", attempts=1)
        self.assertEqual(result["status"], "failed")
        self.assertIn("readiness", result["attempts"][0]["error"])

    def test_stale_worker(self):
        with patch.object(monitor, "read", side_effect=[{"status": "ok"}, {"status": "degraded"}, {"points": [1]}]):
            result = monitor.check("https://example.com", attempts=1)
        self.assertEqual(result["status"], "failed")
        self.assertIn("stale", result["attempts"][0]["error"])

    def test_empty_map(self):
        with patch.object(monitor, "read", side_effect=[{"status": "ok"}, {"status": "ok"}, {"points": [], "clusters": []}]):
            self.assertEqual(monitor.check("https://example.com", attempts=1)["status"], "failed")

    def test_exhausted_network_retries(self):
        with patch.object(monitor, "read", side_effect=TimeoutError("unavailable")) as read:
            result = monitor.check("https://example.com", delay=0)
        self.assertEqual(read.call_count, 3)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["attempts"]), 3)


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.request = Mock()
        self.issue = {"number": 4, "title": incident.TITLE, "body": incident.MARKER}

    def test_new_outage_opens_incident(self):
        incident.reconcile(False, [], self.request, "https://github.com/run/1")
        self.assertEqual(self.request.call_args.args[:2], ("POST", "/issues"))

    def test_unchanged_outage_stays_quiet(self):
        incident.reconcile(False, [self.issue], self.request, "https://github.com/run/1")
        self.request.assert_not_called()

    def test_recovery_closes_owned_incident(self):
        incident.reconcile(True, [self.issue], self.request, "https://github.com/run/2")
        self.assertEqual(self.request.call_args.args[:2], ("PATCH", "/issues/4"))
        self.assertEqual(self.request.call_args.args[2]["state"], "closed")

    def test_unrelated_issues_and_prs_are_untouched(self):
        items = [{**self.issue, "body": "user issue"}, {**self.issue, "pull_request": {"url": "pr"}}]
        incident.reconcile(True, items, self.request, "https://github.com/run/2")
        self.request.assert_not_called()

    def test_backup_incident_is_separate_from_service_outage(self):
        incident.reconcile(False, [self.issue], self.request, "https://github.com/run/3", kind="backup")
        body = self.request.call_args.args[2]
        self.assertIn("backup", body["title"])
        self.assertIn("livemap-catalog-backup", body["body"])

    def test_healthy_service_does_not_close_backup_outage(self):
        backup = {"number": 5, "title": "[LiveMap backup] Encrypted backup unavailable", "body": "<!-- livemap-catalog-backup -->"}
        incident.reconcile(True, [backup], self.request, "https://github.com/run/4")
        self.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
