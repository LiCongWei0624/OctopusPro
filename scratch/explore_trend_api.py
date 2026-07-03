# -*- coding: utf-8 -*-
import urllib.request
import urllib.error
import json
import uuid
import hashlib
import os
import subprocess
import base64
import zlib
import shutil
import time

match_id = "4467734"  # 利恩 vs 阿萨纳 (完赛挪甲)
cid = "3"   # 皇冠
type_val = "1"  # 1-让球

print(f"正在发起直连 odds.leisu.com (主站域名) 的历史赔率走势请求...")

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
SALT = "uHhANonwd4UdpzOdsUqUsnl5PjurM877"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'Origin': 'https://odds.leisu.com',
    'Referer': 'https://odds.leisu.com/',
}

def solve_waf_via_node(html, url, user_agent):
    script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'waf_solver.js')
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
        print("WAF JS Solver error:", stderr)
        return None
    try:
        res = json.loads(stdout.strip())
        if res.get('success'):
            return res.get('cookie')
    except Exception as e:
        print("WAF JSON parse error:", e, stdout)
    return None

# 1. 获取服务器时间 (从 odds.leisu.com 或者是 api-gateway)
url_time = 'https://api-gateway.leisu.com/v1/web/public/time'
req_time = urllib.request.Request(url_time, headers=HEADERS)
try:
    with urllib.request.urlopen(req_time) as resp:
        server_time = json.loads(resp.read().decode('utf-8'))['data']
except Exception as e:
    print("获取服务器时间失败:", e)
    server_time = int(time.time())

# 2. 计算签名
r = server_time + 10
c_val = uuid.uuid4().hex

endpoint_path = f"/v1/web/match/common/odds_detail?id={match_id}&cid={cid}&type={type_val}"
auth_path = "/v1/web/match/common/odds_detail"

l = f"{auth_path}-{r}-{c_val}-0-{SALT}"
u = hashlib.md5(l.encode('utf-8')).hexdigest()
auth_data = f"{r}-{c_val}-0-{u}"

payload = {"auth_data": auth_data, "source": "pc_leisu"}
payload_str = json.dumps(payload, separators=(',', ':'))

# 3. Node.js 加密 payload
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
enc_script_path = os.path.join(os.path.dirname(__file__), 'temp_trend_enc5.js')
with open(enc_script_path, 'w', encoding='utf-8') as f:
    f.write(node_enc_script)
    
process = subprocess.Popen([NODE_PATH, enc_script_path], stdout=subprocess.PIPE, text=True)
stdout, _ = process.communicate()
encrypted_payload = stdout.strip()

if os.path.exists(enc_script_path):
    os.remove(enc_script_path)
    
# 4. 替换域名为主站域名 odds.leisu.com 发起请求！
url_api = f"https://odds.leisu.com{endpoint_path}"
print("目标 API URL:", url_api)

headers = dict(HEADERS)
headers['Accept'] = f"application/json, text/plain, */*;;{encrypted_payload}"
headers['source'] = 'pc_leisu'

opener = urllib.request.build_opener()
req_api = urllib.request.Request(url_api, headers=headers)
html = ""
try:
    with opener.open(req_api, timeout=8) as resp:
        content_bytes = resp.read()
        if resp.info().get('Content-Encoding') == 'gzip':
            content_bytes = zlib.decompress(content_bytes, 15 + 32)
        html = content_bytes.decode('utf-8')
except urllib.error.HTTPError as e:
    content_bytes = e.read()
    if e.info().get('Content-Encoding') == 'gzip':
        content_bytes = zlib.decompress(content_bytes, 15 + 32)
    html = content_bytes.decode('utf-8')
    
# 5. 如果遇到 WAF 挑战，则调用 JS Solver 求解并重试 (只带 WAF Cookie)
if '<textarea id="renderData"' in html:
    print("遇到 WAF 挑战页！正在调用 WAF 沙箱求解 Cookie...")
    user_agent = headers.get('User-Agent', '')
    cookie_val = solve_waf_via_node(html, url_api, user_agent)
    if cookie_val:
        print("WAF Cookie 求解成功:", cookie_val)
        
        headers['Cookie'] = f"acw_sc__v2={cookie_val}"
        req_api2 = urllib.request.Request(url_api, headers=headers)
        try:
            with opener.open(req_api2, timeout=8) as resp2:
                content_bytes2 = resp2.read()
                if resp2.info().get('Content-Encoding') == 'gzip':
                    content_bytes2 = zlib.decompress(content_bytes2, 15 + 32)
                html = content_bytes2.decode('utf-8')
        except Exception as e2:
            print("WAF 求解后请求依然失败:", e2)
    else:
        print("WAF 求解失败！")
        
# 6. 解析并解密返回数据
if html and '<textarea id="renderData"' not in html:
    try:
        res_json = json.loads(html)
        code_val = res_json.get('code', 0)
        data_val = res_json.get('data')
        print(f"最终请求成功！返回 code: {code_val}")
        
        if data_val and isinstance(data_val, str) and 100 <= code_val <= 130:
            offset = code_val - 100
            res_caesar = ""
            for c in data_val:
                code_char = ord(c)
                if 65 <= code_char <= 90:
                    res_caesar += chr((code_char - 65 - offset + 26) % 26 + 65)
                elif 97 <= code_char <= 122:
                    res_caesar += chr((code_char - 97 - offset + 26) % 26 + 97)
                else:
                    res_caesar += c
                    
            decoded_bytes = base64.b64decode(res_caesar)
            decompressed = zlib.decompress(decoded_bytes, 15 + 32).decode('utf-8')
            decrypted_json = json.loads(decompressed)
            print("\n🎉【恭喜！主站域名直连走势成功并完美解密！】")
            print(f"数据总长度: {len(decompressed)} 字符")
            print("前 3 条走势历史点样本:")
            print(json.dumps(decrypted_json[:3], ensure_ascii=False, indent=2))
            print(f"总计获得走势历史点数: {len(decrypted_json)}")
        else:
            print("接口返回数据错误或无需解密:", res_json)
    except Exception as je:
        print("解析 JSON/解密报错:", je)
        print("返回的 HTML 预览:", html[:500])
else:
    print("未获取到有效的 API 返回体，HTML 预览:", html[:300])
