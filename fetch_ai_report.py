# -*- coding: utf-8 -*-
import requests
import json
import time
import os
import sys

# 导入本地的 build_match_prompt_context
from app import build_match_prompt_context, CONFIG_FILE, DEFAULT_SYSTEM_PROMPT

def poll_and_generate():
    match_id = '4480412'
    home = '仁川联'
    away = '安养FC'
    
    print("1. 获取本地拼装的用户提示词内容...")
    # 从本地缓存生成用户提示词
    success, err_msg, context_str = build_match_prompt_context(match_id, home, away)
    if not success:
        print(f"Error building context: {err_msg}")
        sys.exit(1)
        
    print("2. 从远程获取系统提示词配置...")
    try:
        r_config = requests.get('http://103.158.36.165:5000/api/ai_config')
        config_data = r_config.json()
        system_prompt = config_data.get('data', {}).get('system_prompt', DEFAULT_SYSTEM_PROMPT)
    except Exception as e:
        print(f"Failed to get remote config: {e}")
        system_prompt = DEFAULT_SYSTEM_PROMPT

    # 拼装用户提示词的完整包 (与 app.py 中 run_single_version 拼装格式完全一致)
    user_prompt_template = (
        "请针对以下赛事数据进行深度量化研判。请计算重点机构欧指的隐含概率变化，"
        "并通过基本面多维特征与临场盘水交叉审计，找出本场最具数学期望值（Value）的投资方向：\n\n"
        "(注意：这是第 {version_idx} 次研判，请提供独特的分析切入点与结论)\n\n{context_str}"
    )

    print("3. 开始轮询远程 AI 分析状态...")
    reports = None
    max_retries = 30
    for i in range(max_retries):
        try:
            r = requests.get('http://103.158.36.165:5000/api/ai_analysis_status', params={'match_id': match_id})
            res = r.json()
            status = res.get('status')
            print(f"轮询次数 {i+1}/{max_retries}: 状态为 [{status}]")
            if status == 'completed':
                reports = res.get('reports')
                break
            elif status == 'failed':
                print(f"远程生成失败: {res.get('error')}")
                break
        except Exception as e:
            print(f"Request error: {e}")
        time.sleep(10)

    if not reports:
        print("未能获取到生成的报告。")
        sys.exit(1)

    print("4. 成功获取报告！正在生成输出 Markdown 文件...")
    
    # 构造输出格式
    output_lines = []
    output_lines.append("# ⚽ 韩K联 仁川联 VS 安养FC 比赛AI研判完整输入与输出")
    output_lines.append("\n## 一、 系统提示词 (System Prompt)")
    output_lines.append("```markdown")
    output_lines.append(system_prompt)
    output_lines.append("```")
    
    output_lines.append("\n## 二、 用户提示词 (User Prompt)")
    output_lines.append("> 说明：系统会并发请求 3 个版本，它们的 System Prompt 相同，但 User Prompt 的前缀稍有差别（带有版本序号和不同的温度参数）。以下为版本 1 的 User Prompt 示例：\n")
    output_lines.append("```markdown")
    output_lines.append(user_prompt_template.format(version_idx=1, context_str=context_str))
    output_lines.append("```")
    
    output_lines.append("\n## 三、 AI 研判输出内容")
    output_lines.append("> 接口总共返回了 3 个不同版本的分析报告。以下分别列出它们的思考过程（Think）与报告输出内容。\n")

    for idx, report_content in enumerate(reports):
        output_lines.append(f"\n### 📝 研判报告版本 {idx+1}")
        
        # 提取思考过程 (即 <think>...</think> 之间的部分)
        think_content = ""
        actual_output = report_content
        
        if "<think>" in report_content and "</think>" in report_content:
            parts = report_content.split("</think>")
            think_part = parts[0].split("<think>")
            if len(think_part) > 1:
                think_content = think_part[1].strip()
            actual_output = parts[1].strip()
        elif "<think>" in report_content:
            parts = report_content.split("<think>")
            actual_output = parts[0].strip()
            think_content = parts[1].strip()
            
        output_lines.append("\n#### 🧠 思考过程 (Reasoning Process)")
        if think_content:
            output_lines.append("```text")
            output_lines.append(think_content)
            output_lines.append("```")
        else:
            output_lines.append("*（本版本未输出或未能提取出 <think> 标签内的思考过程）*")
            
        output_lines.append("\n#### 📄 研判报告原文 (Output Content)")
        output_lines.append(actual_output)
        output_lines.append("\n" + "="*50 + "\n")

    output_filepath = 'match_ai_analysis_record.md'
    with open(output_filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(output_lines))
        
    print(f"5. 处理完成！生成的文件已保存为: {os.path.abspath(output_filepath)}")

if __name__ == '__main__':
    poll_and_generate()
