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

SALT = "uHhANonwd4UdpzOdsUqUsnl5PjurM877"

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

def run_fetch_flow(match_id, cid, type_val, headless=True):
    from playwright.sync_api import sync_playwright
    
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    cookie_file = os.path.join(os.path.dirname(__file__), 'session_cookies.json')
    
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    '--disable-gpu', 
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-setuid-sandbox',
                    '--disable-gpu-sandbox',
                    '--disable-software-rasterizer'
                ]
            )
            context = browser.new_context(user_agent=user_agent)
            
            # 1. 尝试注入已有 Cookie
            if os.path.exists(cookie_file):
                try:
                    with open(cookie_file, 'r', encoding='utf-8') as f:
                        cookies = json.load(f)
                        context.add_cookies(cookies)
                except Exception as ec:
                    print(f"Error loading cookies: {ec}")
                    
            page = context.new_page()
            page.add_init_script("""
            () => {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = { runtime: {} };
            }
            """)
            
            # 路由拦截过滤，大幅提升网页加载速度并降低流量负载
            def handle_route(route):
                req = route.request
                resource_type = req.resource_type
                url = req.url.lower()
                
                if (resource_type in ["image", "stylesheet", "font", "media"] or 
                    "baidu" in url or "google" in url or "hm.js" in url or 
                    "cnzz" in url or "ad" in url or "stats" in url):
                    try:
                        route.abort()
                    except:
                        pass
                else:
                    try:
                        route.continue_()
                    except:
                        pass
                        
            url_target = f"https://odds.leisu.com/trend-{match_id}-{cid}"
            try:
                page.goto(url_target, timeout=8000)
                
                # WAF 检测与沙箱自适应求解 (仅无头模式下尝试求解)
                html_content = page.content()
                if headless and '<textarea id="renderData"' in html_content:
                    print("Playwright Subprocess: WAF challenge detected! Solving...")
                    sys.path.append(os.path.dirname(__file__))
                    temp_waf_html = os.path.join(os.path.dirname(__file__), f"temp_sub_waf_{uuid.uuid4().hex[:8]}.html")
                    with open(temp_waf_html, 'w', encoding='utf-8') as tf:
                        tf.write(html_content)
                    
                    script_path = os.path.join(os.path.dirname(__file__), 'waf_solver.js')
                    import subprocess
                    import shutil
                    
                    def find_node():
                        path = shutil.which("node")
                        if path: return path
                        if os.path.exists(r"D:\WorkApp\nodejs\node.exe"): return r"D:\WorkApp\nodejs\node.exe"
                        if os.path.exists(r"C:\Program Files\nodejs\node.exe"): return r"C:\Program Files\nodejs\node.exe"
                        return "node"
                        
                    proc = subprocess.Popen(
                        [find_node(), script_path, url_target, user_agent, temp_waf_html],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding='utf-8'
                     )
                    stdout_waf, _ = proc.communicate(timeout=5)
                    
                    try:
                        os.remove(temp_waf_html)
                    except:
                        pass
                        
                    try:
                        res_waf = json.loads(stdout_waf.strip())
                        if res_waf.get('success') and res_waf.get('cookie'):
                            cookie_val = res_waf['cookie']
                            print(f"Playwright Subprocess: WAF Solved! Cookie: {cookie_val}")
                            context.add_cookies([{
                                "name": "acw_sc__v2",
                                "value": cookie_val,
                                "domain": ".leisu.com",
                                "path": "/"
                            }])
                            page.goto(url_target, timeout=8000)
                    except Exception as ew:
                        print("Solve WAF failed inside subprocess:", ew)
                
                # 等待趋势走势表格或者是WAF解除后的核心元素加载出来
                page.wait_for_selector('table.explain-table, table', timeout=8000)
                        
            except Exception as e_load:
                return {"success": False, "error": f"Page load failed or timed out: {e_load}"}
                
            # 2. 如果加载出了数据，且为有头模式，则需要保存最新的 Cookie 凭证
            if not headless:
                try:
                    cookies = context.cookies()
                    with open(cookie_file, 'w', encoding='utf-8') as f:
                        json.dump(cookies, f, ensure_ascii=False, indent=2)
                    print("✅ 凭证已成功保存！")
                except Exception as ec_save:
                    print(f"Error saving cookies: {ec_save}")
                    
            # 3. 强制在浏览器内给 Vue 异步渲染留下 1.5 秒时间
            time.sleep(1.5)
            
            # 4. 在浏览器中直接通过 Evaluate 解密并抓取 DOM 里的 Table 数据
            decrypt_js = """
            () => {
                const tables = document.querySelectorAll('table.explain-table');
                const results = [];
                
                tables.forEach((table, tIdx) => {
                    const tableData = [];
                    const trs = Array.from(table.querySelectorAll('tr'));
                    
                    trs.slice(1).forEach((tr) => {
                        const tds = tr.querySelectorAll('td');
                        if (tds.length >= 5) {
                            const timeStr = tds[0].innerText.trim();
                            const score = tds[1].innerText.trim();
                            
                            const getVal = (td) => {
                                const canvas = td.querySelector('canvas');
                                if (canvas && canvas.getAttribute('key')) {
                                    const key = canvas.getAttribute('key');
                                    if (window.$ && typeof window.$.rot === 'function') {
                                        const kst = (window.STATIC_CONFIG && window.STATIC_CONFIG.KST) || "";
                                        return window.$.rot(key, kst);
                                    }
                                    return "";
                                }
                                return td.innerText.trim();
                            };
                            
                            const val1 = getVal(tds[2]); // 主胜/主水/大球水
                            const val2 = getVal(tds[3]); // 平局/让球盘/大小球盘
                            const val3 = getVal(tds[4]); // 客胜/客水/小球水
                            
                            // 确定当前是第几张表：tIdx == 0 -> 让球 (1), tIdx == 1 -> 胜平负 (2), tIdx == 2 -> 大小球 (3)
                            const typeInt = tIdx + 1;
                            
                            if (typeInt === 1 || typeInt === 3) {
                                tableData.push({
                                    change_time: timeStr,
                                    home: val1 ? parseFloat(val1) : 0,
                                    line: val2,
                                    line_zh: val2,
                                    away: val3 ? parseFloat(val3) : 0,
                                    match_status: 1
                                });
                            } else if (typeInt === 2) {
                                tableData.push({
                                    change_time: timeStr,
                                    home: val1 ? parseFloat(val1) : 0,
                                    draw: val2 ? parseFloat(val2) : 0,
                                    away: val3 ? parseFloat(val3) : 0,
                                    line: "0",
                                    line_zh: "欧指",
                                    match_status: 1
                                });
                            }
                        }
                    });
                    results.push(tableData);
                });
                return results;
            }
            """
            
            results_data = page.evaluate(decrypt_js)
            
            # 若 type_val 为 'all'，则一次性返回全部三张表的变盘明细
            if type_val == 'all':
                if results_data and len(results_data) > 0:
                    return {"success": True, "data": results_data}
                else:
                    return {"success": False, "error": "Extracted all trend list is empty."}
            
            # 确定当前请求需要的 type 对应的表格索引 (type_val 传入的是 '1', '2', '3')
            req_type = int(type_val)
            tbl_idx = req_type - 1
            
            if results_data and tbl_idx < len(results_data):
                matched_rows = results_data[tbl_idx]
                if len(matched_rows) > 0:
                    return {"success": True, "data": matched_rows}
                else:
                    return {"success": False, "error": f"Extracted trend list for type {type_val} is empty."}
            else:
                return {"success": False, "error": f"Failed to extract table data for type {type_val}. Total tables found: {len(results_data) if results_data else 0}"}
        finally:
            if browser:
                try:
                    browser.close()
                except:
                    pass

def main():
    if len(sys.argv) < 4:
        print(json.dumps({"success": False, "error": "Missing arguments"}))
        return
        
    match_id = sys.argv[1]
    cid = sys.argv[2]
    type_val = sys.argv[3]
    
    headless_only = "--headless-only" in sys.argv
    
    # 1. 优先尝试无头模式（使用已有 Cookie 极速加载）
    print("Trying headless mode first...")
    res_headless = run_fetch_flow(match_id, cid, type_val, headless=True)
    if res_headless.get('success'):
        print("Headless fetch success!")
        # 写入物理缓存文件
        cache_path = os.path.join(os.path.dirname(__file__), f"odds_detail_{match_id}_{cid}_{type_val}.json")
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(res_headless['data'], f, ensure_ascii=False, indent=2)
        print(json.dumps({"success": True, "cache_path": cache_path}))
        return
        
    # 2. 如果无头模式失败，判断是否限制为只运行无头
    if headless_only:
        print(json.dumps({"success": False, "error": f"Headless failed: {res_headless.get('error')}. Headless-only is set."}))
        return
        
    # 3. 如果无头模式失败，且允许有头模式，则重载为有头模式进行建联与手动滑动
    print(f"Headless failed: {res_headless.get('error')}. Re-trying with headful mode...")
    res_headful = run_fetch_flow(match_id, cid, type_val, headless=False)
    if res_headful.get('success'):
        cache_path = os.path.join(os.path.dirname(__file__), f"odds_detail_{match_id}_{cid}_{type_val}.json")
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(res_headful['data'], f, ensure_ascii=False, indent=2)
        print(json.dumps({"success": True, "cache_path": cache_path}))
    else:
        print(json.dumps(res_headful))

if __name__ == '__main__':
    main()
