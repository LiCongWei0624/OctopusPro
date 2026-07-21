import datetime
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app


class AnalysisCacheTests(unittest.TestCase):
    def _cache_data(self, captured_at, market_hash='market-a'):
        return {
            'analysis_version': app.AI_ANALYSIS_CACHE_VERSION,
            'analysis_mode': 'prematch',
            'snapshot_hash': 'snapshot-a',
            'market_snapshot_hash': market_hash,
            'snapshot_captured_at': captured_at.isoformat(timespec='seconds'),
            'reports': ['report 1', 'report 2', 'report 3'],
            'final_ticket': 'final report',
        }

    def test_only_recent_prematch_cache_is_reusable(self):
        now = datetime.datetime(2026, 7, 21, 12, 0, 0)
        fresh = self._cache_data(now - datetime.timedelta(seconds=60))
        stale = self._cache_data(now - datetime.timedelta(seconds=91))

        self.assertTrue(app._is_reusable_analysis_cache(fresh, 'prematch', now=now))
        self.assertFalse(app._is_reusable_analysis_cache(stale, 'prematch', now=now))
        self.assertFalse(app._is_reusable_analysis_cache(fresh, 'live', now=now))

    def test_market_change_invalidates_existing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = os.path.join(directory, 'ai_analysis_101.json')
            with open(cache_path, 'w', encoding='utf-8') as cache_file:
                json.dump(self._cache_data(datetime.datetime.now(), market_hash='old-market'), cache_file)

            with patch.object(app, 'CACHE_DIR', directory):
                invalidated = app._invalidate_ai_cache_if_market_changed(
                    '101', {'odds_index': [{'cid': 1, 'home': 0.91, 'away': 0.95}]}
                )

            self.assertTrue(invalidated)
            self.assertFalse(os.path.exists(cache_path))

    def test_market_hash_is_independent_of_company_order(self):
        first = {'odds_index': [{'cid': 2, 'company': 'B'}, {'cid': 1, 'company': 'A'}]}
        second = {'odds_index': [{'cid': 1, 'company': 'A'}, {'cid': 2, 'company': 'B'}]}

        self.assertEqual(app._market_snapshot_hash(first), app._market_snapshot_hash(second))


if __name__ == '__main__':
    unittest.main()
