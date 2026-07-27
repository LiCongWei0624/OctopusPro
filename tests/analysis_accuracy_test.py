import unittest
import tempfile
from unittest.mock import patch

import app
import detail_scraper


class AnalysisAccuracyTests(unittest.TestCase):
    def test_zero_handicap_is_preserved_in_market_catalog(self):
        details = {
            'odds_index': [{
                'company': 'Pinnacle', 'cid': 22,
                'handicap': {
                    'available': True,
                    'home_instant_line': 0,
                    'away_instant_line': 0,
                    'instant': [0.91, 0.93],
                },
                'over_under': {'available': False},
            }],
        }

        catalog = app._instant_market_catalog(details)

        self.assertEqual(catalog['asian_handicap']['home'], [0.0])
        self.assertEqual(catalog['asian_handicap']['away'], [0.0])
        self.assertEqual(len(catalog['asian_handicap']['quotes']), 2)

    def test_league_total_average_is_not_used_as_each_team_goal_prior(self):
        details = {
            'standings': [
                {'total': 20, 'goals_for': 26},
                {'total': 20, 'goals_for': 26},
            ],
            'recent_results': {'home': [], 'away': []},
        }

        baseline = app._build_probability_baseline(details, 'Home', 'Away')

        self.assertAlmostEqual(baseline['league_average'], 2.6, places=2)
        self.assertAlmostEqual(baseline['total_mean'], 2.6, places=2)

    def test_prematch_trend_filter_excludes_in_play_rows(self):
        rows = [
            {'change_time': 200, 'match_minute': '91', 'match_status': 4, 'score': '2-3'},
            {'change_time': 100, 'match_minute': '', 'match_status': 1, 'score': '0-0'},
        ]

        filtered = app._trend_rows_for_analysis_mode(rows, 'prematch')

        self.assertEqual(filtered, [rows[1]])

    def test_prematch_trend_filter_excludes_legacy_live_rows(self):
        rows = [
            {'change_time': '45+', 'score': '1-0', 'line': '-0.25'},
            {'change_time': '07-27 15:00', 'score': '', 'line': '-0.25'},
        ]

        filtered = app._trend_rows_for_analysis_mode(rows, 'prematch')

        self.assertEqual(filtered, [rows[1]])

    def test_handicap_trend_line_uses_the_snapshot_home_direction(self):
        home_receives_rows = [
            {'line': '-2.0', 'source': 'api_compact'},
            {'line': '-1.75', 'source': 'api_compact'},
        ]
        home_gives_rows = [
            {'line': '2.0', 'source': 'api_compact'},
            {'line': '1.75', 'source': 'api_compact'},
        ]

        home_receives = app._normalize_handicap_trend_direction(home_receives_rows)
        home_gives = app._normalize_handicap_trend_direction(home_gives_rows)

        self.assertEqual([row['line'] for row in home_receives], ['2.0', '1.75'])
        self.assertEqual([row['line'] for row in home_gives], ['-2.0', '-1.75'])

    def test_html_trend_direction_is_not_inverted_again(self):
        rows = [{'line': '0.75', 'source': 'html_table'}]

        normalized = app._normalize_handicap_trend_direction(rows)

        self.assertEqual(normalized[0]['line'], '0.75')

    def test_compact_trend_rows_keep_state_needed_for_mode_filtering(self):
        raw = [[1783533076, '93', '3.0', '-0.25', '0.23', 4, 1, '2-3']]

        normalized = detail_scraper.normalize_odds_detail_history(raw, 1)

        self.assertEqual(normalized[0]['match_minute'], '93')
        self.assertEqual(normalized[0]['match_status'], 4)
        self.assertEqual(normalized[0]['raw_flag'], 1)
        self.assertEqual(normalized[0]['source'], 'api_compact')

    def test_system_prompt_matches_the_three_company_strategy(self):
        self.assertIn('Pinnacle', app.DEFAULT_SYSTEM_PROMPT)
        self.assertIn('Bet365', app.DEFAULT_SYSTEM_PROMPT)
        self.assertIn('皇冠', app.DEFAULT_SYSTEM_PROMPT)
        self.assertNotIn('威***', app.DEFAULT_SYSTEM_PROMPT)
        self.assertNotIn('澳*', app.DEFAULT_SYSTEM_PROMPT)
        self.assertNotIn('资金流向', app.DEFAULT_SYSTEM_PROMPT)

    def test_cro_anchor_keeps_probability_baseline_with_market_data(self):
        context = '基本面\n【八、 后端进球概率基线（固定算法，非 xG）】\n基线 EV\n【赔率指数】\n市场'

        anchored = app._cro_market_anchor_context(context)

        self.assertTrue(anchored.startswith('【八、 后端进球概率基线'))
        self.assertIn('基线 EV', anchored)
        self.assertIn('【赔率指数】', anchored)

    def test_prematch_refresh_rejects_in_play_only_history(self):
        odds_index = [{'company': 'Pinnacle', 'cid': 22}]
        in_play_only = [{
            'change_time': 200, 'match_minute': '10', 'match_status': 2,
            'line': '-0.25', 'home': 0.9, 'away': 0.9,
        }]

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app, 'CACHE_DIR', directory), \
             patch.object(app, 'PREFERRED_TREND_COMPANY_IDS', ('22',)), \
             patch.object(app, 'TREND_FETCH_MAX_ATTEMPTS', 1), \
             patch.object(app, 'get_odds_detail_via_playwright', return_value=in_play_only):
            ok, error, quality = app._refresh_required_trend_history(
                '101', odds_index, analysis_mode='prematch'
            )

        self.assertFalse(ok)
        self.assertEqual(quality['refreshed'], 0)
        self.assertIn('赛前', error)


if __name__ == '__main__':
    unittest.main()