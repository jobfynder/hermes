import unittest
from unittest.mock import patch, MagicMock
from app.reporting import service

class ReportCacheTests(unittest.TestCase):
    def test_snapshot_reused_without_shared_mutation(self):
        calls = []
        @service._cached_report(30)
        def report():
            calls.append(1)
            return {'items': [1]}
        report()['items'].append(2)
        self.assertEqual(report(), {'items': [1]})
        self.assertEqual(len(calls), 1)

    def test_cost_fetch_reused_across_windows(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data":[]}'
        with patch.dict('os.environ', {'LANGFUSE_PUBLIC_KEY':'test','LANGFUSE_SECRET_KEY':'test','LANGFUSE_BASE_URL':'https://cost-test.invalid'}), patch.object(service.urllib.request, 'urlopen', return_value=response) as fetch:
            for days in (1, 7, 30):
                service.get_llm_cost_trend(days)
        self.assertEqual(fetch.call_count, 1)

    def test_cost_failure_reused_without_repeated_wait(self):
        with patch.dict('os.environ', {'LANGFUSE_PUBLIC_KEY':'test','LANGFUSE_SECRET_KEY':'test','LANGFUSE_BASE_URL':'https://cost-failure.invalid'}), patch.object(service.urllib.request, 'urlopen', side_effect=TimeoutError) as fetch:
            for days in (1, 7, 30):
                self.assertFalse(service.get_llm_cost_trend(days)['available'])
        self.assertEqual(fetch.call_count, 1)
