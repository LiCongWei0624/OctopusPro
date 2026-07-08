# -*- coding: utf-8 -*-
import sys
import os
import json
import uuid
import time

def run_fast_flow(match_id, cid, type_val):
    from playwright.sync_api import sync_playwright
    
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-gpu', 
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-setuid-sandbox',
                    '--disable-gpu-sandbox',
                    '--disable-software-rasterizer'
                ]
            )
            # 建立全新且高度隔离的安全上下文，模拟最纯净的用户网络身份特征
            context = browser.new_context(user_agent=user_agent)
            page = context.new_page()
            
            # 强力隐藏 webdriver 特征
            page.add_init_script("""
            () => {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = { runtime: {} };
            }
            """)
            
            # 拦截无用静态资源，提速数倍
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
            
            url_target = f"https://odds.leisu.com/trend-{match_id}-{cid}"
            page.goto(url_target, timeout=12000)
            
            # 1. 优先检测 521 无感 WAF 挑战并进行算力求解重试
            html_content = page.content()
            if '<textarea id="renderData"' in html_content:
                temp_waf_html = os.path.join(os.path.dirname(__file__), f"temp_fast_waf_{uuid.uuid4().hex[:8]}.html")
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
                        context.add_cookies([{
                            "name": "acw_sc__v2",
                            "value": cookie_val,
                            "domain": ".leisu.com",
                            "path": "/"
                        }])
                        page.goto(url_target, timeout=12000)
                except:
                    pass
            
            # 2. 等待走势图页面上的 Table 元素渲染出来
            page.wait_for_selector('table.explain-table, table', timeout=6500)
            
            # 3. 直接在浏览器端 evaluate 执行官方 rot 算法解密表格并拿回 JSON 数据
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
            
            # 关键优化：一次加载网页，顺便将该公司的让球(1)、欧赔(2)、大小球(3)的缓存全部写盘，效率提升 3 倍
            if results_data:
                for idx, tableData in enumerate(results_data):
                    t_val = idx + 1
                    # 写入根目录下缓存（供 Python detail_scraper 立即读取）
                    c_path_root = os.path.join(os.path.dirname(__file__), f"odds_detail_{match_id}_{cid}_{t_val}.json")
                    # 写入 cache/ 目录下缓存（供 Flask 路由直接命中，防止再次加载）
                    c_path_cache = os.path.join(os.path.dirname(__file__), 'cache', f"odds_detail_{match_id}_{cid}_{t_val}.json")
                    
                    for p in [c_path_root, c_path_cache]:
                        try:
                            os.makedirs(os.path.dirname(p), exist_ok=True)
                            with open(p, 'w', encoding='utf-8') as f:
                                json.dump(tableData, f, ensure_ascii=False, indent=2)
                        except Exception:
                            pass
                
                # 返回当前请求玩法的数据给主进程
                req_type = int(type_val)
                tbl_idx = req_type - 1
                if tbl_idx < len(results_data):
                    return {"success": True, "data": results_data[tbl_idx]}
            return {"success": False, "error": "Table index out of range"}
        except Exception as e:
            return {"success": False, "error": str(e)}
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
    
    res = run_fast_flow(match_id, cid, type_val)
    if res.get('success'):
        print(json.dumps({"success": True, "data_length": len(res['data'])}))
    else:
        print(json.dumps(res))

if __name__ == '__main__':
    main()
