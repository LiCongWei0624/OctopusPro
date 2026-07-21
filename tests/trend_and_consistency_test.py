# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch
import os
import tempfile
import app

class TrendAndConsistencyTests(unittest.TestCase):
    def test_trend_degradation_gate_passes_when_above_threshold(self):
        """测试走势刷新在获取 13/22 (59.1% >= 55%) 时能够触发降级门禁允许通过"""
        with tempfile.TemporaryDirectory() as directory:
            companies = [(f'Company_{i}', str(i)) for i in range(1, 12)] # 11 家公司 x 2 市场 = 22 组合
            odds_index = [{'company': name, 'cid': int(cid)} for name, cid in companies]

            call_count = [0]
            def mock_fetch(match_id, cid, type_val):
                call_count[0] += 1
                if int(cid) <= 7: # 前 7 家成功（7x2 = 14 个成功，14/22 = 63.6%）
                    return [{'change_time': '12:00', 'line': '0.5', 'home': 0.9, 'away': 0.9}]
                return {'error': 'WAF challenge'}

            with patch.object(app, 'CACHE_DIR', directory), \
                 patch.object(app, 'TREND_FETCH_RETRY_DELAY_SECONDS', 0), \
                 patch.object(app, 'get_odds_detail_via_playwright', side_effect=mock_fetch):
                ok, error, quality = app._refresh_required_trend_history('4556502', odds_index)

            self.assertTrue(ok, f"应当允许 14/22 降级通过: {error}")
            self.assertTrue(quality['degraded'])
            self.assertFalse(quality['complete'])
            self.assertEqual(quality['refreshed'], 14)
            self.assertEqual(quality['required'], 22)

    def test_preparation_failure_trace_persisted(self):
        """测试准备阶段失败时独立生成审计 trace 文件"""
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, 'ANALYSIS_TRACE_DIR', directory):
                trace_path = app._persist_preparation_failure_trace('4556502', 'trend', '变盘历史未达到极小降级门槛')
                self.assertIsNotNone(trace_path)
                self.assertTrue(os.path.exists(trace_path))

    def test_report_consistency_validation(self):
        """测试模型报告推理与最终推荐结论一致性硬校验"""
        valid_report = """
#### 二、 盘口语言解码
真实期望值在客队，机构高水诱主。

##### 1. 亚洲让球盘推荐
- **【最佳价值切入】**：客队 +0.5 | **风控逻辑**：受让打出
"""
        is_valid, msg = app.validate_report_recommendation_consistency(valid_report)
        self.assertTrue(is_valid)

        invalid_report = """
#### 二、 盘口语言解码
真实期望值在客队，机构高水诱主。

##### 1. 亚洲让球盘推荐
- **【最佳价值切入】**：主队 -0.5 | **风控逻辑**：上盘打出
"""
        is_valid, msg = app.validate_report_recommendation_consistency(invalid_report)
        self.assertFalse(is_valid)
        self.assertIn("冲突", msg)

if __name__ == '__main__':
    unittest.main()
