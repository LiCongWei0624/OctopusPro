import time
import json
import os
import subprocess
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
        print("Node WAF Solver error:", stderr)
        return None
    try:
        res = json.loads(stdout.strip())
        if res.get('success'):
            return res.get('cookie')
    except Exception as e:
        print("Node WAF JSON error:", e, stdout)
    return None

print("正在对手机版主域 https://m.leisu.com/ 进行 WAF 预破解...")
user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
headers = {
    'User-Agent': user_agent
}

# 对手机版主页发起请求以拿到 WAF 混淆 HTML
url_waf_target = "https://m.leisu.com/"
req = urllib.request.Request(url_waf_target, headers=headers)
html_waf = ""
try:
    with urllib.request.urlopen(req) as resp:
        html_waf = resp.read().decode('utf-8')
except urllib.error.HTTPError as e:
    html_waf = e.read().decode('utf-8')
except Exception as e:
    print("加载主页 WAF 失败:", e)

cookie_val = solve_waf_via_node(html_waf, url_waf_target, user_agent)
print("解出手机版 WAF Cookie:", cookie_val)

responses = []

def handle_response(response):
    url_str = response.url
    # 捕获所有含有 odds, trend, history, api-gateway 的请求
    if "api-gateway" in url_str or "odds" in url_str or "trend" in url_str or "history" in url_str:
        try:
            body = response.text()
            responses.append({
                "url": url_str,
                "status": response.status,
                "body_snippet": body[:500] if body else None
            })
            print(f"🚀 【拦截成功】 -> {url_str} | Status: {response.status}")
        except Exception:
            pass

try:
    with sync_playwright() as p:
        iphone = p.devices['iPhone 12']
        browser = p.chromium.launch(headless=True)
        # 用 context 模拟手机设备
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
        
        print(f"正在加载 H5 直播页面: {url}")
        page.goto(url, timeout=30000)
        # 等待页面内容渲染出来
        page.wait_for_timeout(6000)
        print("H5 页面渲染完毕。")
        
        # 1. 在手机 H5 页面上，寻找切换 Tab 的按钮并点击
        tab_click_js = """
        () => {
            // 打印页面上所有的文本按钮，方便辅助查找
            const elements = Array.from(document.querySelectorAll('div, span, a, li'));
            const textList = elements.map(el => (el.innerText || '').trim()).filter(Boolean);
            
            // 查找包含“指数”、“赔率”、“数据”的按钮并模拟点击
            const targetTabs = elements.filter(el => {
                const text = (el.innerText || '').trim();
                return text === '指数' || text === '数据' || text === '赔率';
            });
            
            if (targetTabs.length > 0) {
                targetTabs[0].click();
                return { "success": true, "clicked": targetTabs[0].innerText, "all_texts_sample": textList.slice(0, 30) };
            }
            return { "success": false, "all_texts_sample": textList.slice(0, 30) };
        }
        """
        tab_res = page.evaluate(tab_click_js)
        print("切换 Tab 动作结果:", json.dumps(tab_res, indent=2, ensure_ascii=False))
        page.wait_for_timeout(4000)
        
        # 2. 在指数栏，寻找博彩公司的数字格子，执行点击触发走势
        click_probe = """
        () => {
            const cells = Array.from(document.querySelectorAll('div, span, td, a')).filter(el => {
                const text = el.innerText || '';
                return /^[0-9]\\.[0-9]+/i.test(text.trim()) || el.className.includes('odds') || el.className.includes('trend');
            });
            if (cells.length > 0) {
                cells.slice(0, 15).forEach(c => {
                    try { c.click(); } catch(e){}
                });
                return `Clicked ${cells.length} mobile odds cells.`;
            }
            return "No mobile odds cells found.";
        }
        """
        click_res = page.evaluate(click_probe)
        print("点击动作结果:", click_res)
        
        time.sleep(5)
        
        print(f"\n手机端总共拦截到 API 请求 {len(responses)} 个。")
        browser.close()
except Exception as e:
    print("Playwright 异常:", e)
