import urllib.request
import urllib.error
import json
import time
import hashlib
import uuid
import subprocess
import os
import http.cookiejar
import base64
import zlib

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

def solve_waf_via_node(html, url):
    script_path = os.path.join(os.path.dirname(__file__), 'waf_solver.js')
    node_path = r"C:\Program Files\nodejs\node.exe"
    process = subprocess.Popen(
        [node_path, script_path, url],
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

def fetch_date(date_str):
    host_name = 'api-gateway.leisu.com'
    source_val = 'm_leisu'
    
    # 1. Fetch server time
    url_time = f'https://{host_name}/v1/web/public/time'
    req_time = urllib.request.Request(url_time, headers=HEADERS)
    
    t0 = time.time()
    with urllib.request.urlopen(req_time) as resp:
        server_time = json.loads(resp.read().decode('utf-8'))['data']
        
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
        
    node_path = r"C:\Program Files\nodejs\node.exe"
    process = subprocess.Popen(
        [node_path, 'encrypt_payload.js'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8'
    )
    stdout, _ = process.communicate()
    encrypted_payload = stdout.strip()
    
    url_api = f"https://{host_name}/v1/web/match/football/match_list?date={date_str}"
    
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    
    headers = HEADERS.copy()
    headers['Accept'] = f"application/json, text/plain, */*;;{encrypted_payload}"
    headers['Origin'] = 'https://m.leisu.com'
    headers['Referer'] = 'https://m.leisu.com/'
    headers['source'] = source_val
    
    req_api = urllib.request.Request(url_api, headers=headers)
    
    for attempt in range(5):
        try:
            with opener.open(req_api) as resp:
                headers_resp = resp.info()
                content_bytes = resp.read()
                if headers_resp.get('Content-Encoding') == 'gzip':
                    content_bytes = zlib.decompress(content_bytes, 15 + 32)
                html = content_bytes.decode('utf-8')
        except urllib.error.HTTPError as e:
            headers_resp = e.info()
            content_bytes = e.read()
            if headers_resp.get('Content-Encoding') == 'gzip':
                content_bytes = zlib.decompress(content_bytes, 15 + 32)
            html = content_bytes.decode('utf-8') if e.code in [400, 403, 500] else ""
            
        if '<textarea id="renderData"' in html:
            cookie_val = solve_waf_via_node(html, url_api)
            if cookie_val:
                waf_cookie = http.cookiejar.Cookie(
                    version=0, name='acw_sc__v2', value=cookie_val,
                    port=None, port_specified=False,
                    domain='api-gateway.leisu.com', domain_specified=True, domain_initial_dot=False,
                    path='/', path_specified=True,
                    secure=False, expires=None, discard=True, comment=None, comment_url=None, rest={}, rfc2109=False
                )
                cj.set_cookie(waf_cookie)
                
                req_api2 = urllib.request.Request(url_api, headers=headers)
                try:
                    with opener.open(req_api2) as resp2:
                        headers_resp2 = resp2.info()
                        content_bytes2 = resp2.read()
                        if headers_resp2.get('Content-Encoding') == 'gzip':
                            content_bytes2 = zlib.decompress(content_bytes2, 15 + 32)
                        content = content_bytes2.decode('utf-8')
                        if '<textarea id="renderData"' not in content:
                            res_json = json.loads(content)
                            if res_json.get('code', 0) >= 100:
                                return decrypt_data(res_json['data'], res_json['code'])
                            return res_json
                except Exception as e2:
                    print("  Second request error:", e2)
        else:
            if html.strip():
                res_json = json.loads(html)
                if res_json.get('code', 0) >= 100:
                    return decrypt_data(res_json['data'], res_json['code'])
                return res_json
            return None

def test():
    dates = ["20260701", "20260630", "20260629"]
    for d in dates:
        print(f"Fetching matches for date: {d}...")
        data = fetch_date(d)
        if data:
            matches = data.get('matches', [])
            print(f"  Successfully fetched! Total matches: {len(matches)}")
            if matches:
                # Print sample match
                print("  Sample match:", matches[0])
        else:
            print(f"  Failed to fetch for date: {d}")

if __name__ == '__main__':
    test()
