# -*- coding: utf-8 -*-
import http.cookiejar
import json
import unittest
from unittest.mock import mock_open, patch

import detail_scraper
import focused_scheduler


def make_cookie(name, value, domain):
    return http.cookiejar.Cookie(
        version=0, name=name, value=value,
        port=None, port_specified=False,
        domain=domain, domain_specified=True, domain_initial_dot=domain.startswith('.'),
        path='/', path_specified=True,
        secure=False, expires=None, discard=True,
        comment=None, comment_url=None, rest={}, rfc2109=False,
    )


class FakeResponse:
    def __init__(self, body=b'{}', url='https://api-gateway.leisu.com/test'):
        self.body = body
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body

    def info(self):
        return {}

    def geturl(self):
        return self.url


class CapturingOpener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        return FakeResponse(url=request.full_url)


class OddsWafPerformanceTests(unittest.TestCase):
    def test_session_cookie_reload_does_not_discard_fresh_waf_cookie(self):
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(make_cookie('acw_sc__v2', 'fresh-cookie', 'api-gateway.leisu.com'))
        opener = CapturingOpener()
        stored_cookies = [{
            'name': 'other_cookie', 'value': 'value', 'domain': '.leisu.com',
            'path': '/', 'secure': False, 'expires': None,
        }]

        with patch.object(detail_scraper.os.path, 'exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=json.dumps(stored_cookies))):
            detail_scraper.fetch_html_with_bypass(
                'https://api-gateway.leisu.com/test',
                'api-gateway.leisu.com', opener, jar,
                headers={'User-Agent': 'test-agent'},
            )

        cookie_header = opener.requests[0].get_header('Cookie')
        self.assertEqual(cookie_header, 'acw_sc__v2=fresh-cookie')
        self.assertTrue(any(cookie.name == 'acw_sc__v2' and cookie.value == 'fresh-cookie' for cookie in jar))

    def test_server_time_is_cached_between_odds_requests(self):
        detail_scraper._SERVER_TIME_CACHE.update({'value': None, 'monotonic': 0.0})
        response = FakeResponse(body=b'{"data": 1234567890}')

        with patch.object(detail_scraper.urllib.request, 'urlopen', return_value=response) as urlopen:
            first = detail_scraper.get_cached_server_time()
            second = detail_scraper.get_cached_server_time()

        self.assertEqual(first, 1234567890)
        self.assertEqual(second, 1234567890)
        self.assertEqual(urlopen.call_count, 1)

    def test_focused_collector_uses_totals_market_type_three(self):
        self.assertEqual(focused_scheduler.TREND_TYPES, {'asia': 1, 'bs': 3})

    def test_focused_collector_sends_handicap_parameter(self):
        calls = []
        odds = {
            'cids': [22],
            'coop': {'22': {'name': 'Pinnacle', 'type': 0}},
            'asia': [], 'eu': [], 'bs': [],
        }

        def api_get(path, params=None):
            calls.append((path, params))
            return odds if path.endswith('odds_list') else []

        with patch.object(focused_scheduler, 'api_get', side_effect=api_get), \
             patch.object(focused_scheduler.time, 'sleep'):
            focused_scheduler.focused_pick('4556502', fixed_cids=[22])

        detail_params = [params for path, params in calls if path.endswith('odds_detail')]
        self.assertEqual([params['handicap'] for params in detail_params], ['1', '3'])
        self.assertTrue(all('type' not in params for params in detail_params))

    def test_focused_collector_reuses_server_time(self):
        focused_scheduler._SERVER_TIME_CACHE.update({'value': None, 'monotonic': 0.0})
        response = FakeResponse(body=b'{"data": 1234567890}')

        with patch.object(focused_scheduler, 'urlopen', return_value=response) as urlopen:
            focused_scheduler.get_server_time()
            focused_scheduler.get_server_time()

        self.assertEqual(urlopen.call_count, 1)

    def test_focused_collector_reuses_waf_cookie_and_fingerprint(self):
        challenge = b'<textarea id="renderData">challenge</textarea>'
        focused_scheduler._WAF_COOKIE = None
        responses = [
            FakeResponse(body=challenge),
            FakeResponse(body=b'{"data": {"ok": true}, "code": 0}'),
            FakeResponse(body=b'{"data": {"ok": true}, "code": 0}'),
        ]
        requests = []

        def urlopen(request, timeout=None):
            requests.append(request)
            return responses.pop(0)

        with patch.object(focused_scheduler, 'get_server_time', return_value=1234567890), \
             patch.object(focused_scheduler, 'urlopen', side_effect=urlopen), \
             patch.object(focused_scheduler, 'solve_waf', return_value='shared-cookie'):
            focused_scheduler.api_get('/first')
            focused_scheduler.api_get('/second')

        self.assertIsNone(requests[0].get_header('Cookie'))
        self.assertEqual(requests[1].get_header('Cookie'), 'acw_sc__v2=shared-cookie')
        self.assertEqual(requests[2].get_header('Cookie'), 'acw_sc__v2=shared-cookie')
        self.assertEqual(
            {request.get_header('User-agent') for request in requests},
            {focused_scheduler.SESSION_USER_AGENT},
        )

    def test_raw_odds_history_is_normalized_for_analysis(self):
        raw = [[1783533076, '93', '3.0', '-0.25', '0.23', 4, 0, '2-3']]

        normalized = detail_scraper.normalize_odds_detail_history(raw, 1)

        self.assertEqual(normalized, [{
            'change_time': 1783533076,
            'match_minute': '93',
            'home': 3.0,
            'line': '-0.25',
            'line_zh': '-0.25',
            'away': 0.23,
            'match_status': 4,
            'raw_flag': 0,
            'source': 'api_compact',
            'type': 1,
            'score': '2-3',
        }])

    def test_odds_detail_url_uses_handicap_parameter(self):
        url = detail_scraper.build_odds_detail_url('4556502', 2, 3)

        self.assertEqual(
            url,
            'https://api-gateway.leisu.com/v1/web/match/common/odds_detail'
            '?match_id=4556502&cid=2&handicap=3',
        )


if __name__ == '__main__':
    unittest.main()