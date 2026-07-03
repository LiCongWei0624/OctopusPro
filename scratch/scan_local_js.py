import os
import re

js_files = ['de74dcb.js', '0299bd5.js', 'fe66d24.js', '3d179aa.js']
root_dir = os.path.dirname(os.path.dirname(__file__))

print("正在扫描本地雷速前端 JS 文件中的所有 API 端点...")

all_endpoints = set()

for jf in js_files:
    path = os.path.join(root_dir, jf)
    if not os.path.exists(path):
        print(f"[-] 文件不存在: {jf}")
        continue
        
    print(f"[+] 正在扫描: {jf} (大小: {os.path.getsize(path)} 字节)")
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    # 匹配所有的 /v1/web/ 路由
    matches = re.findall(r'/v1/web/[a-zA-Z0-9_\-/]+', content)
    for m in matches:
        all_endpoints.add(m)

print(f"\n扫描结束！总共找到 {len(all_endpoints)} 个独特的 API 端点。")

print("\n--- 包含 odds, trend, history, detail 的赔率相关端点 ---")
keywords = ['odds', 'trend', 'history', 'detail', 'change', 'comp']
matched_count = 0
for ep in sorted(list(all_endpoints)):
    matched_kws = [kw for kw in keywords if kw in ep.lower()]
    if matched_kws:
        print(f"  {ep} (匹配: {matched_kws})")
        matched_count += 1

print(f"\n共筛出 {matched_count} 个赔率相关端点。")
