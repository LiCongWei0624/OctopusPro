# -*- coding: utf-8 -*-
import time
import os
import json
import uuid
import hashlib
import subprocess
import base64
import zlib
from playwright.sync_api import sync_playwright

match_id = "4467734"  # 利恩 vs 阿萨纳 (完赛挪甲)
url = f"https://odds.leisu.com/3in1-{match_id}"

print(f"正在启动有头 Chrome 浏览器 Playwright 访问: {url} ...")

# 1. 在 Python 里使用 Node 计算 Accept 签名
SALT = "uHhANonwd4UdpzOdsUqUsnl5PjurM877"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# 动态获取服务器时间
import urllib.request
url_time = 'https://api-gateway.leisu.com/v1/web/public/time'
req_time = urllib.request.Request(url_time, headers=HEADERS)
server_time = int(time.time())
try:
    with urllib.request.urlopen(req_time) as resp:
        server_time = json.loads(resp.read().decode('utf-8'))['data']
except Exception as e:
    print("获取服务器时间失败，使用本地时间:", e)

r_val = server_time + 10
c_val = uuid.uuid4().hex
auth_path = "/v1/web/match/common/odds_detail"

l_str = f"{auth_path}-{r_val}-{c_val}-0-{SALT}"
u_val = hashlib.md5(l_str.encode('utf-8')).hexdigest()
auth_data = f"{r_val}-{c_val}-0-{u_val}"

payload = {"auth_data": auth_data, "source": "m_leisu"}
payload_str = json.dumps(payload, separators=(',', ':'))

# 使用 node 加密
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
enc_script_temp = os.path.join(os.path.dirname(__file__), 'temp_pc_sig.js')
with open(enc_script_temp, 'w', encoding='utf-8') as f_temp:
    f_temp.write(node_enc_script)
    
process_node = subprocess.Popen(["node", enc_script_temp], stdout=subprocess.PIPE, text=True)
stdout_node, _ = process_node.communicate()
encrypted_payload = stdout_node.strip()

try:
    os.remove(enc_script_temp)
except:
    pass
    
accept_header_val = f"application/json, text/plain, */*;;{encrypted_payload}"
api_target = f"https://api-gateway.leisu.com/v1/web/match/common/odds_detail?id={match_id}&cid=3&type=1"

print(f"计算所得 API: {api_target}")
print(f"计算所得 Accept: {accept_header_val}")

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # 绕过阿里 webdriver 检测特征
        page.add_init_script("""
        () => {
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
        }
        """)
        
        print("打开 3in1 网页以通过阿里 WAF 并设置授权 Cookie...")
        page.goto(url, timeout=30000)
        
        print("等待 8 秒让 WAF 计算并渲染页面完毕...")
        page.wait_for_timeout(8000)
        
        # 2. 核心黑科技：在 odds.leisu.com 页面 Console 中通过 CORS Fetch api-gateway.leisu.com 接口
        # 绝不手动设置 'Origin' 头以防被浏览器安全机制拒绝，且带上 credentials: 'include' 自动传递 Cookie
        fetch_js = f"""
        async () => {{
            try {{
                const r = await fetch('{api_target}', {{
                    method: 'GET',
                    credentials: 'include',
                    headers: {{
                        'Accept': '{accept_header_val}',
                        'source': 'm_leisu'
                    }}
                }});
                const resJson = await r.json();
                return {{ success: true, status: r.status, data: resJson }};
            }} catch(e) {{
                return {{ success: false, error: e.message }};
            }}
        }}
        """
        
        print("正在 Console 里执行 CORS Fetch 走势数据...")
        fetch_res = page.evaluate(fetch_js)
        print("Console Fetch 响应结果:")
        print(json.dumps({k: (v if k != 'data' else 'data_exists') for k, v in fetch_res.items()}, ensure_ascii=False))
        
        if fetch_res.get('success'):
            res_data = fetch_res['data']
            code = res_data.get('code', 0)
            data_val = res_data.get('data')
            print(f"接口返回 code: {code}")
            
            if data_val and isinstance(data_val, str) and 100 <= code <= 130:
                offset = code - 100
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
                decompressed_json = json.loads(decompressed)
                print("\n🎉🎉🎉【恭喜！Console CORS Fetch 并解密历史变盘成功！】")
                print(f"数据总字符数: {len(decompressed)}")
                print(f"历史变盘项总数: {len(decompressed_json)}")
                print("前 3 条走势变盘记录样例:")
                print(json.dumps(decompressed_json[:3], ensure_ascii=False, indent=2))
            else:
                print("未获得密文数据或无需解密:", res_data)
        else:
            print("Fetch 报错:", fetch_res.get('error'))
            
        print("\n挂起 10 秒供交互观察...")
        page.wait_for_timeout(10000)
        
        # 截图留存
        out_img = os.path.join(os.path.dirname(__file__), 'pc_shujufenxi_screenshot.png')
        page.screenshot(path=out_img)
        print(f"页面截图已存为: {out_img}")
        
        browser.close()
except Exception as e:
    print("Playwright 异常:", e)
