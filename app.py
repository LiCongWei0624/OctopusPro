# -*- coding: utf-8 -*-
from flask import Flask, jsonify, render_template, request, send_from_directory
import json
import os
import datetime
from leisu_crawler import fetch_matches
from detail_scraper import get_complete_match_details, get_odds_detail_via_playwright
from scraper import scrape_desktop_matches

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

DATA_FILE = os.path.join(os.path.dirname(__file__), 'parsed_matches.json')
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')

DEFAULT_SYSTEM_PROMPT = "你是一位资深的足球数据分析大师与博彩盘口操盘专家。你的任务是根据用户提供的比赛基础信息、独家 SWOT 有利/不利情报、两队近 10 场历史交锋比分、两队近期战绩、伤停名单以及主流公司（如皇*、36*）的让球与总进球（大小球）初始/即时变盘水位数据，进行深度且符合逻辑的比赛研判。\n\n请严格根据以下维度进行分析，并输出 Markdown 格式的中文报告：\n1. **技战术与状态剖析**：分析两队攻防近况、主客战力及战意。\n2. **伤停影响对冲**：研判阵中核心球员缺席对各自战术体系带来的实质性变化。\n3. **博彩机构意图洞察**：对比让球盘口与大小球盘口从初始盘口到即时盘口的水位与盘口线变化（例如从2.5球升盘至2.75球），研判机构是在正向防范大球，还是通过水位拉力进行诱盘或阻盘。\n4. **综合推荐结论**：\n   - **胜平负方向预测**：给出明确胜平负结论与信心指数；\n   - **让球方向推荐**：给出临场赢盘方向；\n   - **大小球（总进球数）推荐**：明确指出是大球 Over 还是小球 Under，并给出临场进球盘口建议（例如大 2.5）；\n   - **精准比分预测**：提供 2-3 个最可能的完场比分；\n   - **同初盘/同走势历史赛果概率对比**：结合给出的历史相似初盘概率数据进行分析；若提供的数据中该项为空，你必须基于自身强大的历史足球赛事及指数大数据库，匹配出 2-3 场历史中初盘盘口与临场变盘走势（如一球退半球高水）完全相同的真实已完场比赛，列出具体球队对阵和比分，统计并列出在该相同走势下踢出来的胜、平、负真实比例，最终对比指出买哪边（主队还是客队，上盘还是下盘）胜率和投注期望更高。"

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def get_weekday_cn(date_obj):
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return weekdays[date_obj.weekday()]

def merge_date_matches(date_str, mobile_matches, desktop_matches):
    d = datetime.datetime.strptime(date_str, "%Y%m%d").date()
    target_date_formatted = f"{d.strftime('%m-%d')} {get_weekday_cn(d)}"
    
    existing_matches = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                existing_matches = json.load(f)
        except Exception:
            pass
            
    # Extract existing matches for target date by ID to do incremental merge
    existing_date_matches = {str(m['id']): m for m in existing_matches if m.get('date') == target_date_formatted}
    other_date_matches = [m for m in existing_matches if m.get('date') != target_date_formatted]
    
    formatted_new_matches = []
    seen_ids = set()
    
    # First process mobile matches
    for m in mobile_matches:
        match_id = str(m['match_id'])
        seen_ids.add(match_id)
        
        # If match already exists, update scores and status without erasing other fields (probabilities, similar outcomes etc.)
        if match_id in existing_date_matches:
            item = existing_date_matches[match_id].copy()
            item['score'] = f"{m['home_score']}-{m['away_score']}" if m.get('status', 1) in [2, 3, 4, 5, 7, 8] else ""
            item['half_score'] = m.get('half_score', '')
            item['penalty_score'] = m.get('penalty_score', '')
            item['status'] = m.get('status', 1)
            formatted_new_matches.append(item)
        else:
            # 直接根据比赛本身的 match_time 计算出精确格式化日期，防止被接口日期参数污染导致错位
            try:
                m_time_part = m['match_time'].split(' ')
                m_date_obj = datetime.datetime.strptime(m_time_part[0], "%Y-%m-%d").date()
                exact_date_formatted = f"{m_date_obj.strftime('%m-%d')} {get_weekday_cn(m_date_obj)}"
            except Exception:
                exact_date_formatted = target_date_formatted
                
            formatted_new_matches.append({
                'id': match_id,
                'date': exact_date_formatted,
                'time': m['match_time'].split(' ')[1][:5],
                'competition': m['competition'],
                'home_team': m['home_team'],
                'home_rank': '',
                'away_team': m['away_team'],
                'away_rank': '',
                'win_probability': {},
                'similar_trend': {},
                'pros_cons': {'home': {'pros': [], 'cons': []}, 'away': {'pros': [], 'cons': []}},
                'score': f"{m['home_score']}-{m['away_score']}" if m.get('status', 1) in [2, 3, 4, 5, 7, 8] else "",
                'half_score': m.get('half_score', ''),
                'penalty_score': m.get('penalty_score', ''),
                'status': m.get('status', 1)
            })
            
    # Then add desktop matches as fallback and update scores/status for existing ones
    for dm in desktop_matches:
        match_id = str(dm['id'])
        # 寻找已由移动端创建的对应比赛
        existing_item = next((item for item in formatted_new_matches if str(item['id']) == match_id), None)
        
        if existing_item:
            # 优先采用 PC 网页端更实时的比分和比赛状态（如进行中、已结束）进行覆盖更新
            dm_status = dm.get('status', 1)
            dm_score = dm.get('score', '')
            if dm_status in [2, 3, 4, 5, 7, 8] or dm_score:
                existing_item['status'] = dm_status
                existing_item['score'] = dm_score
                existing_item['half_score'] = dm.get('half_score', '')
                existing_item['penalty_score'] = dm.get('penalty_score', '')
            # 补全缺失的时间或更新日期
            if dm.get('time') and not existing_item.get('time'):
                existing_item['time'] = dm['time']
            if dm.get('date') and existing_item.get('date') != dm['date']:
                existing_item['date'] = dm['date']
        else:
            seen_ids.add(match_id)
            if match_id in existing_date_matches:
                item = existing_date_matches[match_id].copy()
                item['score'] = dm['score']
                item['half_score'] = dm.get('half_score', '')
                item['penalty_score'] = dm.get('penalty_score', '')
                item['status'] = dm.get('status', 1)
                # 补全缺失的时间或更新日期
                if dm.get('time') and not item.get('time'):
                    item['time'] = dm['time']
                if dm.get('date') and item.get('date') != dm['date']:
                    item['date'] = dm['date']
                formatted_new_matches.append(item)
            else:
                # 优先保留 PC 网页端根据时间戳精密计算出来的真实比赛日期
                exact_date = dm.get('date') if dm.get('date') else target_date_formatted
                formatted_new_matches.append({
                    'id': match_id,
                    'date': exact_date,
                    'time': dm['time'],
                    'competition': dm['competition'],
                    'home_team': dm['home_team'],
                    'home_rank': '',
                    'away_team': dm['away_team'],
                    'away_rank': '',
                    'win_probability': {},
                    'similar_trend': {},
                    'pros_cons': {'home': {'pros': [], 'cons': []}, 'away': {'pros': [], 'cons': []}},
                    'score': dm['score'],
                    'half_score': dm.get('half_score', ''),
                    'penalty_score': dm.get('penalty_score', ''),
                    'status': dm.get('status', 1)
                })
                
    # CRITICAL: Keep matches that are in local database but missing in current crawl!
    for match_id, old_match in existing_date_matches.items():
        if match_id not in seen_ids:
            formatted_new_matches.append(old_match)
            
    # Guard: prevent empty merged list due to accidental crawl error
    if not formatted_new_matches and existing_date_matches:
        print(f"Warning: Merged list is empty for {target_date_formatted}, restoring local cache.")
        return existing_matches
        
    other_date_matches.extend(formatted_new_matches)
    
    # Sort matches by time
    try:
        other_date_matches.sort(key=lambda x: (x.get('date', ''), x.get('time', '')))
    except Exception:
        pass
        
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(other_date_matches, f, ensure_ascii=False, indent=2)
        
    return formatted_new_matches
    
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'ai_config.json')

@app.route('/api/ai_config', methods=['GET'])
def get_ai_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # 若系统提示词读取出为空，自动填充默认值，确保配置页面能正常展示
            if not config.get('system_prompt'):
                config['system_prompt'] = DEFAULT_SYSTEM_PROMPT
            return jsonify({'success': True, 'data': config})
        except Exception as e:
            pass
    # 默认值兜底，避免全新部署时文件不存在导致前端加载卡死
    default_config = {
        'api_key': '',
        'api_base': 'https://opencode.ai/zen/v1',
        'model_name': 'deepseek-v4-flash-free',
        'system_prompt': DEFAULT_SYSTEM_PROMPT
    }
    return jsonify({'success': True, 'data': default_config})

@app.route('/api/ai_config', methods=['POST'])
def save_ai_config():
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': "Empty data"})
    
    config = {
        'api_key': data.get('api_key', ''),
        'api_base': data.get('api_base', 'https://opencode.ai/zen/v1'),
        'model_name': data.get('model_name', 'minimax-m2.5-free'),
        'system_prompt': data.get('system_prompt', '')
    }
    
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True, 'message': "Config saved successfully"})
    except Exception as e:
        return jsonify({'success': False, 'error': f"Write config error: {str(e)}"})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/matches')
def get_matches():
    today_str = request.args.get('today')
    if not today_str:
        today_str = datetime.date.today().strftime('%Y%m%d')
        
    has_today = False
    data = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            d = datetime.datetime.strptime(today_str, "%Y%m%d").date()
            target_date_formatted = f"{d.strftime('%m-%d')} {get_weekday_cn(d)}"
            for m in data:
                if m.get('date') == target_date_formatted:
                    has_today = True
                    break
        except Exception:
            pass
            
    if not has_today:
        try:
            new_matches = fetch_matches(today_str, n_values=[1, 2, 3, 4, 5, 7])
            desktop_matches = []
            try:
                desktop_matches = scrape_desktop_matches(today_str)
            except Exception as de:
                print("Failed to scrape desktop matches:", de)
            data = merge_date_matches(today_str, new_matches, desktop_matches)
        except Exception as e:
            if not data:
                return jsonify({'success': False, 'error': f"Failed to fetch initial matches: {str(e)}"})
                
    return jsonify({'success': True, 'data': data})

@app.route('/api/refresh')
def refresh_matches():
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.date.today().strftime('%Y%m%d')
        
    try:
        new_matches = fetch_matches(date_str, n_values=[1, 2, 3, 4, 5, 7])
        desktop_matches = []
        try:
            desktop_matches = scrape_desktop_matches(date_str)
        except Exception as de:
            print("Failed to scrape desktop matches:", de)
        updated_list = merge_date_matches(date_str, new_matches, desktop_matches)
        return jsonify({'success': True, 'data': updated_list})
    except Exception as e:
        return jsonify({'success': False, 'error': f"Refresh failed: {str(e)}"})

@app.route('/api/match_details')
def get_match_details():
    match_id = request.args.get('id')
    home = request.args.get('home')
    away = request.args.get('away')
    force = request.args.get('force', 'false') == 'true'
    
    if not match_id or not home or not away:
        return jsonify({'success': False, 'error': 'Missing required parameters: id, home, away'})
        
    # Check if the match is finished by looking it up in parsed_matches.json
    is_finished = False
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                matches = json.load(f)
            for m in matches:
                if str(m.get('id')) == str(match_id):
                    # Check if status code is 8 (finished)
                    if m.get('status') == 8 or m.get('status') == '8':
                        is_finished = True
                    break
        except Exception:
            pass
            
    if force:
        ai_cache_file = os.path.join(CACHE_DIR, f'ai_analysis_{match_id}.json')
        if os.path.exists(ai_cache_file):
            try:
                os.remove(ai_cache_file)
            except Exception:
                pass
            
    cache_file = os.path.join(CACHE_DIR, f'details_{match_id}.json')
    
    # Only load from cache if the match is finished AND force is False
    if not force and is_finished and os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({'success': True, 'data': data})
        except Exception as e:
            pass # fallback to scrape
            
    try:
        details = get_complete_match_details(match_id, home, away)
        # Only write to cache if the match is finished
        if is_finished:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(details, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True, 'data': details})
    except Exception as e:
        return jsonify({'success': False, 'error': f"Failed to fetch match details: {str(e)}"})

@app.route('/api/match_odds_detail')
def get_odds_detail():
    match_id = request.args.get('match_id')
    cid = request.args.get('cid')
    type_val = request.args.get('type')
    
    if not match_id or not cid or not type_val:
        return jsonify({'success': False, 'error': 'Missing required parameters: match_id, cid, type'})
        
    # Check if the match is finished by looking it up in parsed_matches.json
    is_finished = False
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                matches = json.load(f)
            for m in matches:
                if str(m.get('id')) == str(match_id):
                    # Check if status code is 8 (finished)
                    if m.get('status') == 8 or m.get('status') == '8':
                        is_finished = True
                    break
        except Exception:
            pass
            
    cache_file = os.path.join(CACHE_DIR, f'odds_detail_{match_id}_{cid}_{type_val}.json')
    if is_finished and os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({'success': True, 'data': data})
        except Exception:
            pass
            
    try:
        data = get_odds_detail_via_playwright(match_id, cid, type_val)
        if isinstance(data, dict) and 'error' in data:
            err_msg = data.get('error', '')
            if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
                friendly_error = "该指数变盘详情获取超时，可能因雷速服务器瞬时防爬保护限制，请稍候重试"
            elif "waf" in err_msg.lower() or "captcha" in err_msg.lower():
                friendly_error = "该比赛变盘明细受到安全限制，请在赛事列表上点击‘同步最新赛事’后重试"
            else:
                friendly_error = f"获取指数走势失败: {err_msg}"
            return jsonify({'success': False, 'error': friendly_error})
            
        if data is not None:
            if is_finished:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            return jsonify({'success': True, 'data': data})
        else:
            return jsonify({'success': False, 'error': '暂无该公司的指数走势明细数据'})
    except Exception as e:
        return jsonify({'success': False, 'error': f"系统请求异常: {str(e)}"})
def get_cached_odds_detail(match_id, cid):
    all_tables = []
    has_cache = False
    for type_val in ["1", "2", "3"]:
        cache_file = os.path.join(CACHE_DIR, f'odds_detail_{match_id}_{cid}_{type_val}.json')
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list) and data:
                        all_tables.append(data)
                        has_cache = True
                        continue
            except Exception:
                pass
        all_tables.append([])
    return all_tables if has_cache else None

@app.route('/api/match_ai_analysis', methods=['POST'])
def match_ai_analysis():
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': 'Missing request body'})
        
    match_id = data.get('match_id')
    home = data.get('home_team')
    away = data.get('away_team')
    force = data.get('force') == True
    
    if not match_id or not home or not away:
        return jsonify({'success': False, 'error': 'Missing match details (id, home_team, away_team)'})
        
    # 1. Read config from ai_config.json database
    api_key = ""
    api_base = "https://opencode.ai/zen/v1"
    model_name = "minimax-m2.5-free"
    system_prompt = ""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                api_key = cfg.get('api_key', '')
                api_base = cfg.get('api_base', 'https://opencode.ai/zen/v1')
                model_name = cfg.get('model_name', 'minimax-m2.5-free')
                system_prompt = cfg.get('system_prompt', '')
        except Exception:
            pass
            
    # 如果读取出的系统提示词为空，也使用预设兜底，保证分析请求完全闭环
    if not system_prompt:
        system_prompt = DEFAULT_SYSTEM_PROMPT
            
    if not api_key:
        return jsonify({'success': False, 'error': '请先在顶部“AI配置中心”中配置您的 API Key。'})
        
    # 2. Check if AI analysis cache exists and force is False
    ai_cache_file = os.path.join(CACHE_DIR, f'ai_analysis_{match_id}.json')
    if not force and os.path.exists(ai_cache_file):
        try:
            with open(ai_cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            return jsonify({'success': True, 'cached': True, 'text': cache_data.get('text', '')})
        except Exception:
            pass

    # 3. Get latest match details
    details_cache_file = os.path.join(CACHE_DIR, f'details_{match_id}.json')
    details = None
    if not force and os.path.exists(details_cache_file):
        try:
            with open(details_cache_file, 'r', encoding='utf-8') as f:
                details = json.load(f)
        except Exception:
            pass
            
    if not details:
        try:
            details = get_complete_match_details(match_id, home, away)
        except Exception as e:
            return jsonify({'success': False, 'error': f"获取比赛详情数据失败: {str(e)}"})

    # 2.5 尝试从 parsed_matches.json 数据库中获取当前比赛的 similar_trend 和 win_probability
    similar_trend_data = {}
    win_probability_data = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                all_matches = json.load(f)
            for m in all_matches:
                if str(m.get('id')) == str(match_id):
                    similar_trend_data = m.get('similar_trend', {})
                    win_probability_data = m.get('win_probability', {})
                    break
        except Exception as e_db:
            print("Failed to load match meta from parsed_matches:", e_db)

    # 4. Assemble match context text
    context_lines = []
    context_lines.append(f"【比赛信息】")
    context_lines.append(f"赛事竞争：{details.get('competition', '') or '未知赛事'}")
    context_lines.append(f"对阵双方：主队 {home} vs 客队 {away}")
    
    # 历史同盘口打出概率
    if similar_trend_data and similar_trend_data.get('stats'):
        context_lines.append(f"\n【历史相似初盘走势与胜平负比例统计】")
        context_lines.append(f"描述：{similar_trend_data.get('description', '')}")
        for stat in similar_trend_data.get('stats', []):
            context_lines.append(f"- 结果: {stat.get('outcome', '')} | 概率/比例: {stat.get('percentage', '')}")
            
    if win_probability_data:
        context_lines.append(f"\n【智能 AI 胜率预测概率】")
        context_lines.append(f"- 主胜概率: {win_probability_data.get('home', '未知')}")
        context_lines.append(f"- 客胜概率: {win_probability_data.get('away', '未知')}")

    # SWOT
    swot = details.get('pros_cons', {})
    context_lines.append(f"\n【独家 SWOT 有利/不利情报】")
    context_lines.append(f"主队有利情报：")
    for item in swot.get('home', {}).get('pros', []):
        context_lines.append(f"- {item}")
    context_lines.append(f"主队不利情报：")
    for item in swot.get('home', {}).get('cons', []):
        context_lines.append(f"- {item}")
    context_lines.append(f"客队有利情报：")
    for item in swot.get('away', {}).get('pros', []):
        context_lines.append(f"- {item}")
    context_lines.append(f"客队不利情报：")
    for item in swot.get('away', {}).get('cons', []):
        context_lines.append(f"- {item}")
        
    # H2H
    h2h_data = details.get('h2h', {})
    h2h_matches = h2h_data.get('matches', []) if isinstance(h2h_data, dict) else []
    context_lines.append(f"\n【历史对决交锋战绩 (近10场)】")
    for idx, match in enumerate(h2h_matches[:10]):
        context_lines.append(f"{idx+1}. {match.get('date', '')} {match.get('home', '')} {match.get('score', '')} {match.get('away', '')} (赛事: {match.get('competition', '')}, 结果: {match.get('result', '')})")
        
    # Recent Form
    recent = details.get('recent_results', {})
    recent_home = recent.get('home', []) if isinstance(recent, dict) else []
    recent_away = recent.get('away', []) if isinstance(recent, dict) else []
    context_lines.append(f"\n【两队近期战绩】")
    context_lines.append(f"主队 {home} 近期战绩：")
    for idx, match in enumerate(recent_home[:10]):
        context_lines.append(f"- {match.get('date', '')} {match.get('home', '')} {match.get('score', '')} {match.get('away', '')} (赛事: {match.get('competition', '')}, 结果: {match.get('result', '')})")
    context_lines.append(f"客队 {away} 近期战绩：")
    for idx, match in enumerate(recent_away[:10]):
        context_lines.append(f"- {match.get('date', '')} {match.get('home', '')} {match.get('score', '')} {match.get('away', '')} (赛事: {match.get('competition', '')}, 结果: {match.get('result', '')})")

    # Injuries
    injuries = details.get('injuries', {})
    injuries_home = injuries.get('home', {}) if isinstance(injuries, dict) else {}
    injuries_away = injuries.get('away', {}) if isinstance(injuries, dict) else {}
    context_lines.append(f"\n【伤停与缺阵名单】")
    context_lines.append(f"主队伤停：")
    for p in injuries_home.get('injuries', []):
        context_lines.append(f"- 伤病: {p.get('name', '')} ({p.get('position', '')}) - 原因: {p.get('reason', '')} - 状态: {p.get('status', '')}")
    for p in injuries_home.get('suspensions', []):
        context_lines.append(f"- 停赛: {p.get('name', '')} ({p.get('position', '')}) - 原因: {p.get('reason', '')} - 状态: {p.get('status', '')}")
    context_lines.append(f"客队伤停：")
    for p in injuries_away.get('injuries', []):
        context_lines.append(f"- 伤病: {p.get('name', '')} ({p.get('position', '')}) - 原因: {p.get('reason', '')} - 状态: {p.get('status', '')}")
    for p in injuries_away.get('suspensions', []):
        context_lines.append(f"- 停赛: {p.get('name', '')} ({p.get('position', '')}) - 原因: {p.get('reason', '')} - 状态: {p.get('status', '')}")

    # Odds
    odds_index = details.get('odds_index', [])
    context_lines.append(f"\n【赔率指数初始与即时变盘水位数据】")
    
    # 1x2 (europe)
    context_lines.append(f"胜平负 (1x2) 盘口数据：")
    for item in odds_index:
        company = item.get('company')
        eu = item.get('europe', {})
        init = eu.get('initial', [1.0, 1.0, 1.0])
        inst = eu.get('instant', [1.0, 1.0, 1.0])
        context_lines.append(f"- 公司: {company} | 初始赔率: 主胜 {init[0]} 平局 {init[1]} 客胜 {init[2]} | 即时赔率: 主胜 {inst[0]} 平局 {inst[1]} 客胜 {inst[2]}")
        
    # Handicap
    context_lines.append(f"让球 (Handicap) 盘口数据：")
    for item in odds_index:
        company = item.get('company')
        h = item.get('handicap', {})
        init = h.get('initial', [1.0, 1.0])
        inst = h.get('instant', [1.0, 1.0])
        context_lines.append(f"- 公司: {company} | 初始盘口: {h.get('initial_line', '')} (主水 {init[0]} / 客水 {init[1]}) | 即时盘口: {h.get('instant_line', '')} (主水 {inst[0]} / 客水 {inst[1]})")
        
    # Over/Under
    context_lines.append(f"大小球总进球 (Over/Under) 盘口数据：")
    for item in odds_index:
        company = item.get('company')
        ou = item.get('over_under', {})
        init = ou.get('initial', [1.0, 1.0])
        inst = ou.get('instant', [1.0, 1.0])
        context_lines.append(f"- 公司: {company} | 初始盘口: {ou.get('initial_line', '')} (大球水 {init[0]} / 小球水 {init[1]}) | 即时盘口: {ou.get('instant_line', '')} (大球水 {inst[0]} / 小球水 {inst[1]})")

    # 3.8 获取主流公司 (36*, 皇*) 的全量变盘历史明细
    context_lines.append(f"\n【核心指数庄家 (36*、皇*) 变盘历史走势明细】")
    for company_name, cid in [("36*", "2"), ("皇*", "3")]:
        try:
            cached_trend = get_cached_odds_detail(match_id, cid)
            if cached_trend:
                print(f"AI Analysis: Successfully loaded cached odds details for {company_name} (cid {cid}).")
                all_tables = cached_trend
            else:
                print(f"AI Analysis: No local cache found for {company_name} (cid {cid}). Skipping historical trend logs to save time and bypass WAF.")
                all_tables = []
                    
            if all_tables and len(all_tables) >= 3:
                # 0 -> 让球, 1 -> 胜平负, 2 -> 大小球
                table_names = ["让球 (Handicap)", "胜平负 (1X2)", "大小球 (Over/Under)"]
                for tbl_idx, rows in enumerate(all_tables[:3]):
                    t_name = table_names[tbl_idx]
                    context_lines.append(f"- {company_name} {t_name} 变盘路径 (按时间倒序，最近 10 次变盘):")
                    if not rows:
                        context_lines.append("  (暂无该项变盘明细)")
                        continue
                    # 只取前 10 个最接近当前时间的变盘
                    for r in rows[:10]:
                        time_str = r.get('change_time', '')
                        if tbl_idx == 1:
                            # 欧赔
                            context_lines.append(f"  * 时间: {time_str} | 主胜 {r.get('home')} | 平局 {r.get('draw')} | 客胜 {r.get('away')}")
                        else:
                            # 让球/大小球
                            context_lines.append(f"  * 时间: {time_str} | 盘口 {r.get('line')} | 上/大 {r.get('home')} | 下/小 {r.get('away')}")
            else:
                context_lines.append(f"- {company_name} 指数变盘走势: 获取超时或受风控限制")
        except Exception as e_trend:
            print(f"AI Analysis: Pre-fetch for {company_name} failed: {e_trend}")
            context_lines.append(f"- {company_name} 指数变盘走势: 加载异常 ({str(e_trend)})")

    context_str = "\n".join(context_lines)
    
    print("\n" + "="*40 + f" 发送给 AI 的真实数据 Context [比赛 {match_id}]: " + "="*40)
    print(context_str)
    print("="*110 + "\n")
    
    # 5. Connect to OpenCode Zen API for streaming response
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    url = f"{api_base}/chat/completions"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请针对以下赛事数据进行深度研判。特别是要根据这场的盘口走势，去匹配历史已踢完的相同盘口的比赛，仔细比对其中的【历史相似初盘走势与胜平负比例统计】数据，列出踢出来的胜、平、负真实比例。通过对比同样的盘口与走势变化下胜率的概率学分布，研判得出买哪边赢盘或赢球的胜率期望更高，并在新增的“同初盘/同走势历史赛果概率对比”结论中给出明确倾向推荐：\n\n{context_str}"}
        ],
        "stream": True
    }
    
    def generate():
        import requests
        try:
            r = requests.post(url, headers=headers, json=payload, stream=True, timeout=60)
            if r.status_code != 200:
                error_msg = f"大模型接口请求失败: HTTP {r.status_code} - {r.text}"
                yield f"data: {json.dumps({'error': error_msg})}\n\n"
                return
                
            full_text = []
            for line in r.iter_lines():
                if line:
                    decoded = line.decode('utf-8')
                    if decoded.startswith("data:"):
                        data_content = decoded[5:].strip()
                        if data_content == "[DONE]":
                            break
                        try:
                            chunk_json = json.loads(data_content)
                            delta = chunk_json.get('choices', [{}])[0].get('delta', {})
                            content = delta.get('content', '')
                            if content:
                                full_text.append(content)
                                yield f"data: {json.dumps({'text': content})}\n\n"
                        except Exception:
                            pass
            
            # Cache complete response
            if full_text:
                complete_predicted = "".join(full_text)
                try:
                    with open(ai_cache_file, 'w', encoding='utf-8') as cache_f:
                        json.dump({'text': complete_predicted}, cache_f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
                    
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    from flask import Response
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    # Run locally or on server port 5000, listening on all interfaces
    app.run(host='0.0.0.0', port=5000)
