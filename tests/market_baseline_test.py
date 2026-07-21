import math
import unittest
from unittest.mock import patch

import app


class MarketBaselineTests(unittest.TestCase):
    def test_baseline_returns_finite_directional_expectations(self):
        details = {
            'standings': [
                {'total': 20, 'goals_for': 31},
                {'total': 20, 'goals_for': 25},
            ],
            'recent_results': {
                'home': [
                    {'home': 'Home', 'away': 'A', 'score': '2-0'},
                    {'home': 'B', 'away': 'Home', 'score': '1-1'},
                ],
                'away': [
                    {'home': 'Away', 'away': 'C', 'score': '0-1'},
                    {'home': 'D', 'away': 'Away', 'score': '1-2'},
                ],
            },
        }
        baseline = app._build_probability_baseline(details, 'Home', 'Away')

        self.assertGreater(baseline['total_mean'], 0)
        self.assertTrue(math.isfinite(baseline['total_expectation'](2.5, 'over')))
        self.assertTrue(math.isfinite(baseline['handicap_expectation'](-0.25, 'home')))
        self.assertTrue(math.isfinite(baseline['handicap_expectation'](0.25, 'away')))

    def test_catalog_exposes_only_normalized_current_lines(self):
        details = {
            'odds_index': [
                {
                    'handicap': {
                        'home_instant_line': -0.25,
                        'away_instant_line': 0.25,
                        'instant': [0.9, 0.9],
                    },
                    'over_under': {'instant_line': '2.75'},
                },
                {
                    'handicap': {
                        'home_instant_line': -0.5,
                        'away_instant_line': 0.5,
                        'instant': [0.9, 0.9],
                    },
                    'over_under': {'instant_line': '2.75', 'instant': [0.9, 0.9]},
                },
            ],
        }
        self.assertEqual(app._instant_market_catalog(details), {
            'asian_handicap': {
                'home': [-0.5, -0.25], 'away': [0.25, 0.5],
                'quotes': [
                    {'company': '', 'cid': '', 'team': 'home', 'line': -0.25, 'water': 0.9, 'decimal_odds': 1.9, 'market_probability': 0.5},
                    {'company': '', 'cid': '', 'team': 'away', 'line': 0.25, 'water': 0.9, 'decimal_odds': 1.9, 'market_probability': 0.5},
                    {'company': '', 'cid': '', 'team': 'home', 'line': -0.5, 'water': 0.9, 'decimal_odds': 1.9, 'market_probability': 0.5},
                    {'company': '', 'cid': '', 'team': 'away', 'line': 0.5, 'water': 0.9, 'decimal_odds': 1.9, 'market_probability': 0.5},
                ],
            },
            'over_under': {
                'line': [2.75],
                'quotes': [
                    {'company': '', 'cid': '', 'side': 'over', 'line': 2.75, 'water': 0.9, 'decimal_odds': 1.9, 'market_probability': 0.5},
                    {'company': '', 'cid': '', 'side': 'under', 'line': 2.75, 'water': 0.9, 'decimal_odds': 1.9, 'market_probability': 0.5},
                ],
            },
        })

    def test_baseline_calculates_price_sensitive_asian_expected_value(self):
        details = {
            'standings': [{'total': 20, 'goals_for': 30}, {'total': 20, 'goals_for': 20}],
            'recent_results': {
                'home': [{'home': 'Home', 'away': 'A', 'score': '3-0'}],
                'away': [{'home': 'Away', 'away': 'B', 'score': '0-1'}],
            },
        }
        baseline = app._build_probability_baseline(details, 'Home', 'Away')
        low_price = baseline['handicap_expected_value'](-0.25, 'home', 0.6)
        high_price = baseline['handicap_expected_value'](-0.25, 'home', 1.2)
        self.assertLess(low_price, high_price)

    def test_prompt_context_initializes_standings_before_recent_form_annotations(self):
        details = {
            'competition': 'Test League',
            'standings': [
                {'team_name': 'Home', 'position': 1, 'total': 20, 'goals_for': 32},
                {'team_name': 'Away', 'position': 4, 'total': 20, 'goals_for': 24},
            ],
            'recent_results': {
                'home': [{'home': 'Home', 'away': 'Away', 'score': '2-1', 'result': '胜'}],
                'away': [{'home': 'Home', 'away': 'Away', 'score': '2-1', 'result': '负'}],
            },
            'odds_index': [{
                'company': 'Test Book', 'cid': 1,
                'handicap': {
                    'available': True, 'home_initial_line': -0.25, 'away_initial_line': 0.25,
                    'home_instant_line': -0.25, 'away_instant_line': 0.25,
                    'initial': [0.9, 0.9], 'instant': [0.9, 0.9],
                },
                'over_under': {
                    'available': True, 'initial_line': 2.5, 'instant_line': 2.5,
                    'initial': [0.9, 0.9], 'instant': [0.9, 0.9],
                },
                'europe': {'initial': [2.0, 3.2, 3.6], 'instant': [2.0, 3.2, 3.6]},
            }],
        }

        with patch.object(app, 'load_match_store', return_value=([], {})), \
             patch.object(app, '_trend_companies_from_odds', return_value=([], [])):
            success, error, context = app.build_match_prompt_context(
                '101', 'Home', 'Away', details=details, trend_quality={'complete': True},
            )

        self.assertTrue(success, error)
        self.assertIn('Home', context)
        self.assertIn('Test Book', context)
        self.assertIn('EV', context)


if __name__ == '__main__':
    unittest.main()
