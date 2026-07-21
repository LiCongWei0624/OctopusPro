import os
import tempfile
import unittest
from unittest.mock import patch

import app


class BatchTrendHistoryTests(unittest.TestCase):
    def test_all_company_handicap_and_totals_histories_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            companies = [('A', '1'), ('B', '2')]
            odds_index = [{'company': name, 'cid': int(cid)} for name, cid in companies]

            def fetch(match_id, cid, type_val):
                return [{'change_time': '12:00', 'line': '2.5', 'home': 0.9, 'away': 0.9}]

            with patch.object(app, 'CACHE_DIR', directory), \
                 patch.object(app, 'get_odds_detail_via_playwright', side_effect=fetch):
                ok, error, quality = app._refresh_required_trend_history('101', odds_index)

            self.assertTrue(ok, error)
            self.assertEqual(quality['required'], 4)
            self.assertEqual(quality['refreshed'], 4)
            for _, cid in companies:
                for type_val in app.TREND_MARKETS:
                    self.assertTrue(os.path.exists(os.path.join(directory, f'odds_detail_101_{cid}_{type_val}.json')))

    def test_one_missing_history_retries_then_blocks_batch_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            companies = [('A', '1'), ('B', '2')]
            odds_index = [{'company': name, 'cid': int(cid)} for name, cid in companies]
            calls = []

            def fetch(match_id, cid, type_val):
                calls.append((cid, type_val))
                if cid == '2' and type_val == '3':
                    return {'error': 'upstream unavailable'}
                return [{'change_time': '12:00', 'line': '2.5', 'home': 0.9, 'away': 0.9}]

            with patch.object(app, 'CACHE_DIR', directory), \
                 patch.object(app, 'TREND_FETCH_RETRY_DELAY_SECONDS', 0), \
                 patch.object(app, 'get_odds_detail_via_playwright', side_effect=fetch):
                ok, error, quality = app._refresh_required_trend_history('101', odds_index)

            self.assertFalse(ok)
            self.assertIn('B大小球', error)
            self.assertEqual(quality['refreshed'], 3)
            self.assertEqual(len(quality['failures']), 1)
            self.assertFalse(quality['complete'])
            self.assertEqual(calls.count(('2', '3')), app.TREND_FETCH_MAX_ATTEMPTS)

    def test_absent_market_is_not_requested_but_present_market_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            odds_index = [
                {
                    'company': 'Only handicap', 'cid': 1,
                    'handicap': {'available': True}, 'over_under': {'available': False},
                },
                {
                    'company': 'Only totals', 'cid': 2,
                    'handicap': {'available': False}, 'over_under': {'available': True},
                },
            ]
            calls = []

            def fetch(match_id, cid, type_val):
                calls.append((cid, type_val))
                return [{'change_time': '12:00', 'line': '2.5', 'home': 0.9, 'away': 0.9}]

            with patch.object(app, 'CACHE_DIR', directory), \
                 patch.object(app, 'get_odds_detail_via_playwright', side_effect=fetch):
                ok, error, quality = app._refresh_required_trend_history('101', odds_index)

            self.assertTrue(ok, error)
            self.assertEqual(quality['required'], 2)
            self.assertEqual(set(calls), {('1', '1'), ('2', '3')})

    def test_active_batch_pipeline_blocks_context_when_trends_fail(self):
        item = {
            'match_id': '101', 'home_team': 'Home', 'away_team': 'Away',
            'analysis_mode': 'prematch',
        }
        details = {'odds_index': [{'company': 'A', 'cid': 1}]}
        snapshot = {'quality': {}, 'hash': 'fixture-hash', 'captured_at': 'now'}

        with patch.object(app, '_persist_latest_batch_state'), \
             patch.object(app, '_prepare_analysis_snapshot', return_value=(True, '', details, snapshot)), \
             patch.object(app, '_refresh_required_trend_history', return_value=(False, 'trend missing', {'complete': False})), \
             patch.object(app, 'build_match_prompt_context') as build_context:
            success, error, context, prepared_snapshot = app._prepare_batch_item('batch-test', item)

        self.assertFalse(success)
        self.assertEqual(error, 'trend missing')
        self.assertIsNone(context)
        self.assertEqual(prepared_snapshot['trend_quality']['complete'], False)
        build_context.assert_not_called()


if __name__ == '__main__':
    unittest.main()
