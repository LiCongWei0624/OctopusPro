# -*- coding: utf-8 -*-
import asyncio
from playwright.async_api import async_playwright
import json
import uuid
import hashlib
import time
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
        print("WAF JS Solver error:", stderr)
        return None
    try:
        res = json.loads(stdout.strip())
        if res.get('success'):
            return res.get('cookie')
    except Exception as e:
        print("WAF JSON parse error:", e, stdout)
    return None

async def test():
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch(headless=True)
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
        
        url = f"https://odds.leisu.com/3in1-{match_id}"
        print(f"Loading page: {url} ...")
        await page.goto(url, timeout=30000)
        
        # 求解 WAF
        html = await page.content()
        if '<textarea id="renderData"' in html:
            print("WAF challenge encountered! Solving WAF...")
            cookie_val = solve_waf_via_node(html, url, user_agent)
            if cookie_val:
                print("WAF Cookie solved, injecting:", cookie_val)
                await context.add_cookies([{
                    "name": "acw_sc__v2",
                    "value": cookie_val,
                    "domain": "odds.leisu.com",
                    "path": "/"
                }])
                print("Reloading page...")
                await page.goto(url, timeout=30000)
                
        await page.wait_for_selector('.main-content-vue', timeout=10000)
        print("Page loaded successfully under Vue scope.")
        
        detect_js = """
        () => {
            const el = document.querySelector('.main-content-vue');
            if (!el || !el.__vue__) return { success: false, error: "Vue instance not found" };
            
            const vue = el.__vue__;
            const props = [];
            
            for (let k in vue) {
                props.push(k);
            }
            
            const network_helpers = [];
            const search_keys = ['axios', '$axios', 'http', '$http', 'request', '$request', 'ajax', '$ajax', 'fetch', 'api', '$api'];
            
            search_keys.forEach(k => {
                if (vue[k] !== undefined) {
                    network_helpers.push({ name: k, type: typeof vue[k] });
                }
                if (window[k] !== undefined) {
                    network_helpers.push({ name: `window.${k}`, type: typeof window[k] });
                }
                if (vue.constructor && vue.constructor.prototype && vue.constructor.prototype[k] !== undefined) {
                    network_helpers.push({ name: `prototype.${k}`, type: typeof vue.constructor.prototype[k] });
                }
            });
            
            const trend_methods = [];
            for (let k in vue) {
                if (typeof vue[k] === 'function') {
                    const name = k.toLowerCase();
                    if (name.includes('odds') || name.includes('trend') || name.includes('detail') || name.includes('chart') || name.includes('fetch') || name.includes('load')) {
                        trend_methods.push(k);
                    }
                }
            }
            
            return {
                success: true,
                network_helpers: network_helpers,
                trend_methods: trend_methods,
                all_properties_sample: props.slice(0, 100)
            };
        }
        """
        
        res = await page.evaluate(detect_js)
        print("Vue 实例探测结果:")
        print(json.dumps(res, ensure_ascii=False, indent=2))
        await browser.close()

if __name__ == '__main__':
    asyncio.run(test())
