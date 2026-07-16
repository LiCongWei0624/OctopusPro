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

            sample = summary(database)['recent'][0]
            detail = prediction_detail(database, sample['id'])

            self.assertEqual(detail['context'], 'fixture input')
            self.assertEqual(detail['prediction']['one_x_two'], 'home')
            self.assertEqual(detail['result']['score'], '2-1')
            self.assertEqual(detail['result']['one_x_two']['outcome'], 'win')
            self.assertEqual(detail['competition'], 'Test League')
            self.assertEqual(detail['fixture_date'], '07-16 Thursday')
            self.assertEqual(detail['fixture_status'], 1)

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
