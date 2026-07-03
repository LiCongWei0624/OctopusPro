# -*- coding: utf-8 -*-
import asyncio
from playwright.async_api import async_playwright
import json
import uuid
import hashlib
import time
import base64
import zlib
import os
import subprocess
import shutil

match_id = "4467734"

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
        return None
    try:
        res = json.loads(stdout.strip())
        if res.get('success'):
            return res.get('cookie')
    except Exception:
        pass
    return None

responses = []

async def handle_response(response):
    url_str = response.url
    if "odds_detail" in url_str:
        print(f"\n🎉🎉🎉【拦截到走势 API 响应！】 -> {url_str}")
        try:
            body = await response.text()
            responses.append({
                "url": url_str,
                "status": response.status,
                "body": body
            })
        except Exception as e:
            print("读取响应内容失败:", e)

async def test():
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=user_agent)
        page = await context.new_page()
        
        await page.add_init_script("""
        () => {
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
        }
        """)
        
        # 1. 拦截走势请求
        page.on("response", handle_response)
        
        url_3in1 = f"https://odds.leisu.com/3in1-{match_id}"
        print(f"加载三合一页面: {url_3in1} ...")
        await page.goto(url_3in1, timeout=30000)
        
        # 3in1 页面的 WAF 求解
        html_3in1 = await page.content()
        if '<textarea id="renderData"' in html_3in1:
            print("三合一页面遇到 WAF，正在求解...")
            cookie_3in1 = solve_waf_via_node(html_3in1, url_3in1, user_agent)
            if cookie_3in1:
                print("植入 3in1 WAF Cookie 并重载...")
                await context.add_cookies([{
                    "name": "acw_sc__v2",
                    "value": cookie_3in1,
                    "domain": ".leisu.com",
                    "path": "/"
                }])
                await page.goto(url_3in1, timeout=30000)
                
        # 确认页面加载出 Vue
        await page.wait_for_selector('.main-content-vue', timeout=10000)
        print("三合一页面加载成功！")
        
        # 2. 模拟悬浮/鼠标划过赔率格子，以触发雷速自身的 Fetch 走势
        print("正在 Console 里执行模拟 hover 动作触发变盘拉取...")
        hover_js = """
        () => {
            // 寻找所有的赔率单元格（通常它们是 td 或者是包含赔率数字的 span/a，在 3in1 页上有特定的 class）
            // 我们通过遍历页面上所有可疑的赔率格子，派发 mouseenter 和 mouseover 事件！
            const elements = Array.from(document.querySelectorAll('td, span, a')).filter(el => {
                const text = el.innerText || '';
                return /^[0-9]\.[0-9]+/i.test(text.trim()) || el.className.includes('odds') || el.className.includes('trend') || el.getAttribute('data-cid') !== null;
            });
            
            if (elements.length > 0) {
                // 模拟对前 30 个赔率格子进行 mouseover / click，以尽可能触发各大公司的变盘 Fetch
                elements.slice(0, 30).forEach(el => {
                    try {
                        const eventEnter = new MouseEvent('mouseenter', { bubbles: true, cancelable: true });
                        const eventOver = new MouseEvent('mouseover', { bubbles: true, cancelable: true });
                        el.dispatchEvent(eventEnter);
                        el.dispatchEvent(eventOver);
                        // 也可以尝试 click 它们
                        el.click();
                    } catch(e) {}
                });
                return `Successfully dispatched hover events to ${elements.length} elements.`;
            }
            return "No odds elements found to hover.";
        }
        """
        hover_res = await page.evaluate(hover_js)
        print("模拟 Hover 结果:", hover_res)
        
        # 挂起 5 秒等待所有异步 Fetch 响应拦截完毕
        await page.wait_for_timeout(5000)
        
        print(f"\n共拦截到 {len(responses)} 个走势 API 响应。")
        for idx, r in enumerate(responses):
            body_text = r['body']
            try:
                res_json = json.loads(body_text)
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
                    decrypted_json = json.loads(decompressed)
                    print(f"[{idx+1}] 拦截并成功解密走势！数据长度: {len(decompressed)}")
                    print("  走势前 2 点样本:", decrypted_json[:2])
                else:
                    print(f"[{idx+1}] 拦截但无需解密或错误: code={code_val}")
            except Exception as ex:
                print(f"[{idx+1}] 解析解密报错:", ex, "内容:", body_text[:200])
                
        await browser.close()

if __name__ == '__main__':
    asyncio.run(test())
