import json
import os

json_path = os.path.join(os.path.dirname(__file__), 'vue_data.json')

if not os.path.exists(json_path):
    print("找不到 vue_data.json 文件")
    exit(1)

with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

print("正在深度扫描 Vue _data 字典...")

def scan_dict(d, path="root"):
    if isinstance(d, dict):
        for k, v in d.items():
            new_path = f"{path} -> {k}"
            if isinstance(v, (dict, list)):
                scan_dict(v, new_path)
            else:
                # 打印普通键值
                if k in ['cur_select_id', 'odd_type', 'fide']:
                    print(f"[{new_path}] = {v}")
    elif isinstance(d, list):
        print(f"[{path}] (List of length {len(d)})")
        if len(d) > 0:
            # 打印前 2 项样本
            print(f"   Sample: {str(d[:2])[:200]}")
            # 如果列表里的项是字典或列表，继续递归
            for idx, item in enumerate(d[:2]):
                scan_dict(item, f"{path}[{idx}]")

scan_dict(data)
