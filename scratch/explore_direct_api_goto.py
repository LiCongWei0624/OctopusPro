# -*- coding: utf-8 -*-
import time
import os
import json
import base64
import zlib
from playwright.sync_api import sync_playwright

match_id = "4467734"  # 利恩 vs 阿萨纳 (完赛挪甲)
cid = "3"   # 皇冠
type_val = "1"  # 1-让球, 3-大小球, 2-胜平负(欧指)

# 1. 动态计算 Accept 签名
import urllib.request
import uuid
import hashlib

SALT = "uHhANonwd4UdpzOdsUqUsnl5PjurM877"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

print("正在获取服务器时间以计算签名...")
url_time = 'https://api-gateway.leisu.com/v1/web/public/time'
req_time = urllib.request.Request(url_time, headers=HEADERS)
server_time = int(time.time())
try:
    with urllib.request.urlopen(req_time) as resp:
        server_time = json.loads(resp.read().decode('utf-8'))['data']
except Exception as e:
    print("获取时间失败，使用本地时间:", e)

r = server_time + 10
c_val = uuid.uuid4().hex
auth_path = "/v1/web/match/common/odds_detail"
l = f"{auth_path}-{r}-{c_val}-0-{SALT}"
u = hashlib.md5(l.encode('utf-8')).hexdigest()
auth_data = f"{r}-{c_val}-0-{u}"

payload = {"auth_data": auth_data, "source": "m_leisu"}
payload_str = json.dumps(payload, separators=(',', ':'))

# 使用 node 加密 payload 得到 Accept 签名后半截
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
enc_script_path = os.path.join(os.path.dirname(__file__), 'temp_direct_enc.js')
with open(enc_script_path, 'w', encoding='utf-8') as f:
    f.write(node_enc_script)
    
import subprocess
process = subprocess.Popen(["node", enc_script_path], stdout=subprocess.PIPE, text=True)
stdout, _ = process.communicate()
encrypted_payload = stdout.strip()

if os.path.exists(enc_script_path):
    os.remove(enc_script_path)

accept_header_val = f"application/json, text/plain, */*;;{encrypted_payload}"
api_target = f"https://api-gateway.leisu.com/v1/web/match/common/odds_detail?id={match_id}&cid={cid}&type={type_val}"

print(f"生成的 API 目标 URL: {api_target}")
print(f"生成的 Accept 签名: {accept_header_val}")

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # 绕过阿里 webdriver 检测
        page = context.new_page()
        page.add_init_script("""
        () => {
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
        }
        """)
        
        # 核心黑科技：通过 extra_http_headers 把我们计算出来的 Accept 签名和 source 强制种到这个 page 的每一次请求中！
        page.set_extra_http_headers({
            "Accept": accept_header_val,
            "source": "m_leisu"
        })
        
        print("\n正在通过 Playwright 直接加载 API URL...")
        page.goto(api_target, timeout=30000)
        
        print("等待 8 秒确保 WAF 滑块/跳转完成，并且页面显示 JSON...")
        page.wait_for_timeout(8000)
        
        # 从页面获取纯文本（一般 Chrome 对 JSON 会自动包在 <pre> 里或者直接在 body 中）
        content = page.locator('body').inner_text()
        print("浏览器页面内返回的文本内容预览:")
        print(content[:600])
        
        # 尝试解密
        try:
            res_json = json.loads(content)
            code_val = res_json.get('code', 0)
            data_val = res_json.get('data')
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
                decompressed_json = json.loads(decompressed)
                print("\n🎉🎉🎉【恭喜！Playwright 直接加载 API 并完美解密走势成功！】")
                print(f"数据总字符长度: {len(decompressed)}")
                print(f"历史走势记录个数: {len(decompressed_json)}")
                print("前 3 条走势变盘记录样例:")
                print(json.dumps(decompressed_json[:3], ensure_ascii=False, indent=2))
            else:
                print("API 返回格式不匹配或无需解密:", res_json)
        except Exception as e_dec:
            print("Python 解密报错:", e_dec)
            
        browser.close()
except Exception as e:
    print("Playwright 异常:", e)
