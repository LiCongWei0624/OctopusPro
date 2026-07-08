# -*- coding: utf-8 -*-
import urllib.request
import urllib.error
import json
import time
import hashlib
import uuid
import subprocess
import os
import shutil
import http.cookiejar
import base64
import zlib

def find_node_executable():
    path = shutil.which("node")
    if path:
        return path
    if os.path.exists(r"D:\WorkApp\nodejs\node.exe"):
        return r"D:\WorkApp\nodejs\node.exe"
    if os.path.exists(r"C:\Program Files\nodejs\node.exe"):
        return r"C:\Program Files\nodejs\node.exe"
    return "node"

NODE_PATH = find_node_executable()

from urllib.parse import urlparse

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}

SALT = "uHhANonwd4UdpzOdsUqUsnl5PjurM877"

def md5(s):
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def caesar_decrypt(s, offset):
    res = ""
    for c in s:
        code = ord(c)
        if 65 <= code <= 90:
            res += chr((code - 65 - offset + 26) % 26 + 65)
        elif 97 <= code <= 122:
            res += chr((code - 97 - offset + 26) % 26 + 97)
        else:
            res += c
    return res

def decrypt_data(encrypted_data, code_val):
    offset = code_val - 100
    caesar_str = caesar_decrypt(encrypted_data, offset)
    decoded_bytes = base64.b64decode(caesar_str)
    decompressed = zlib.decompress(decoded_bytes, 15 + 32)
    return json.loads(decompressed.decode('utf-8'))

def solve_waf_via_node(html, url, user_agent):
    script_path = os.path.join(os.path.dirname(__file__), 'waf_solver.js')
    process = subprocess.Popen(
        [NODE_PATH, script_path, url, user_agent],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8'
    )
    stdout, stderr = process.communicate(input=html)
    if process.returncode != 0:
        return None
    try:
        res = json.loads(stdout.strip())
        if res.get('success'):
            return res.get('cookie')
    except Exception:
        pass
    return None

def fetch_matches_for_tier(date_str, n_val, cj=None):
    host_name = 'api-gateway.leisu.com'
    source_val = 'm_leisu'
    
    # 1. Fetch server time
    url_time = f'https://{host_name}/v1/web/public/time'
    req_time = urllib.request.Request(url_time, headers=HEADERS)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req_time) as resp:
            server_time = json.loads(resp.read().decode('utf-8'))['data']
    except Exception as e:
        print(f"Error fetching server time: {e}")
        return None
        
    dt = time.time() - t0
    r = server_time + 10 + int(dt)
    
    c_val = uuid.uuid4().hex
    i = "/v1/web/match/football/match_list"
    
    l = f"{i}-{r}-{c_val}-0-{SALT}"
    u = md5(l)
    auth_data = f"{r}-{c_val}-0-{u}"
    
    payload = {
        "auth_data": auth_data,
        "source": source_val
    }
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    # Run Node to encrypt payload
    node_enc_script = f"""
const crypto = require('crypto');
function encrypt(text) {{
    const key = Buffer.from('kw@h*8gCIn$8X#df', 'utf8');
    const cipher = crypto.createCipheriv('aes-128-ecb', key, null);
    let encrypted = cipher.update(text, 'utf8', 'base64');
    encrypted += cipher.final('base64');
    return encrypted.replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=/g, '');
}}
console.log(encrypt('{payload_str}'));
"""
    with open('encrypt_payload.js', 'w', encoding='utf-8') as f:
        f.write(node_enc_script)
        
    process = subprocess.Popen(
        [NODE_PATH, 'encrypt_payload.js'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8'
    )
    stdout, _ = process.communicate()
    encrypted_payload = stdout.strip()
    
    url_api = f"https://{host_name}/v1/web/match/football/match_list?date={date_str}&n={n_val}"
    
    if cj is None:
        cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    
    headers = HEADERS.copy()
    headers['Accept'] = f"application/json, text/plain, */*;;{encrypted_payload}"
    headers['Origin'] = 'https://m.leisu.com'
    headers['Referer'] = 'https://m.leisu.com/'
    headers['source'] = source_val
    
    req_api = urllib.request.Request(url_api, headers=headers)
    
    try:
        with opener.open(req_api) as resp:
            headers_resp = resp.info()
            content_bytes = resp.read()
            if headers_resp.get('Content-Encoding') == 'gzip':
                content_bytes = zlib.decompress(content_bytes, 15 + 32)
            html = content_bytes.decode('utf-8')
            real_url = resp.geturl()
            real_domain = urlparse(real_url).netloc
    except urllib.error.HTTPError as e:
        headers_resp = e.info()
        content_bytes = e.read()
        if headers_resp.get('Content-Encoding') == 'gzip':
            content_bytes = zlib.decompress(content_bytes, 15 + 32)
        html = content_bytes.decode('utf-8') if e.code in [400, 403, 500] else ""
        real_url = url_api
        real_domain = 'api-gateway.leisu.com'
        
    if 'renderData' in html:
        user_agent = headers.get('User-Agent', '')
        cookie_val = solve_waf_via_node(html, real_url, user_agent)
        if cookie_val:
            # 重试前清空 cj 脏数据，防范过期 Cookie 重写覆盖
            cj.clear()
            
            waf_cookie = http.cookiejar.Cookie(
                version=0, name='acw_sc__v2', value=cookie_val,
                port=None, port_specified=False,
                domain=real_domain, domain_specified=True, domain_initial_dot=real_domain.startswith('.'),
                path='/', path_specified=True,
                secure=False, expires=None, discard=True, comment=None, comment_url=None, rest={}, rfc2109=False
            )
            cj.set_cookie(waf_cookie)
            
            req_api2 = urllib.request.Request(real_url, headers=headers)
            try:
                with opener.open(req_api2) as resp2:
                    headers_resp2 = resp2.info()
                    content_bytes2 = resp2.read()
                    if headers_resp2.get('Content-Encoding') == 'gzip':
                        content_bytes2 = zlib.decompress(content_bytes2, 15 + 32)
                    content = content_bytes2.decode('utf-8')
                    if '<textarea id="renderData"' not in content:
                        res_json = json.loads(content)
                        if 100 <= res_json.get('code', 0) <= 130:
                            return decrypt_data(res_json['data'], res_json['code'])
                        return res_json
            except Exception as e2:
                print(f"Error on second WAF request: {e2}")
    else:
        if html.strip():
            res_json = json.loads(html)
            if 100 <= res_json.get('code', 0) <= 130:
                return decrypt_data(res_json['data'], res_json['code'])
            return res_json
    return None

def fetch_matches(date_str, n_values=[1, 2, 3, 4, 5, 7]):
    """
    Fetches unique matches for a given date.
    By default, n_values=[1, 2] fetches major matches (Tier 1 & Tier 2).
    If you want all matches (including lower-tier small matches), use n_values=[1, 2, 3, 4, 5, 7].
    """
    from concurrent.futures import ThreadPoolExecutor
    all_matches = {}
    events_map = {}
    
    if not n_values:
        return []
        
    cj = http.cookiejar.CookieJar()
    
    # 1. 预热第一志愿，先单独拉取首个层级获取并建立全局 WAF Cookie
    first_n = n_values[0]
    first_data = fetch_matches_for_tier(date_str, first_n, cj=cj)
    if first_data and isinstance(first_data, dict):
        matches = first_data.get('matches', [])
        events = first_data.get('events', {})
        events_map.update(events)
        for m in matches:
            all_matches[m['id']] = m
            
    # 2. 剩余层级启用多线程并发拉取，直接复用已解出的 WAF Cookie
    remaining_ns = n_values[1:]
    if remaining_ns:
        def worker(n_val):
            # 错开极短时间内的并发请求以防接口频率限制
            time.sleep(0.1)
            return fetch_matches_for_tier(date_str, n_val, cj=cj)
            
        with ThreadPoolExecutor(max_workers=len(remaining_ns)) as executor:
            results = executor.map(worker, remaining_ns)
            
        for data in results:
            if data and isinstance(data, dict):
                matches = data.get('matches', [])
                events = data.get('events', {})
                events_map.update(events)
                for m in matches:
                    all_matches[m['id']] = m
        
    # Format and attach competition info to each match
    formatted_matches = []
    for m in all_matches.values():
        comp_id = str(m.get('comp_id'))
        comp_info = events_map.get(comp_id, {})
        
        home_scores = m.get('home', {}).get('scores', [])
        away_scores = m.get('away', {}).get('scores', [])
        
        half_score = ""
        penalty_score = ""
        status = m.get('status', 1)
        
        # Status code: 3=half-time, 4=second half, 5=overtime, 7=penalties, 8=finished
        if len(home_scores) > 1 and len(away_scores) > 1:
            if status in [3, 4, 5, 7, 8]:
                half_score = f"{home_scores[1]}-{away_scores[1]}"
                
        if len(home_scores) > 6 and len(away_scores) > 6:
            if status in [7, 8] and (home_scores[6] > 0 or away_scores[6] > 0):
                penalty_score = f"{home_scores[6]}-{away_scores[6]}"
                
        formatted_matches.append({
            'match_id': m.get('id'),
            'competition': comp_info.get('name', 'Unknown'),
            'competition_zh_full': comp_info.get('full_name_zh', ''),
            'match_time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(m.get('match_time'))),
            'status': status,
            'home_team': m.get('home', {}).get('name', 'Unknown'),
            'home_team_en': m.get('home', {}).get('name_en', ''),
            'away_team': m.get('away', {}).get('name', 'Unknown'),
            'away_team_en': m.get('away', {}).get('name_en', ''),
            'home_score': home_scores[0] if home_scores else 0,
            'away_score': away_scores[0] if away_scores else 0,
            'half_score': half_score,
            'penalty_score': penalty_score,
        })
        
    return formatted_matches

if __name__ == '__main__':
    # Test for July 1st, 2026
    date_to_test = "20260701"
    print(f"Fetching matches for {date_to_test}...")
    matches_list = fetch_matches(date_to_test, n_values=[1, 2, 3, 4, 5, 7])
    print(f"Total unique matches found: {len(matches_list)}")
    if matches_list:
        print("\nFirst 5 matches sample:")
        print(json.dumps(matches_list[:5], indent=2, ensure_ascii=False))
