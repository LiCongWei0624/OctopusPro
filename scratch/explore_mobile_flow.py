import time
import os
from playwright.sync_api import sync_playwright

match_id = "4467734"
url = f"https://m.leisu.com/live?id={match_id}"

print(f"正在以手机无头模式启动真实 Chrome 访问: {url} ...")

responses = []

def handle_response(response):
    url_str = response.url
    if "api-gateway" in url_str or "odds" in url_str or "trend" in url_str or "history" in url_str:
        try:
            body = response.text()
            responses.append({
                "url": url_str,
                "status": response.status,
                "method": response.request.method,
                "body_snippet": body[:500] if body else None
            })
            print(f"\n🚀 【拦截到 API】 -> {response.request.method} {url_str} | Status: {response.status}", flush=True)
            print(f"   Body: {body[:300]}", flush=True)
        except Exception:
            pass

try:
    with sync_playwright() as p:
        iphone = p.devices['iPhone 12']
        # 以无头模式拉起系统真实 Chrome 浏览器，解决 TLS 指纹问题
        browser = p.chromium.launch(headless=True, channel="chrome")
        context = browser.new_context(**iphone)
        page = context.new_page()
        page.on("response", handle_response)
        
        print("正在打开手机端详情页...")
        page.goto(url, timeout=30000)
        page.wait_for_timeout(6000)
        
        # 不需要模拟首页卡片点击了，因为我们直接用 URL 进详情页
        page.wait_for_timeout(3000)
        
        # 2. 自动切换到“指数”Tab
        tab_click_js = """
        () => {
            const tabs = Array.from(document.querySelectorAll('div, span, a, li')).filter(el => {
                const text = (el.innerText || '').trim();
                return text === '指数' || text === '数据' || text === '赔率' || text.includes('数据');
            });
            if (tabs.length > 0) {
                tabs[0].click();
                return `Clicked Tab: ${tabs[0].innerText}`;
            }
            return "No data/index tabs found in match details.";
        }
        """
        tab_res = page.evaluate(tab_click_js)
        print("点击数据详情Tab结果:", tab_res)
        
        page.wait_for_timeout(4000)
        
        # 3. 模拟点击公司的赔率格子拉起走势
        click_odds_js = """
        () => {
            const cells = Array.from(document.querySelectorAll('div, span, td, a')).filter(el => {
                const text = el.innerText || '';
                return /^[0-9]\\.[0-9]+/i.test(text.trim()) || el.className.includes('odds') || el.className.includes('trend');
            });
            if (cells.length > 0) {
                cells.slice(0, 15).forEach(c => {
                    try { c.click(); } catch(e){}
                });
                return `Clicked ${cells.length} odds cells.`;
            }
            return "No odds cells to click.";
        }
        """
        odds_res = page.evaluate(click_odds_js)
        print("点击赔率格子结果:", odds_res)
        
        # 挂起供点击响应和网络传输
        print("挂起 15 秒供人工在浏览器上自由点击指数...")
        page.wait_for_timeout(15000)
        
        # 保存手机页面的当前截图存盘
        out_img = os.path.join(os.path.dirname(__file__), 'mobile_flow_screenshot.png')
        page.screenshot(path=out_img)
        print(f"手机流式截图存入: {out_img}")
        
        browser.close()
except Exception as e:
    print("异常:", e)
