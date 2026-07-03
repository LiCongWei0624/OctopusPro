import json
import os
import subprocess
import urllib.request
import urllib.error
from playwright.sync_api import sync_playwright

match_id = "4459725"
url = f"https://odds.leisu.com/3in1-{match_id}"
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

print("正在破解 WAF 并 Dump Vue _data...")
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

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=user_agent)
        context.add_cookies([{
            "name": "acw_sc__v2",
            "value": cookie_val,
            "domain": "odds.leisu.com",
            "path": "/"
        }])
        page = context.new_page()
        page.goto(url, timeout=25000)
        page.wait_for_selector('.main-content-vue', timeout=10000)
        
        # 提取整个 _data
        probe_js = """
        () => {
            const el = document.querySelector('.main-content-vue');
            if (el && el.__vue__) {
                return JSON.stringify(el.__vue__._data);
            }
            return null;
        }
        """
        vue_data_json = page.evaluate(probe_js)
        if vue_data_json:
            parsed = json.loads(vue_data_json)
            out_path = os.path.join(os.path.dirname(__file__), 'vue_data.json')
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(parsed, f, indent=2, ensure_ascii=False)
            print(f"Vue _data 已成功 Dump 到 {out_path}！")
            
            # 打印部分 Key 的长度或样例
            for k, v in parsed.items():
                if isinstance(v, list):
                    print(f"Key: {k} (list, length: {len(v)})")
                elif isinstance(v, dict):
                    print(f"Key: {k} (dict, keys: {list(v.keys())[:10]})")
                else:
                    print(f"Key: {k} (value: {v})")
        else:
            print("未能提取到 Vue 数据")
        browser.close()
except Exception as e:
    print("异常:", e)
