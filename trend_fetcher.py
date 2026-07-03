# -*- coding: utf-8 -*-
import sys
import os
import json
import uuid
import hashlib
import time
import base64
import zlib
import urllib.request
import subprocess
import shutil

# 确保能导入 detail_scraper 里的 solver
sys.path.append(os.path.dirname(__file__))

# 这里的 SALT 应该与 detail_scraper.py 中一致
SALT = "uHhANonwd4UdpzOdsUqUsnl5PjurM877"

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

def solve_waf_via_node(html, url, user_agent):
    temp_path = os.path.join(os.path.dirname(__file__), f"temp_waf_{uuid.uuid4().hex[:8]}.html")
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(html)
            
        script_path = os.path.join(os.path.dirname(__file__), 'waf_solver.js')
        process = subprocess.Popen(
            [NODE_PATH, script_path, url, user_agent, temp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        stdout, stderr = process.communicate(timeout=5)
        
        if process.returncode == 0:
            res = json.loads(stdout.strip())
            if res.get('success'):
                return res.get('cookie')
    except Exception as e:
        print("Solve WAF via Node subprocess exception:", e, file=sys.stderr)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
    return None

def encrypt_payload_python(text):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    key = b'kw@h*8gCIn$8X#df'
    pad_len = 16 - (len(text) % 16)
    padded = text + chr(pad_len) * pad_len
    
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    encryptor = cipher.encryptor()
    ct = encryptor.update(padded.encode('utf-8')) + encryptor.finalize()
    res = base64.b64encode(ct).decode('utf-8')
    return res.replace('+', '-').replace('/', '_').replace('=', '')

def main():
    if len(sys.argv) < 4:
        print(json.dumps({"error": "Missing arguments"}))
        return
        
    match_id = sys.argv[1]
    cid = sys.argv[2]
    type_val = sys.argv[3]
    
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    # 1. 获取服务器时间
    server_time = int(time.time())
    try:
        url_time = 'https://api-gateway.leisu.com/v1/web/public/time'
        req_time = urllib.request.Request(url_time, headers={
            'User-Agent': user_agent
        })
        with urllib.request.urlopen(req_time, timeout=5) as resp:
            server_time = json.loads(resp.read().decode('utf-8'))['data']
    except Exception:
        pass
        
    auth_path = "/v1/web/match/common/odds_detail"
    r = server_time + 10
    c_val = uuid.uuid4().hex
    
    l = f"{auth_path}-{r}-{c_val}-0-{SALT}"
    u = hashlib.md5(l.encode('utf-8')).hexdigest()
    auth_data = f"{r}-{c_val}-0-{u}"
    
    payload = {"auth_data": auth_data, "source": "pc_leisu"}
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    # 2. 纯 Python 极速加密 payload
    try:
        encrypted_payload = encrypt_payload_python(payload_str)
    except Exception as e_enc:
        print(json.dumps({"error": f"Encryption failed: {e_enc}"}))
        return
        
    accept_header_val = f"application/json, text/plain, */*;;{encrypted_payload}"
    api_target = f"https://odds.leisu.com/v1/web/match/common/odds_detail?id={match_id}&cid={cid}&type={type_val}"
    
    # 3. 启动 Playwright 并拉取
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-gpu',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-setuid-sandbox',
                    '--disable-gpu-sandbox'
                ]
            )
            context = browser.new_context(user_agent=user_agent)
            page = context.new_page()
            
            page.add_init_script("""
            () => {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = { runtime: {} };
            }
            """)
            
            url_3in1 = f"https://odds.leisu.com/3in1-{match_id}"
            page.goto(url_3in1, timeout=30000)
            
            html_3in1 = page.content()
            if '<textarea id="renderData"' in html_3in1:
                cookie_3in1 = solve_waf_via_node(html_3in1, url_3in1, user_agent)
                if cookie_3in1:
                    context.add_cookies([{
                        "name": "acw_sc__v2",
                        "value": cookie_3in1,
                        "domain": ".leisu.com",
                        "path": "/"
                    }])
                    page.goto(url_3in1, timeout=30000)
                    
            page.wait_for_selector('.main-content-vue', timeout=10000)
            
            # 4. 发起 Fetch
            fetch_js = f"""
            async () => {{
                try {{
                    const r = await fetch('{api_target}', {{
                        method: 'GET',
                        headers: {{
                            'Accept': '{accept_header_val}',
                            'source': 'pc_leisu'
                        }}
                    }});
                    const resText = await r.text();
                    return {{ success: true, status: r.status, data: resText }};
                }} catch(e) {{
                    return {{ success: false, error: e.message }};
                }}
            }}
            """
            res = page.evaluate(fetch_js)
            if browser:
                browser.close()
                
            if res.get('success'):
                content = res['data']
                res_json = json.loads(content)
                data_val = res_json.get('data')
                code_val = res_json.get('code', 0)
                
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
                    print(decompressed) # 打印解密明文
                else:
                    print(json.dumps({"error": f"API Error Code {code_val}. Content: {content}"}))
            else:
                print(json.dumps({"error": res.get('error')}))
        except Exception as e:
            if browser:
                try:
                    browser.close()
                except:
                    pass
            print(json.dumps({"error": str(e)}))

if __name__ == '__main__':
    main()
