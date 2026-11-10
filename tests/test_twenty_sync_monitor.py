"""Health-check rules of the read-only Twenty sync monitor (pure functions)."""
import unittest

from app.integrations.twenty_sync_monitor import ACTIONS, _checks


def sections(**over):
    base = {
        "parsing": {"last_email_minutes_ago": 3, "parsed_1h": 400, "parsed_24h": 3000, "latest_job": None},
        "service": {"last_success_minutes_ago": 1,
                    "reconciliation": {"status": "COMPLETE", "started_hours_ago": 3, "checked": 10},
                    "worker_restarts": {"incidents": 0, "last_minutes_ago": None},
                    "source_poll": {"status": "COMPLETE", "completed_minutes_ago": 2}},
        "capture": {"captured_24h": 500, "last_captured_minutes_ago": 1, "pending": 265000, "oldest_pending_minutes": 9000},
        "outbox": {"backlog": 10, "oldest_backlog_minutes": 5, "published_1h": 900, "published_24h": 20000, "with_errors": 0},
        "inbox_quarantine": {"quarantine_open": 0, "quarantine_by_reason": [], "processing": {"count": 5, "older_than_24h": 0}},
        "alerts": {"active": []},
    }
    base.update(over)
    return base


def by_id(checks):
    return {c["id"]: c for c in checks}


class Rules(unittest.TestCase):
    def test_healthy_everything_is_green(self):
        self.assertTrue(all(c["status"] == "ok" for c in _checks(sections())))

    def test_unprocessed_capture_rows_are_not_a_health_signal(self):
        # processed_at is not stamped by the sync, so a huge "pending" count must NOT alarm.
        self.assertEqual(by_id(_checks(sections()))["capture"]["status"], "ok")

    def test_stuck_reconciliation_fails(self):
        s = sections(service={**sections()["service"],
                              "reconciliation": {"status": "RUNNING", "started_hours_ago": 144, "checked": 0}})
        c = by_id(_checks(s))["reconcile"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("6 days", c["detail"])

    def test_no_recent_delivery_fails(self):
        s = sections(service={**sections()["service"], "last_success_minutes_ago": 200})
        self.assertEqual(by_id(_checks(s))["heartbeat"]["status"], "fail")

    def test_old_outbox_backlog_escalates(self):
        for minutes, expected in ((20, "ok"), (60, "warn"), (300, "fail")):
            s = sections(outbox={**sections()["outbox"], "backlog": 500, "oldest_backlog_minutes": minutes})
            self.assertEqual(by_id(_checks(s))["outbox"]["status"], expected, minutes)

    def test_quarantine_and_alerts_are_warnings_not_outages(self):
        s = sections(inbox_quarantine={"quarantine_open": 6000, "quarantine_by_reason":
                                       [{"reason": "SOURCE_SIGNALS_REVIEW", "count": 4938, "oldest_days": 5}],
                                       "processing": {"count": 9000, "older_than_24h": 9000}},
                     alerts={"active": [{"code": "QUEUE_BACKLOG", "label": "Events are queuing", "count": 1, "since_days": 5}]})
        got = by_id(_checks(s))
        self.assertEqual((got["quarantine"]["status"], got["processing"]["status"], got["alerts"]["status"]),
                         ("warn", "warn", "warn"))

    def test_failed_section_is_skipped_not_fatal(self):
        s = sections(outbox={"error": "OperationalError"}, alerts={"error": "OperationalError"})
        ids = {c["id"] for c in _checks(s)}
        self.assertNotIn("outbox", ids)
        self.assertIn("heartbeat", ids)

    def test_every_non_green_check_has_an_owner_hint(self):
        s = sections(service={**sections()["service"], "last_success_minutes_ago": 200,
                              "reconciliation": {"status": "RUNNING", "started_hours_ago": 144, "checked": 0}})
        for c in _checks(s):
            if c["status"] != "ok":
                self.assertIn(c["id"], ACTIONS)


if __name__ == "__main__":
    unittest.main()
