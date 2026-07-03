# -*- coding: utf-8 -*-
import time
import os
import json
from playwright.sync_api import sync_playwright

match_id = "4467734"  # 利恩 vs 阿萨纳 (完赛挪甲)
url = f"https://m.leisu.com/match/detail/football/{match_id}#odds"

print(f"正在启动隐身移动端浏览器 Playwright 访问 H5 数据分析页: {url} ...")

def handle_response(response):
    url_str = response.url
    if "leisu.com" in url_str:
        try:
            body_bytes = response.body()
            import zlib
            import base64
            # 尝试 gzip 解压
            try:
                body_bytes = zlib.decompress(body_bytes, 15 + 32)
            except Exception:
                try:
                    body_bytes = zlib.decompress(body_bytes)
                except Exception:
                    pass
            body = body_bytes.decode('utf-8', errors='ignore')
            
            # 如果是 odds_detail API (走势细节接口)
            if "odds_detail" in url_str:
                print(f"\n🎉🎉🎉 【拦截到走势 API 成功响应！】 -> {url_str}")
                try:
                    res_json = json.loads(body)
                    code = res_json.get('code', 0)
                    data_val = res_json.get('data')
                    if data_val and isinstance(data_val, str) and 100 <= code <= 130:
                        offset = code - 100
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
                        decompressed_json = json.loads(decompressed)
                        print("🔥 【历史变盘走势明文解密成功！】")
                        print(f"数据总字符长度: {len(decompressed)}")
                        print(f"走势变盘点总个数: {len(decompressed_json)}")
                        print("前 5 条走势历史记录明细:")
                        print(json.dumps(decompressed_json[:5], ensure_ascii=False, indent=2))
                        print("--------------------------------------------------")
                except Exception as ex2:
                    print("   [解密走势密文报错]:", ex2)
            else:
                # 其它 API 仅简短打印
                if "v1/web" in url_str:
                    print(f"🚀 【拦截到 API】 -> {url_str[:120]}... | Status: {response.status}")
        except Exception as ex:
            pass

try:
    with sync_playwright() as p:
        # 使用移动端 iPhone 12/13 的 UA 和视口启动 Chrome
        browser = p.chromium.launch(headless=False, channel="chrome")
        iphone_13 = p.devices['iPhone 13']
        context = browser.new_context(
            **iphone_13
        )
        page = context.new_page()
        
        # 绕过阿里 WAF 的 webdriver 特征检测
        page.add_init_script("""
        () => {
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
        }
        """)
        
        page.on("response", handle_response)
        
        print("正在打开 H5 赔率页...")
        page.goto(url, timeout=30000)
        
        print("等待 10 秒确保 WAF 滑块挑战通过并完整渲染...")
        page.wait_for_timeout(10000)
        
        # 在控制台直接 Fetch 变盘走势 API
        # type=1 (让球), cid=3 (皇冠)
        api_target = f"https://api-gateway.leisu.com/v1/web/match/common/odds_detail?id={match_id}&cid=3&type=1"
        print(f"\n正在通过 H5 Console 作用域直接 Fetch API: {api_target} ...")
        
        fetch_js = f"""
        async () => {{
            try {{
                const r = await fetch('{api_target}', {{
                    headers: {{
                        'Accept': 'application/json, text/plain, */*',
                        'source': 'm_leisu'
                    }}
                }});
                const resText = await r.text();
                return {{ success: true, status: r.status, data: resText }};
            }} catch(e) {{
                return {{ success: false, error: e.message }};
            }}
        }}
        """
        
        fetch_res = page.evaluate(fetch_js)
        print("Fetch 发起结果诊断:")
        if fetch_res.get('success'):
            print(f"HTTP 状态码: {fetch_res['status']}")
            snippet = fetch_res['data'][:400]
            print(f"响应内容片段: {snippet}")
            
            # 在 python 里尝试直接解密它
            try:
                res_json = json.loads(fetch_res['data'])
                data_val = res_json.get('data')
                code_val = res_json.get('code', 0)
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
                    import base64
                    import zlib
                    decoded_bytes = base64.b64decode(res_caesar)
                    decompressed = zlib.decompress(decoded_bytes, 15 + 32).decode('utf-8')
                    print("\n🎉【恭喜！从 H5 作用域 Fetch 成功并解密！】")
                    print(f"解密总项数: {len(json.loads(decompressed))}")
            except Exception as e_dec:
                print("Python 自行解析解密报错:", e_dec)
        else:
            print("Fetch 错误:", fetch_res.get('error'))
            
        print("\n挂起 15 秒供人机交互和观察...")
        page.wait_for_timeout(15000)
        
        # 截图存底
        out_img = os.path.join(os.path.dirname(__file__), 'h5_shujufenxi_screenshot.png')
        page.screenshot(path=out_img)
        print(f"页面截图已存为: {out_img}")
        
        browser.close()
except Exception as e:
    print("移动端 Playwright 异常:", e)
