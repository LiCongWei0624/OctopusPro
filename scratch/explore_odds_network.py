import time
import json
import os
import subprocess
import urllib.request
import urllib.error
from playwright.sync_api import sync_playwright

match_id = "4459725"
url = f"https://live.leisu.com/shujufenxi-{match_id}"
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

print("正在破解 WAF...")
user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
if not cookie_val:
    print("WAF Cookie 求解失败")
    exit(1)
print("解出 WAF Cookie:", cookie_val)

responses = []

def handle_response(response):
    req = response.request
    url_str = response.url
    # 捕获所有 api-gateway 接口
    if "api-gateway" in url_str or "odds" in url_str or "trend" in url_str:
        try:
            body = response.text()
            responses.append({
                "url": url_str,
                "status": response.status,
                "method": req.method,
                "body_snippet": body[:500] if body else None
            })
        except Exception:
            pass

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=user_agent)
        context.add_cookies([{
            "name": "acw_sc__v2",
            "value": cookie_val,
            "domain": "live.leisu.com",
            "path": "/"
        }])
        page = context.new_page()
        page.on("response", handle_response)
        page.goto(url, timeout=25000)
        page.wait_for_timeout(3000)
        print("网页加载完毕。")
        
        # 1. 寻找包含“指数”或者“三合一”的 Tab 选项卡按钮并点击
        tab_click_js = """
        () => {
            const tabs = Array.from(document.querySelectorAll('a, li, div, span')).filter(el => {
                const text = el.innerText || '';
                return text.includes('指数') || text.includes('赔率');
            });
            if (tabs.length > 0) {
                // 打印找到的 Tab 选项卡标签名和类名
                const details = tabs.map(t => `${t.tagName}.${t.className} (${t.innerText})`);
                // 点击包含“指数”的第一个元素
                tabs[0].click();
                return { "success": true, "found": details };
            }
            return { "success": false, "found": [] };
        }
        """
        tab_res = page.evaluate(tab_click_js)
        print("切换 Tab 动作结果:", json.dumps(tab_res, indent=2, ensure_ascii=False))
        page.wait_for_timeout(3000)
        
        # 2. 模拟点击指数表格格子
        click_probe = """
        () => {
            const elements = Array.from(document.querySelectorAll('span, td, div')).filter(el => {
                const text = el.innerText || '';
                return /^[0-9]\\.[0-9]+/i.test(text.trim()) || el.className.includes('odds') || el.className.includes('trend');
            });
            
            if (elements.length > 0) {
                elements.slice(0, 15).forEach(el => {
                    try { el.click(); } catch(e){}
                });
                return `Clicked ${elements.length} elements.`;
            }
            return "No odds elements found after tab switch.";
        }
        """
        click_res = page.evaluate(click_probe)
        print("点击动作结果:", click_res)
        
        time.sleep(5)
        
        print(f"\n拦截到 API 走势请求 {len(responses)} 个：")
        for idx, r in enumerate(responses):
            print(f"[{idx+1}] {r['method']} -> {r['url']}")
            print(f"    Status: {r['status']}")
            print(f"    Body snippet: {r['body_snippet']}")
            print("-" * 120)
            
        browser.close()
except Exception as e:
    print("异常:", e)
