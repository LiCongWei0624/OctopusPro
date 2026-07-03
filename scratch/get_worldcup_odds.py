# -*- coding: utf-8 -*-
import sys
import os
import json

# 确保能导入 detail_scraper
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from detail_scraper import get_real_odds

def check_match_odds(match_id, home_team, away_team):
    print(f"\n====================================================")
    print(f" 🎯 赛事：{home_team} vs {away_team} (ID: {match_id})")
    print(f"====================================================")
    
    try:
        odds_data = get_real_odds(match_id)
        if not odds_data or 'error' in odds_data:
            print(f"获取赔率数据失败: {odds_data.get('error') if odds_data else '返回空'}")
            return
            
        print("各大主流公司指数盘口：\n")
        
        # 让球赔率 (Handicap)
        print(" 【让球 (Handicap)】")
        print(f"  {'公司':<12} | {'初始盘口 (主/盘/客)':<25} | {'最新即时盘口 (主/盘/客)':<25}")
        print(f"  {'-'*70}")
        
        for row in odds_data:
            company = row.get('company', '未知')
            handicap = row.get('handicap')
            if handicap:
                init_vals = handicap.get('initial', [0, 0])
                inst_vals = handicap.get('instant', [0, 0])
                line = handicap.get('initial_line', handicap.get('line', '0'))
                inst_line = handicap.get('instant_line', handicap.get('line', '0'))
                
                init_str = f"{init_vals[0]:.2f} / {line} / {init_vals[1]:.2f}"
                inst_str = f"{inst_vals[0]:.2f} / {inst_line} / {inst_vals[1]:.2f}"
                print(f"  {company:<12} | {init_str:<25} | {inst_str:<25}")
                
        # 大小球赔率 (Over/Under)
        print("\n 【总进球 (Over/Under)】")
        print(f"  {'公司':<12} | {'初始盘口 (大/盘/小)':<25} | {'最新即时盘口 (大/盘/小)':<25}")
        print(f"  {'-'*70}")
        
        for row in odds_data:
            company = row.get('company', '未知')
            ou = row.get('over_under')
            if ou:
                init_vals = ou.get('initial', [0, 0])
                inst_vals = ou.get('instant', [0, 0])
                line = ou.get('initial_line', ou.get('line', '0'))
                inst_line = ou.get('instant_line', ou.get('line', '0'))
                
                init_str = f"{init_vals[0]:.2f} / {line} / {init_vals[1]:.2f}"
                inst_str = f"{inst_vals[0]:.2f} / {inst_line} / {inst_vals[1]:.2f}"
                print(f"  {company:<12} | {init_str:<25} | {inst_str:<25}")
                
    except Exception as e:
        print(f"执行异常: {e}")

if __name__ == '__main__':
    matches = [
        {"id": "4459728", "home": "西班牙", "away": "奥地利"},
        {"id": "4459727", "home": "葡萄牙", "away": "克罗地亚"},
        {"id": "4459729", "home": "瑞士", "away": "阿尔及利亚"}
    ]
    for m in matches:
        check_match_odds(m["id"], m["home"], m["away"])
