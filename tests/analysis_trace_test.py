import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app


class AnalysisTraceTests(unittest.TestCase):
    def test_trace_persists_inputs_outputs_and_failure_without_credentials(self):
        task_key = 'trace-test-task'
        app.ai_tasks[task_key] = {
            'trace_id': 'trace-test',
            'status': 'failed',
            'phase': 'ai',
            'error': 'provider timeout',
            'started_at': 1,
            'snapshot_hash': 'fixture-hash',
            'analysis_input': 'fixture context',
            'analyst_inputs': [{'messages': [{'role': 'user', 'content': 'prompt'}]}],
            'analyst_outputs': [{'status': 'failed', 'reasoning': 'checked data', 'content': '', 'error': 'timeout'}],
            'reports': ['visible analyst report'],
            'final_ticket': 'visible final report',
            'cro_input': None,
            'cro_output': None,
        }
        try:
            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(app, 'ANALYSIS_TRACE_DIR', directory):
                trace_path = app._persist_analysis_trace('101', task_key, 'model-test', 'prematch')
                self.assertTrue(os.path.exists(trace_path))
                with open(trace_path, 'r', encoding='utf-8') as trace_file:
                    trace = json.load(trace_file)

            self.assertEqual(trace['status'], 'failed')
            self.assertEqual(trace['analysis_input'], 'fixture context')
            self.assertNotIn('reasoning', trace['analyst_outputs'][0])
            self.assertTrue(trace['analyst_outputs'][0]['reasoning_omitted'])
            self.assertEqual(trace['analyst_reports'], ['visible analyst report'])
            self.assertEqual(trace['final_report'], 'visible final report')
            self.assertNotIn('api_key', json.dumps(trace))
            self.assertNotIn('Authorization', json.dumps(trace))
        finally:
            app.ai_tasks.pop(task_key, None)


if __name__ == '__main__':
    unittest.main()
