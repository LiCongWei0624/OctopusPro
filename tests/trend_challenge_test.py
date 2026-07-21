import unittest
from unittest.mock import patch

import detail_scraper


class TrendChallengeTests(unittest.TestCase):
    def test_recognizes_challenge_response(self):
        challenge = '<textarea id="renderData">x</textarea><meta name="aliyun_waf_aa" content="1">'

        self.assertTrue(detail_scraper.is_waf_challenge_response(challenge))
        self.assertFalse(detail_scraper.is_waf_challenge_response('<html><table></table></html>'))

    def test_html_fallback_returns_explicit_challenge_error(self):
        challenge = '<textarea id="renderData">x</textarea><meta name="aliyun_waf_aa" content="1">'
        with patch.object(detail_scraper, 'fetch_html_with_bypass', return_value=challenge):
            result = detail_scraper.get_odds_detail_via_html_pure('101', '2', '1')

        self.assertIn('WAF challenge response persisted', result['error'])


if __name__ == '__main__':
    unittest.main()
