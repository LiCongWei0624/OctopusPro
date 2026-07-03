import json
import sys
from playwright.sync_api import sync_playwright

match_id = "4459725"
url = f"https://odds.leisu.com/3in1-{match_id}"

print(f"正在加载 {url} 并分析 Vue 实例...")

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.goto(url, timeout=20000)
        page.wait_for_selector('.main-content-vue', timeout=8000)
        
        # 执行探测：查看 Vue 根组件的所有 data 字段
        js_probe = """
        () => {
            const el = document.querySelector('.main-content-vue');
            if (!el || !el.__vue__) return { "error": "No Vue instance found" };
            
            // 拿到 Vue 实例的所有 key
            const keys = Object.keys(el.__vue__._data || {});
            
            // 尝试序列化 ftb_odds
            const ftb_odds_sample = el.__vue__.ftb_odds ? JSON.stringify(el.__vue__.ftb_odds).substring(0, 1000) : null;
            
            return {
                keys: keys,
                ftb_odds_sample: ftb_odds_sample,
                // 查看是否有其它带有 odds、trend、change、history 字样的变量
                matched_vars: Object.keys(el.__vue__).filter(k => /odds|trend|change|history/i.test(k))
            };
        }
        """
        result = page.evaluate(js_probe)
        print("Vue 探测结果：")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        # 探索页面中其他 Vue 实例（比如在各个表格行上是否有 Vue 实例）
        js_all_vue = """
        () => {
            const list = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.__vue__) {
                    list.push({
                        tag: el.tagName,
                        className: el.className,
                        data_keys: Object.keys(el.__vue__._data || {}),
                        matched: Object.keys(el.__vue__).filter(k => /odds|trend|change|history/i.test(k))
                    });
                }
            });
            return list.slice(0, 20); // 只取前 20 个
        }
        """
        all_vue = page.evaluate(js_all_vue)
        print("\n页面中所有检测到的 Vue 组件：")
        print(json.dumps(all_vue, indent=2, ensure_ascii=False))
        
        browser.close()
except Exception as e:
    print("发生异常:", e)
