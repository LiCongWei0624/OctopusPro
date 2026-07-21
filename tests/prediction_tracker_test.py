import json
import os
import tempfile
import unittest

from prediction_tracker import init_database, prediction_detail, record_prediction, settle_finished_predictions, summary


class PredictionTrackerTests(unittest.TestCase):
    def test_detail_contains_fixture_input_prediction_and_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, 'predictions.sqlite3')
            init_database(database)
            report = json.dumps({
                'prediction_record': {
                    'one_x_two': 'home',
                    'asian_handicap': {'team': 'home', 'line': -0.25},
                    'over_under': {'side': 'over', 'line': 2.5},
                    'confidence': 'high',
                }
            })
            record_prediction(
                database,
                {
                    'match_id': '101', 'home_team': 'Home', 'away_team': 'Away',
                    'kickoff': '2026-07-16 20:00', 'competition': 'Test League',
                    'fixture_date': '07-16 Thursday', 'fixture_status': 1,
                },
                'test-model', 'system', 'fixture input', report,
            )
            settle_finished_predictions(database, [{'id': '101', 'status': 8, 'score': '2-1'}])

            backtest = summary(database)
            sample = backtest['recent'][0]
            detail = prediction_detail(database, sample['id'])

            self.assertEqual(detail['context'], 'fixture input')
            self.assertEqual(detail['prediction']['one_x_two'], 'home')
            self.assertEqual(detail['result']['score'], '2-1')
            self.assertEqual(detail['result']['one_x_two']['outcome'], 'win')
            self.assertEqual(detail['competition'], 'Test League')
            self.assertEqual(detail['fixture_date'], '07-16 Thursday')
            self.assertEqual(detail['fixture_status'], 1)
            self.assertEqual(backtest['metrics']['asian_handicap']['wins'], 1)
            self.assertEqual(backtest['metrics']['over_under']['wins'], 1)
            self.assertNotIn('one_x_two', backtest['metrics'])

    def test_two_market_record_is_valid_and_settles_without_one_x_two(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, 'predictions.sqlite3')
            init_database(database)
            report = json.dumps({
                'prediction_record': {
                    'asian_handicap': {'team': 'away', 'line': 0.25},
                    'over_under': {'side': 'under', 'line': 2.5},
                    'confidence': 'medium',
                }
            })
            self.assertTrue(record_prediction(
                database,
                {'match_id': '202', 'home_team': 'Home', 'away_team': 'Away'},
                'test-model', 'system', 'fixture input', report,
            ))

            settle_finished_predictions(database, [{'id': '202', 'status': 8, 'score': '1-1'}])
            sample = summary(database)['recent'][0]

            self.assertNotIn('one_x_two', sample['prediction'])
            self.assertNotIn('one_x_two', sample['result'])
            self.assertEqual(sample['result']['asian_handicap']['outcome'], 'half_win')
            self.assertEqual(sample['result']['over_under']['outcome'], 'win')

    def test_no_bet_record_is_kept_but_excluded_from_market_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, 'predictions.sqlite3')
            init_database(database)
            report = json.dumps({
                'prediction_record': {
                    'status': 'no_bet',
                    'asian_handicap': None,
                    'over_under': None,
                    'confidence': 'low',
                    'reason': '市场与基线没有可验证优势',
                }
            })
            self.assertTrue(record_prediction(
                database, {'match_id': '303', 'home_team': 'Home', 'away_team': 'Away'},
                'test-model', 'system', 'fixture input', report,
            ))
            settle_finished_predictions(database, [{'id': '303', 'status': 8, 'score': '1-1'}])
            data = summary(database)
            self.assertEqual(data['overview']['no_bet'], 1)
            self.assertEqual(data['overview']['recommended'], 0)
            self.assertEqual(data['overview']['settled'], 0)
            self.assertEqual(data['metrics']['asian_handicap']['settled'], 0)

    def test_rejects_a_line_that_is_not_in_the_snapshot_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, 'predictions.sqlite3')
            init_database(database)
            report = json.dumps({
                'prediction_record': {
                    'status': 'bet',
                    'asian_handicap': {'team': 'home', 'line': -0.75},
                    'over_under': None,
                    'confidence': 'high',
                }
            })
            recorded = record_prediction(
                database,
                {
                    'match_id': '404', 'home_team': 'Home', 'away_team': 'Away',
                    'market_catalog': {
                        'asian_handicap': {'home': [-0.5], 'away': [0.5]},
                        'over_under': {'line': [2.5]},
                    },
                },
                'test-model', 'system', 'fixture input', report,
            )
            self.assertFalse(recorded)
            self.assertEqual(summary(database)['overview']['untracked'], 1)

    def test_statistics_cohort_filters_the_entire_backtest_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, 'predictions.sqlite3')
            init_database(database)
            report = json.dumps({
                'prediction_record': {
                    'status': 'bet',
                    'asian_handicap': {'team': 'home', 'line': -0.25},
                    'over_under': None,
                    'confidence': 'medium',
                }
            })
            for match_id, cohort_id, cohort_name in (
                ('501', 'dual-market-v2-validation-1', '双市场 v2 - 验证批次 1'),
                ('502', 'dual-market-v2-validation-2', '双市场 v2 - 验证批次 2'),
            ):
                record_prediction(
                    database,
                    {
                        'match_id': match_id, 'home_team': 'Home', 'away_team': 'Away',
                        'strategy_version': 'dual-market-v2',
                        'tracking_cohort_id': cohort_id,
                        'tracking_cohort_name': cohort_name,
                    },
                    'test-model', 'system', 'fixture input', report,
                )
            settle_finished_predictions(database, [
                {'id': '501', 'status': 8, 'score': '1-0'},
                {'id': '502', 'status': 8, 'score': '0-1'},
            ])

            data = summary(
                database, cohort_id='dual-market-v2-validation-2',
                cohort_definitions=[
                    {'id': 'dual-market-v2-validation-1', 'name': '双市场 v2 - 验证批次 1'},
                    {'id': 'dual-market-v2-validation-2', 'name': '双市场 v2 - 验证批次 2'},
                ],
            )
            self.assertEqual(data['overview']['window_size'], 1)
            self.assertEqual(data['metrics']['asian_handicap']['losses'], 1)
            self.assertEqual(data['selected_cohort_id'], 'dual-market-v2-validation-2')

    def test_summary_defaults_to_all_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, 'predictions.sqlite3')
            init_database(database)
            report = json.dumps({
                'prediction_record': {
                    'one_x_two': 'home',
                    'asian_handicap': {'team': 'home', 'line': -0.25},
                    'over_under': {'side': 'over', 'line': 2.5},
                }
            })
            for match_id in range(101):
                record_prediction(
                    database,
                    {'match_id': str(match_id), 'home_team': 'Home', 'away_team': 'Away'},
                    'test-model', 'system', 'fixture input', report,
                )

            self.assertEqual(summary(database)['overview']['window_size'], 101)


if __name__ == '__main__':
    unittest.main()
