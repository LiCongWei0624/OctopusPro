#!/usr/bin/env python3
"""
批量采集与分析脚本 — 用于收集 dual-market-v3 新策略的首次 ROI 样本

用法:
  export LINSHU_AI_API_KEY='sk-...'
  cd /home/hermesprojects/OctopusPro
  nohup python3 batch_collect.py > batch_collect.log 2>&1 &

每次运行结果保存到 batch_results/ 目录。
"""
import os, sys, json, time, tempfile, traceback
from datetime import datetime
from unittest.mock import patch

# 请确保在项目根目录运行
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import app
import detail_scraper as d
from leisu_crawler import fetch_matches

# ============ 配置 ============
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'batch_results')
os.makedirs(OUTPUT_DIR, exist_ok=True)
API_KEY = os.environ.get('LINSHU_AI_API_KEY') or os.environ.get('OPENAI_API_KEY', '')
MAX_MATCHES = 55
PARALLEL_MAX = 2  # 同时最多分析 X 场（受 semaphore 限制）

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)

def collect_and_analyze(mid, home, away, idx, total):
    """采集并分析一场比赛"""
    log(f'[{idx}/{total}] 开始 {home} vs {away} ({mid})')
    
    d.ODDS_DEBUG_LOG.clear()
    d._SERVER_TIME_CACHE.update({'value': None, 'monotonic': 0.0})
    d.GLOBAL_ODDS_CJ.clear()
    
    t_start = time.monotonic()
    result = {
        'match_id': mid, 'home': home, 'away': away,
        'started_at': datetime.now().isoformat(),
        'status': 'failed', 'error': None,
        'phases': {},
    }
    
    # 1. 赔率列表
    try:
        t0 = time.monotonic()
        odds = d.get_real_odds(mid)
        result['phases']['odds_list'] = round(time.monotonic() - t0, 2)
        if not odds:
            result['error'] = '赔率列表为空'
            return result
        if len(odds) < 3:
            result['warning'] = f'仅获取 {len(odds)} 家公司'
    except Exception as e:
        result['error'] = f'赔率获取失败: {e}'
        return result
    
    # 2. 构建详情
    details = {
        'competition': '',
        'odds_index': odds,
        'standings': [], 'goal_distribution': {}, 'half_full_stats': [],
        'h2h': {'matches': []},
        'recent_results': {'home': [], 'away': []},
        'pros_cons': {'home': {'pros': [], 'cons': []}, 'away': {'pros': [], 'cons': []}},
        'injuries': {'home': {}, 'away': {}},
    }
    
    # 3. 走势刷新
    try:
        with tempfile.TemporaryDirectory() as cache_dir, \
             patch.object(app, 'CACHE_DIR', cache_dir), \
             patch.object(app, 'TREND_REQUEST_MIN_INTERVAL_SECONDS', 0.1):
            
            app._trend_next_request_at = 0.0
            t1 = time.monotonic()
            trends_ok, trend_error, trend_quality = app._refresh_required_trend_history(
                mid, odds, 'prematch'
            )
            result['phases']['trend_refresh'] = round(time.monotonic() - t1, 2)
            
            if not trends_ok:
                result['error'] = f'走势刷新失败: {trend_error}'
                result['trend_quality'] = trend_quality
                return result
            result['trend_quality'] = trend_quality
            
            # 4. 构建上下文
            t2 = time.monotonic()
            success, ctx_error, context = app.build_match_prompt_context(
                mid, home, away, 'prematch',
                details=details, trend_quality=trend_quality
            )
            result['phases']['context_build'] = round(time.monotonic() - t2, 2)
            
            if not success:
                result['error'] = f'上下文构建失败: {ctx_error}'
                return result
            result['context_len'] = len(context)
            
            # 5. AI 配置
            config_ok, config_err, runtime = app._load_ai_runtime_config()
            if not config_ok:
                result['error'] = f'AI配置失败: {config_err}'
                return result
            
            # 6. 生成预测
            market_catalog = app._instant_market_catalog(
                details, app._build_probability_baseline(details, home, away)
            )
            prediction_metadata = {
                'match_id': mid, 'home_team': home, 'away_team': away,
                'kickoff': '', 'competition': '', 'fixture_date': '',
                'fixture_status': 1, 'analysis_mode': 'prematch',
                'strategy_version': app.STRATEGY_VERSION,
                'tracking_cohort_id': 'default',
                'tracking_cohort_name': '批量采集',
                'market_catalog': market_catalog,
            }
            
            ai_cache_file = os.path.join(cache_dir, f'ai_{mid}.json')
            task_key = f"batch-{mid}"
            snapshot = {
                'trend_quality': trend_quality,
                'market_catalog': market_catalog,
                'hash': 'batch',
                'market_hash': app._market_snapshot_hash(details),
                'captured_at': datetime.now().isoformat(),
            }
            
            app.ai_tasks[task_key] = {
                'status': 'processing', 'reports': ['', '', ''],
                'status_list': ['processing', 'processing', 'processing'],
                'final_ticket': '', 'analyst_inputs': [None, None, None],
                'analyst_outputs': [None, None, None],
                'cro_input': None, 'cro_output': None,
                'started_at': time.time(), 'heartbeat_at': time.time(),
                'snapshot_hash': 'batch', 'analysis_input': context,
                'trace_id': f'batch-{mid}',
            }
            
            try:
                t3 = time.monotonic()
                app.run_ai_analysis_thread(
                    mid, runtime['api_base'], runtime['api_key'],
                    runtime['model_name'], runtime['system_prompt'], context,
                    ai_cache_file, prediction_metadata, 'prematch',
                    task_key=task_key, snapshot=snapshot,
                )
                result['phases']['ai_generation'] = round(time.monotonic() - t3, 2)
                
                task = app.ai_tasks.get(task_key, {})
                result['reports'] = task.get('reports', [])
                result['final_ticket'] = task.get('final_ticket', '')
                result['version_completed'] = sum(1 for r in result['reports'] if app.has_final_output(r))
                result['cro_completed'] = app.has_final_output(result.get('final_ticket', ''))
                
                # 提取 prediction_record
                import re
                for r in result.get('reports', []):
                    blocks = re.findall(r'```json\s*([\s\S]*?)```', r)
                    for b in blocks:
                        try:
                            jd = json.loads(b)
                            pred = jd.get('prediction_record', {})
                            if pred.get('status') != 'unknown':
                                result['prediction'] = pred
                                break
                        except: pass
                    if 'prediction' in result:
                        break
                
                if result.get('version_completed', 0) >= 2:
                    result['status'] = 'completed'
                elif result.get('version_completed', 0) >= 1:
                    result['status'] = 'partial'
                else:
                    result['status'] = 'failed'
                    result['error'] = '无可用报告'
                    
            except Exception as e:
                result['error'] = f'AI生成失败: {e}'
                
    except Exception as e:
        result['error'] = f'数据阶段失败: {e}'
        traceback.print_exc()
    
    result['elapsed_seconds'] = round(time.monotonic() - t_start, 1)
    return result


def main():
    # 获取今天的匹配列表
    log('加载比赛列表...')
    matches = json.loads(open('parsed_matches.json', encoding='utf-8').read())
    
    candidates = []
    for m in matches:
        status = int(m.get('status', 0) or 0)
        if status not in (1, 13):
            continue
        date = str(m.get('date', ''))
        # 只收集最近几天的未开赛比赛
        if '07-' not in date and '08-' not in date:
            continue
        ht = str(m.get('home_team', ''))
        at = str(m.get('away_team', ''))
        if not ht or not at:
            continue
        candidates.append((str(m['id']), ht, at,
                           m.get('competition', ''), m.get('time', '')))
    
    log(f'候选比赛: {len(candidates)} 场')
    candidates = candidates[:MAX_MATCHES]
    
    results = []
    completed = 0
    partial = 0
    failed = 0
    
    for idx, (mid, home, away, comp, kickoff) in enumerate(candidates, 1):
        res = collect_and_analyze(mid, home, away, idx, len(candidates))
        res['competition'] = comp
        res['kickoff'] = kickoff
        results.append(res)
        
        if res['status'] == 'completed':
            completed += 1
        elif res['status'] == 'partial':
            partial += 1
        else:
            failed += 1
        
        log(f'  → {res["status"]}  (完成{completed}+部分{partial}+失败{failed})')
        
        # 每5场保存一次中间结果
        if idx % 5 == 0 or idx == len(candidates):
            save_path = os.path.join(OUTPUT_DIR, f'batch_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{completed}ok.json')
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2, default=str)
            log(f'已保存中间结果: {save_path}')
        
        # 场次间隔
        if idx < len(candidates):
            wait = 3
            log(f'  等待 {wait}s...')
            time.sleep(wait)
    
    # 最终保存
    save_path = os.path.join(OUTPUT_DIR, f'final_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{completed}ok_{partial}partial_{failed}fail.json')
    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    
    log(f'\n{"="*50}')
    log(f'批量采集完成: 完成={completed} 部分={partial} 失败={failed} 总计={len(results)}')
    log(f'结果文件: {save_path}')


if __name__ == '__main__':
    if not API_KEY:
        print('错误: 请设置 LINSHU_AI_API_KEY 环境变量')
        sys.exit(1)
    os.environ['LINSHU_AI_API_KEY'] = API_KEY
    main()
