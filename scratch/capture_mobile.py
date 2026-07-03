import time
import os
import subprocess
import json
import urllib.request
import urllib.error
from playwright.sync_api import sync_playwright

match_id = "4467734"
url = f"https://m.leisu.com/live?id={match_id}"
NODE_PATH = "node"

def solve_waf_via_node(html, url_val, user_agent):
    script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'waf_solver.js')
    process = subprocess.Popen(
        [NODE_PATH, script_path, url_val, user_agent],
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

print("正在破解 WAF Cookie...")
user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
req = urllib.request.Request(url, headers={'User-Agent': user_agent})
html_waf = ""
try:
    with urllib.request.urlopen(req) as resp:
        html_waf = resp.read().decode('utf-8')
except urllib.error.HTTPError as e:
    html_waf = e.read().decode('utf-8')
except Exception as e:
    pass

cookie_val = solve_waf_via_node(html_waf, url, user_agent)
print("WAF Cookie:", cookie_val)

try:
    with sync_playwright() as p:
        iphone = p.devices['iPhone 12']
        # 以有头模式启动，以保障最完美的渲染
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(**iphone)
        
        if cookie_val:
            context.add_cookies([{
                "name": "acw_sc__v2",
                "value": cookie_val,
                "domain": "m.leisu.com",
                "path": "/"
            }])
            
        page = context.new_page()
        page.goto(url, timeout=30000)
        print("等待 8 秒渲染...")
        page.wait_for_timeout(8000)
        
        # 保存截图到 scratch 目录
        out_img = os.path.join(os.path.dirname(__file__), 'mobile_page_screenshot.png')
        page.screenshot(path=out_img)
        print(f"截图保存成功: {out_img}")
        
        # 顺便把 DOM 里的 textContent 打印部分出来
        text = page.evaluate("() => document.body.innerText")
        print("\n页面 innerText 前 500 个字：")
        print(text[:500])
        
        browser.close()
except Exception as e:
    print("异常:", e)
