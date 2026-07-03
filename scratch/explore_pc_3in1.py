import time
import json
import os
import subprocess
import urllib.request
import urllib.error
from playwright.sync_api import sync_playwright

match_id = "4467734"  # 利恩 vs 阿萨纳 (有数据的比赛)
url = f"https://odds.leisu.com/3in1-{match_id}"
NODE_PATH = r"D:\WorkApp\nodejs\node.exe"

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
        print("Node solver failed. Stderr:", stderr)
        return None
    try:
        res = json.loads(stdout.strip())
        if res.get('success'):
            return res.get('cookie')
        else:
            print("WAF solver success=False:", res)
    except Exception as e:
        print("JSON parse WAF error:", e, "Stdout:", stdout)
    return None

print("正在破解 PC 端的 WAF Cookie...")
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

print("urllib 请求返回 HTML 长度:", len(html_waf))
print("前 300 字符:", html_waf[:300])

cookie_val = solve_waf_via_node(html_waf, url, user_agent)
print("解出 WAF Cookie:", cookie_val)

responses = []

def handle_response(response):
    url_str = response.url
    # 只要有 api-gateway 或者是 leisu 域名下的 odds、trend、history 走势请求
    if "api-gateway" in url_str or "odds" in url_str or "trend" in url_str or "history" in url_str:
        try:
            body = response.text()
            responses.append({
                "url": url_str,
                "status": response.status,
                "body_snippet": body[:500] if body else None
            })
            print(f"🚀 【成功拦截 PC 走势 API】 -> {url_str} | Status: {response.status}", flush=True)
        except Exception:
            pass

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=user_agent)
        
        if cookie_val:
            context.add_cookies([{
                "name": "acw_sc__v2",
                "value": cookie_val,
                "domain": ".leisu.com",
                "path": "/"
            }])
            
        page = context.new_page()
        page.on("response", handle_response)
        
        print(f"正在打开 PC 端三合一页面: {url}")
        page.goto(url, timeout=30000)
        # 等待 Vue 表格组件渲染
        page.wait_for_selector('.main-content-vue', timeout=12000)
        page.wait_for_timeout(3000)
        print("PC 3in1 网页渲染完毕。")
        
        # 3. 模拟点击表格里的任意赔率格子
        click_probe = """
        () => {
            const elements = Array.from(document.querySelectorAll('span, td, div, a')).filter(el => {
                const text = (el.innerText || '').trim();
                return /^[0-9]\\.[0-9]+/i.test(text) || el.className.includes('trend') || el.className.includes('odds');
            });
            
            if (elements.length > 0) {
                elements.slice(0, 30).forEach(el => {
                    try { el.click(); } catch(e){}
                });
                return `Clicked ${elements.length} odds elements successfully on PC 3in1 page.`;
            }
            return "No clickable odds cells found.";
        }
        """
        click_res = page.evaluate(click_probe)
        print("点击动作结果:", click_res)
        
        # 等待 6 秒让走势 API 请求发送并拦截
        time.sleep(6)
        
        print(f"\nPC 端总共拦截到走势相关的 API 请求 {len(responses)} 个。")
        for idx, r in enumerate(responses):
            print(f"[{idx+1}] -> {r['url']}")
            print(f"    Status: {r['status']}")
            print(f"    Body snippet: {r['body_snippet']}")
            print("-" * 120)
            
        browser.close()
except Exception as e:
    print("Playwright 异常:", e)
