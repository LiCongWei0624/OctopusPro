import time
import os
import subprocess
import json
import urllib.request
import urllib.error
from playwright.sync_api import sync_playwright

match_id = "4459725"
url = f"https://m.leisu.com/live/{match_id}"
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

print("正在破解 WAF Cookie...", flush=True)
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
print("解出 WAF Cookie:", cookie_val, flush=True)

# 实时 Response 监控处理器
def handle_response(response):
    req_obj = response.request
    url_str = response.url
    # 只要有 odds, trend, history, list, common 相关的接口
    if "api-gateway" in url_str or "odds" in url_str or "trend" in url_str or "history" in url_str:
        print(f"\n🚀 【拦截到 API 请求】 -> {req_obj.method} {url_str}", flush=True)
        print(f"   HTTP Status: {response.status}", flush=True)
        try:
            body = response.text()
            print(f"   Body Snippet: {body[:300]}", flush=True)
        except Exception as ex:
            print(f"   [无法提取 Body]: {str(ex)}", flush=True)

try:
    with sync_playwright() as p:
        iphone = p.devices['iPhone 12']
        # 弹窗显示，有头模式
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(**iphone)
        
        if cookie_val:
            context.add_cookies([{
                "name": "acw_sc__v2",
                "value": cookie_val,
                "domain": "m.leisu.com",
                "path": "/"
            }])
            
        page = context.new_page()
        page.on("response", handle_response)
        
        print(f"正在打开手机版网页: {url}", flush=True)
        page.goto(url, timeout=30000)
        
        print("\n" + "="*80, flush=True)
        print("【手动操作嗅探提示】", flush=True)
        print("1. 手机版浏览器已在您的桌面上弹出！", flush=True)
        print("2. 请在页面上，点击“指数”Tab 栏，并点击任何一个公司的赔率拉起历史走势。", flush=True)
        print("3. 当您在浏览器中点击时，脚本控制台将【实时】为您打印出拦截到的接口和参数！", flush=True)
        print("4. 我们挂起 120 秒，您可以尽情操作。", flush=True)
        print("="*80 + "\n", flush=True)
        
        # 挂起 120 秒
        time.sleep(120)
        
        browser.close()
except Exception as e:
    print("异常:", e, flush=True)
