# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
import json
import base64
import os
import sys
import uuid
import shutil
import subprocess

app = Flask(__name__)

# 全局 Playwright 实例与常驻浏览器对象
_playwright = None
_browser = None

def decrypt_rot(key_b64, kst_str):
    salt = "uHhANonwd4UdpzOdsUqUsnl5PjurM877"
    key_seed = (kst_str + salt)[:16]
    key_bytes = key_seed.encode('utf-8')
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        enc_data = base64.b64decode(key_b64)
        cipher = Cipher(algorithms.AES(key_bytes), modes.ECB(), backend=default_backend())
        decryptor = cipher.decryptor()
        dec_data = decryptor.update(enc_data) + decryptor.finalize()
        pad_len = dec_data[-1]
        if 1 <= pad_len <= 16:
            dec_data = dec_data[:-pad_len]
        return dec_data.decode('utf-8')
    except Exception as e:
        return ""

def init_browser():
    global _playwright, _browser
    if _browser is None:
        print("Initializing global trend browser inside 5001 microservice...")
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-gpu',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-setuid-sandbox',
                '--disable-gpu-sandbox'
            ]
        )

@app.route('/fetch')
def fetch_trend():
    match_id = request.args.get('match_id')
    cid = request.args.get('cid')
    type_val = request.args.get('type')
    
    if not match_id or not cid or not type_val:
        return jsonify({'success': False, 'error': 'Missing parameters'}), 400
        
    try:
        init_browser()
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        context = _browser.new_context(user_agent=user_agent)
        
        # 尝试复用已有 Cookie 以极速建立风控信任
        cookie_file = os.path.join(os.path.dirname(__file__), 'session_cookies.json')
        if os.path.exists(cookie_file):
            try:
                with open(cookie_file, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                    context.add_cookies(cookies)
            except:
                pass
                
        page = context.new_page()
        
        # 强力隐藏 webdriver 特征，避免被阿里 WAF 识别为无头浏览器
        page.add_init_script("""
        () => {
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
        }
        """)
        
        # 拦截静态资源和多余广告，将网络负载缩至零
        def handle_route(route):
            req_type = route.request.resource_type
            url = route.request.url.lower()
            if (req_type in ["image", "stylesheet", "font", "media"] or 
                "baidu" in url or "google" in url or "hm.js" in url):
                try:
                    route.abort()
                except:
                    pass
            else:
                try:
                    route.continue_()
                except:
                    pass
        page.route("**/*", handle_route)
        # 1. 优先访问信任度高且入口正规的 3in1 指数大厅页面以建立 WAF 信任
        url_3in1 = f"https://odds.leisu.com/3in1-{match_id}"
        url_target = f"https://odds.leisu.com/trend-{match_id}-{cid}"
        print(f"5001 Microservice: Visiting 3in1 trust page: {url_3in1}")
        page.goto(url_3in1, timeout=15000)
        
        # 智能双轨监控：监测是成功建立信任直接载入大厅面板，还是被阿里 WAF 拦截出滑块
        try:
            page.wait_for_selector('.main-content-vue, table, #aliyunCaptcha-sliding-wrapper, .aliyun-captcha, .nc-container', timeout=8000)
        except:
            pass
            
        # 检测 3in1 页面上的 WAF 挑战并进行算力求解重试
        html_content = page.content()
        if '滑动验证页面' in html_content or 'aliyunCaptcha' in html_content or '<textarea id="renderData"' in html_content:
            print("5001 Microservice: WAF challenge detected on 3in1! Solving...")
            temp_waf_html = os.path.join(os.path.dirname(__file__), f"temp_5001_waf_{uuid.uuid4().hex[:8]}.html")
            with open(temp_waf_html, 'w', encoding='utf-8') as tf:
                tf.write(html_content)
                
            script_path = os.path.join(os.path.dirname(__file__), 'waf_solver.js')
            
            def find_node():
                path = shutil.which("node")
                if path: return path
                if os.path.exists(r"D:\WorkApp\nodejs\node.exe"): return r"D:\WorkApp\nodejs\node.exe"
                if os.path.exists(r"C:\Program Files\nodejs\node.exe"): return r"C:\Program Files\nodejs\node.exe"
                return "node"
                
            try:
                node_cmd = [find_node(), script_path, url_3in1, user_agent, temp_waf_html]
                proc = subprocess.Popen(
                    node_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8'
                )
                stdout_waf, stderr_waf = proc.communicate(timeout=6)
                
                debug_log_path = os.path.join(os.path.dirname(__file__), 'cache', 'node_waf_debug.log')
                with open(debug_log_path, 'w', encoding='utf-8') as df:
                    df.write(f"CMD: {node_cmd}\n")
                    df.write(f"STDOUT: {stdout_waf}\n")
                    df.write(f"STDERR: {stderr_waf}\n")
                
                try:
                    os.remove(temp_waf_html)
                except:
                    pass
                    
                res_waf = json.loads(stdout_waf.strip())
                if res_waf.get('success') and res_waf.get('cookie'):
                    cookie_val = res_waf['cookie']
                    print(f"5001 Microservice: WAF Solved! Injecting Cookie: {cookie_val}")
                    context.add_cookies([{
                        "name": "acw_sc__v2",
                        "value": cookie_val,
                        "domain": ".leisu.com",
                        "path": "/"
                    }])
                    page.goto(url_3in1, timeout=15000)
                else:
                    raise Exception(f"WAF Solver returned success=False. Stdout: {stdout_waf}. Stderr: {stderr_waf}")
            except Exception as ew:
                import traceback
                err_str = traceback.format_exc()
                debug_log_path = os.path.join(os.path.dirname(__file__), 'cache', 'node_waf_debug.log')
                with open(debug_log_path, 'a', encoding='utf-8') as df:
                    df.write(f"EXCEPTION_IN_WAF_RUN: {err_str}\n")
                raise Exception(f"WAF solve execution failed: {ew}")
                
        # 等待 3in1 页面的核心面板加载
        try:
            page.wait_for_selector('.main-content-vue, table', timeout=8000)
            print("5001 Microservice: 3in1 page trust established.")
        except Exception as e_3in1:
            print("5001 Microservice: 3in1 core selector wait timeout/failed:", e_3in1)
            
        # 2. 跳转到正式的 trend 静态走势图页面
        print(f"5001 Microservice: Redirecting to trend page: {url_target}")
        page.goto(url_target, timeout=12000)
        
        # 3. 等待 DOM 中的 table 元素渲染
        page.wait_for_selector('table.explain-table, table', timeout=8000)
        
        # 3. 运行浏览器内部原版 JS 算力直接解密并提取数据
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
                        
                        const typeInt = tIdx + 1;
                        
                        if (typeInt === 1 || typeInt === 3) {
                            tableData.push({
                                change_time: timeStr,
                                home: val1 ? parseFloat(val1) : 0,
                                line: val2,
                                line_zh: val2,
                                away: val3 ? parseFloat(val3) : 0,
                                type: typeInt,
                                score: score
                            });
                        } else if (typeInt === 2) {
                            tableData.push({
                                change_time: timeStr,
                                home: val1 ? parseFloat(val1) : 0,
                                draw: val2 ? parseFloat(val2) : 0,
                                away: val3 ? parseFloat(val3) : 0,
                                type: typeInt,
                                score: score
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
        
        # 4. 更新并写回最新 WAF Cookie 凭据到本地文件
        try:
            cookies = context.cookies()
            with open(cookie_file, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
        except Exception as ec:
            print("5001 Microservice: Failed to save cookies:", ec)
            
        context.close()
        
        # 5. 过滤并返回所请求的玩法类型的数据
        req_type = int(type_val)
        tbl_idx = req_type - 1
        
        if results_data and tbl_idx < len(results_data):
            matched_rows = results_data[tbl_idx]
            return jsonify({'success': True, 'data': matched_rows})
        else:
            return jsonify({'success': False, 'error': f"Table index {tbl_idx} out of range (Found tables: {len(results_data) if results_data else 0})"}), 404
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            if 'page' in locals() and page:
                err_html = page.content()
                err_html_path = os.path.join(os.path.dirname(__file__), 'cache', 'trend_error_page.html')
                os.makedirs(os.path.dirname(err_html_path), exist_ok=True)
                with open(err_html_path, 'w', encoding='utf-8') as ef:
                    ef.write(err_html)
                print(f"DEBUG: Saved error page content to {err_html_path}")
                
                err_img_path = os.path.join(os.path.dirname(__file__), 'cache', 'trend_error_page.png')
                page.screenshot(path=err_img_path)
                print(f"DEBUG: Saved error page screenshot to {err_img_path}")
        except Exception as e_debug:
            print("Failed to save debug info:", e_debug)
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    # 启动单线程常驻服务
    print("Starting Trend API Server on port 5001...")
    app.run(port=5001, threaded=False, debug=False)
