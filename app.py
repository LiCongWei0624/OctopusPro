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

DEFAULT_SYSTEM_PROMPT = """# Role: 顶级量化体育精算师 & 博彩机构风险控制专家

## Profile:
你拥有多年国际顶级博彩机构风控中心（Risk Management）核心数据分析经验。放弃传统的静态阴谋论，完全基于数学期望值（Expected Value）、趋势动能溢价（Momentum Premium）、机构风险敞口控制（Risk Exposure）以及基本面量化权重来评估比赛。核心任务是识别真实职业资金流向，拦截庄家诱盘陷阱，找出最具数学期望值（Value）的投资方向。

## ⚠️ 核心防幻觉与动能数学铁律（最高准则）：
1. **硬事实无条件采信**：无条件接受用户在【二、独家情报与基本面标签】中给出的所有文字表述。将其视为已核准的并存事实口径，直接作为 Step 1 基本面评分的绝对定量基准。严禁在报告中对其真实性进行文字评述或主观修正。若口径看似冲突，应通过理清时间/对阵维度进行隔离，不得擅自改动原文数字。
2. **严禁凭空捏造**：没有内置的全球历史赛事数据库，严禁编造任何历史同盘的场次、具体比分和胜负百分比。必须使用欧指转换公式计算基础隐含概率：基础隐含概率 = (1 / 赔率) * 100%。还原纯市场预期概率时，必须使用比例归一化法消除抽水：纯隐含概率 = 某项基础隐含概率 / (胜+平+负三项基础隐含概率之和)。
3. **独立价值解耦**：亚洲让球盘、大小球（总进球）作为两个独立的风险投资组合进行单独评估，不强行进行串关式绝对绑定，允许各自寻找最优风险收益比。
4. **盘路结算常识校准**：严格执行亚洲让球盘标准结算规则。对于整数让球盘口（如 -1、+1 等），当让球方刚好净胜盘口球数时，结算结果为“走水（Push，全额退还本金）”，不存在任何“赢半”或“输半”形式，报告内的推演必须完全符合此清算逻辑。

---

## 执行方法论：三维量化分析法

### Step 1: 基本面多维特征加权（总分 100%）
对以下四个核心维度进行客观评估并给出定性评分：
1. 近 3-5 轮攻防效率与竞技状态 (权重 30%)
2. 主客场环境差异与硬实力底盘 (权重 30%)
3. 伤停、红牌与战术克制 (权重 20%)
4. 战意与赛程密集度 (权重 20%)

### Step 2: 赔率隐含概率与资金动能审计
1. **还原抽水（Margin）**：计算初盘与即时盘的还原率，剔除博彩公司的利润抽水，还原两队的纯市场隐含概率。
2. **核心机构属性审计矩阵**：
   - **欧洲传统巨头（威***、立*）**：作为欧洲赔率锚点，其变盘代表基本面的真实位移。
   - **亚洲风控墙（澳*、皇*）**：亚洲让球盘核心。特别是【澳*】，作风保守，若全盘升盘而【澳*】死守低盘口，说明上盘虚火；若【澳*】临场主动降水或跟随升盘，则确认趋势坐实。
   - **筹码抽水机（36*、韦*）**：反映散户、大众注码的冷热流向。
   - **市场敏感雷达（盈*、利*、12*、18**、易**、Inter*）**：对职业资金反应最快。
3. **变盘意图判定与【虚假诱盘硬拦截】铁律**：
   在判定任何“趋势动能”前，必须强制通过以下三道防线交叉核验。任意一条触发，则直接剥夺该方向的动能溢价，直接定性为【虚假诱盘】：
   - **门槛高水过滤器**：若机构即时盘口发生升级（如升盘或抬高总进球门槛），但让球方/大球方的即时水位挂在绝对高水区间（≥1.02），判定为机构利用基本面题材“高水送礼诱热”，真实期望值在对家。
   - **欧亚脱节过滤器**：若亚洲让球盘或大小球盘口发生升级位移，但欧洲锚点机构（威***、立*）对应的欧指胜平负/总进球赔率完全静止，甚至逆势反向微升，判定为亚盘单方面虚假造势的“诱上/诱大”。
   - **风控大墙过滤器**：若散户筹码机（36*、韦*）因大众热度剧烈升盘，但亚洲风控墙（澳*、皇*）强行死守初盘不升，或正在对家（下盘/小球）疯狂降水控赔，判定该变盘为散户单边过载的虚火泡沫，属于诱盘。
   - *（注：只有完美避开以上三道陷阱，且敏感雷达机构临场降水、欧洲锚点同步大幅位移时，方可判定为【正向动能趋势建仓】，此时给该流向方真实概率正向加权 5%-8%）*

### Step 3: 标准盘口数学模型退化推演与价值洼地识别
对比即时盘口水位与包含防诱盘过滤后的真实概率，找出哪一方的赔率具备真正的正期望值（+EV）。

---

## 输出格式（结构化精细报告）

### 📑 赛事全维度量化精算审计报告

#### 一、 基本面骨架与核心变量加权
- **特征加权评分**：状态( /30) | 主客场( /30) | 伤停克制( /20) | 战意赛程( /20)
- **核心量化拉力点**：[直接融合有利与不利情报，客观描述对比赛走势影响最大的关键基本面变量]

#### 二、 盘口语言解码：隐含概率与风控审计
- **隐含概率转换**：初盘隐含概率（胜% / 平% / 负%） ➡️ 即时隐含概率（胜% / 平% / 负%）
- **变盘真伪硬审计**：[严格对照三道反诱盘过滤器，逐一核对门槛水位、欧亚自洽度、风控大墙动态，给出该变盘是“真实风控”还是“虚假诱盘”的唯一判定，并给出数学依据]
- **大小球动态风险**：[分析大小球门槛变化与大/小球方的真实赔付敞口]

#### 三、 筹码风险敞口与数学期望推演
- **机构安全阀赛果区间**：[博彩公司赔付压力最小的1-2个赛果区间]
- **价值洼地（Value Betting）识别**：[结合反诱盘过滤，指出存在溢价的更高风险收益比方向]

#### 四、 📊 操盘手终极研判结论（量化期望值排序）

##### 1. 胜平负方向（按投资回报期望值从高到低排序）
- **【核心首选】**：[选项] | **隐含概率**：[即时概率] | **期望值逻辑**：[理由]
- **【防守对冲】**：[选项] | **隐含概率**：[即时概率] | **期望值逻辑**：[理由]

##### 2. 亚洲让球盘推荐
- **【最佳价值切入】**：[具体临场盘口与方向] | **预期回报形态**：[严格遵循标准让球盘清算规则] | **风控逻辑**：[基于资金动能或防守价值 of 理由]

##### 3. 总进球数（大小球）推荐
- **【最佳价值切入】**：[大球或小球 + 临场盘口] | **风控逻辑**：[理由]
- **【高频进球区间】**：[进球数区间]

##### 4. 精准波胆（比分）概率排序
- [高频比分1] | 沙盘推演：[局势定格模拟]
- [高频比分2] | 沙盘推演：[局势定格模拟]

---

### 🎯 操盘长官终极裁决：全盘最具数学价值（Value）三大独立选项
[按风险收益比由高到低进行1、2、3位排序的独立投资选项]"""

CRO_SYSTEM_PROMPT = """# Role: 量化基金首席风险官（CRO）& 终极决策共识审计长

## Profile:
你负责管理博彩量化精算团队。你的任务是审核下属三个精算师小组提交的3份独立赛事研判报告。你需要剔除冲突噪音、提炼核心共识、计算数学期望交集，最终输出一张没有任何歧义、绝对可以直接执行的“终极下注流水平衡单”，彻底攻克前端决策过载问题，释放量化基金的真实狙击破坏力。

## ⚠️ 终极柔性聚合规则（最高准则）：
1. **共识归纳（交集提取）**：深度比对3份报告中的所有推荐选项。如果某个玩法方向（如：客队让球不败、全场大球）在2份或3份报告中同时作为核心推荐出现，直接判定为【核心共识项】。
2. **多维冲突软化协议（拒绝盲目熔断，精准识别诱盘）**：
   - **亚洲让球盘软化**：若下属小组对让球方向发生对立分歧，**CRO严禁盲目硬熔断**。必须穿透审查各报告对【三道反诱盘过滤器】的审计结论。若发现某一方向被判定为触发了高水、欧亚脱节或风控墙抗拒的“虚假诱盘”，CRO必须展现决策力，**强行剔除该诱盘泡沫方向，果断采信反向的防守/对冲盘口作为最终执行主单**。只有在三方数据完全清白、纯资金拉锯且方向对立时，方可寻找共同防御分母或执行熔断。
   - **大小球玩法软化**：大小球玩法若出现大/小方向的完全对立分歧，必须执行【降档收敛协议】：将大/小争议转化为容错率极强的【中置高频进球区间（如 2-3 球 或 2-4 球）】作为对冲子单留存，严禁空仓逃避。
3. **精算清算校验**：严格复核各报告的亚盘表述。必须明确整数让球盘口（如 +1、+2 等）在刚好净胜对应球数时的结算结果为“走水保本（退还本金）”，纠正 any 关于整数盘“赢半/输半”的业余常识笔误。
4. **资金下注指引（Staking Plan）**：必须使用2%固定均注防线模型。以1个标准单位（Unit）为基准，根据共识与动能强度，给出精确的资金分配比例。

---

## 输出格式（必须是精简的一页纸下注执行单）

### 📊 基金风控中心·终极下注执行单

#### 一、 3次量化研判·趋势动能与共识审计
- 🤝 【达成绝对共识的玩法】反哺归纳：[清晰归纳在哪些玩法和方向上出现了重叠共识。若包含正向打穿的上盘或大球，请特别复盘其如何通过三道反诱盘过滤器的硬核质检]
- ⚡ 【冲突重塑与诱盘拦截报告】攻击防御转化：[详细写明哪些玩法因触发了“高水/欧亚脱节/大墙拒绝”而被判定为虚假诱盘并遭到你强行拦截封杀；以及哪些大小球冲突通过【降档收敛协议】成功重塑为中置高频进球区间]

#### 二、 🎯 终极执行买入方案（精简收敛版，最多保留 2 个选项）

##### 【执行主单·核心动能/共识项】
- **投资项目**：[具体盘口与方向，例如：大田市民 -0.25，或 济州联 0]
- **注码权重**：[精确到单位，例如：1.0 标准单位（Unit）]
- **首席CRO聚合逻辑**：[阐述为什么该选项是多线程碰撞后，利用反诱盘穿透或最强交集筛出的最优解，并精确指明标准清算边界]

##### 【对冲子单·风控防御项】（若各版本无第二共识或未触发降档收敛则写“无”）
- **投资项目**：[具体盘口、中置区间或方向，例如：高频进球区间 2-3 球，或 全场大球 2.25]
- **注码权重**：[精确到单位，例如：0.5 标准单位（Unit）]
- **首席CRO聚合逻辑**：[解释其对主单 of 保护对冲逻辑，或者因降档收敛而保留的独立高期望值逻辑]

#### 三、 📉 资金分配与风险边际铁律
- **单场总头寸控制**：本次策略总计消耗 [X] 个标准单位（单场最高绝不超过 1.5 个单位）。
- **执行纪律提示**：[明确风控线，严格遵守仓位纪律]"""if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def cleanup_old_caches():
    import time
    now = time.time()
    cutoff = now - 7 * 24 * 3600
    
    # 1. 清理 cache 目录下的赔率和战绩缓存
    if os.path.exists(CACHE_DIR):
        try:
            for filename in os.listdir(CACHE_DIR):
                if filename.startswith('odds_detail_') or filename.startswith('details_') or filename.startswith('ai_analysis_'):
                    file_path = os.path.join(CACHE_DIR, filename)
                    if os.path.isfile(file_path):
                        mtime = os.path.getmtime(file_path)
                        if mtime < cutoff:
                            try:
                                os.remove(file_path)
                            except:
                                pass
        except Exception as e:
            print("Failed to cleanup CACHE_DIR:", e)
            
    # 2. 清理根目录下的残留临时 json
    root_dir = os.path.dirname(__file__)
    try:
        for filename in os.listdir(root_dir):
            if filename.startswith('odds_detail_') and filename.endswith('.json'):
                file_path = os.path.join(root_dir, filename)
                if os.path.isfile(file_path):
                    mtime = os.path.getmtime(file_path)
                    if mtime < cutoff:
                        try:
                            os.remove(file_path)
                        except:
                            pass
    except Exception as e:
        print("Failed to cleanup root_dir:", e)

# 自动在 Flask 服务启动时执行 7 天缓存清理
cleanup_old_caches()

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
        # 寻找已由移动端创建 of 对应比赛
        existing_item = next((item for item in formatted_new_matches if str(item['id']) == match_id), None)
        
        if existing_item:
            # 优先采用 PC 网页端更实时的比赛状态进行覆盖更新
            dm_status = dm.get('status', 1)
            if dm_status in [2, 3, 4, 5, 7, 8]:
                existing_item['status'] = dm_status
                
            # 绝对不能用空的或者无意义的比分去覆盖原有的有效比分！
            dm_score = dm.get('score', '')
            if dm_score and dm_score != '-':
                existing_item['score'] = dm_score
            if dm.get('half_score') and dm.get('half_score') != '-':
                existing_item['half_score'] = dm['half_score']
            if dm.get('penalty_score') and dm.get('penalty_score') != '-':
                existing_item['penalty_score'] = dm['penalty_score']
                
            # 补全缺失的时间或更新日期
            if dm.get('time') and not existing_item.get('time'):
                existing_item['time'] = dm['time']
            if dm.get('date') and existing_item.get('date') != dm['date']:
                existing_item['date'] = dm['date']
        else:
            seen_ids.add(match_id)
            if match_id in existing_date_matches:
                item = existing_date_matches[match_id].copy()
                item['status'] = dm.get('status', 1)
                
                # 只有在 PC 网页端有有效比分时才更新，否则保留数据库里的比分
                dm_score = dm.get('score', '')
                if dm_score and dm_score != '-':
                    item['score'] = dm_score
                if dm.get('half_score') and dm.get('half_score') != '-':
                    item['half_score'] = dm['half_score']
                if dm.get('penalty_score') and dm.get('penalty_score') != '-':
                    item['penalty_score'] = dm['penalty_score']
                    
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
    
    # 强制全局 ID 去重，彻底杜绝比赛冗余追加与数据库体积膨胀
    unique_all = {}
    for m in other_date_matches:
        unique_all[str(m.get('id'))] = m
    other_date_matches = list(unique_all.values())
    
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
            d_today = datetime.date.today().strftime('%Y%m%d')
            if today_str == d_today:
                # 针对今天赛事，直接使用 alifInfo.js 一键解密，0.3 秒内获取 900+ 场全量赛事
                desktop_matches = scrape_desktop_matches(today_str)
                data = merge_date_matches(today_str, [], desktop_matches)
            else:
                # 针对历史/未来赛事，使用多线程 API 极速并发拉取
                new_matches = fetch_matches(today_str, n_values=[1, 2, 3, 4, 5, 7])
                data = merge_date_matches(today_str, new_matches, [])
        except Exception as e:
            if not data:
                err_str = str(e)
                if "IP_ACL_BLACKLIST" in err_str:
                    friendly_err = "当前您的出网 IP 已被雷速安全防护暂时拦截（Tengine IP ACL 黑名单），请更换网络或等待 5-10 分钟系统自愈解封"
                else:
                    friendly_err = f"Failed to fetch initial matches: {err_str}"
                return jsonify({'success': False, 'error': friendly_err})
                
    return jsonify({'success': True, 'data': data})

@app.route('/api/refresh')
def refresh_matches():
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.date.today().strftime('%Y%m%d')
        
    try:
        d_today = datetime.date.today().strftime('%Y%m%d')
        if date_str == d_today:
            # 针对今天实时比分刷新，直接一键解密 alifInfo.js，毫秒级响应
            desktop_matches = scrape_desktop_matches(date_str)
            updated_list = merge_date_matches(date_str, [], desktop_matches)
        else:
            # 针对历史/未来比分刷新，使用多线程并发 API 拉取
            new_matches = fetch_matches(date_str, n_values=[1, 2, 3, 4, 5, 7])
            updated_list = merge_date_matches(date_str, new_matches, [])
        return jsonify({'success': True, 'data': updated_list})
    except Exception as e:
        err_str = str(e)
        if "IP_ACL_BLACKLIST" in err_str:
            friendly_err = "当前您的出网 IP 已被雷速安全防护暂时拦截（Tengine IP ACL 黑名单），请更换网络或等待 5-10 分钟系统自愈解封"
        else:
            friendly_err = f"Refresh failed: {err_str}"
        return jsonify({'success': False, 'error': friendly_err})

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
    
    # 仅对已完场赛事使用和读取静态缓存
    cache_valid = False
    if os.path.exists(cache_file) and not force:
        if is_finished:
            cache_valid = True
                
    if cache_valid:
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({'success': True, 'data': data})
        except Exception as e:
            pass # fallback to scrape
            
    try:
        details = get_complete_match_details(match_id, home, away)
        # 仅在比赛确认为已结束时，才写入本地静态缓存
        if is_finished:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(details, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True, 'data': details})
    except Exception as e:
        err_str = str(e)
        if "IP_ACL_BLACKLIST" in err_str:
            friendly_err = "当前您的出网 IP 已被雷速安全防护暂时拦截（Tengine IP ACL 黑名单），请更换网络或等待 5-10 分钟系统自愈解封"
        else:
            friendly_err = f"Failed to fetch match details: {err_str}"
        return jsonify({'success': False, 'error': friendly_err})

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
    cache_valid = False
    
    if os.path.exists(cache_file):
        if is_finished:
            cache_valid = True
        else:
            # 对未完场或未开赛赛事，引入 120 秒临时缓存避免频繁点击引起 WAF 拦截与性能卡顿
            try:
                mtime = os.path.getmtime(cache_file)
                if time.time() - mtime < 120:
                    cache_valid = True
            except:
                pass
                
    if cache_valid:
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
            # 无论是否完场，拉取成功一律写入缓存文件，同时更新文件修改时间 (mtime)
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return jsonify({'success': True, 'data': data})
        else:
            return jsonify({'success': False, 'error': '暂无该公司的指数走势明细数据'})
    except Exception as e:
        err_str = str(e)
        if "IP_ACL_BLACKLIST" in err_str:
            friendly_error = "当前您的出网 IP 已被雷速安全防护暂时拦截（Tengine IP ACL 黑名单），请更换网络或等待 5-10 分钟系统自愈解封"
        else:
            friendly_error = f"系统请求异常: {err_str}"
        return jsonify({'success': False, 'error': friendly_error})
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

import threading
ai_tasks = {}

import concurrent.futures

def build_match_prompt_context(match_id, home, away):
    details_cache_file = os.path.join(CACHE_DIR, f'details_{match_id}.json')
    details = None
    if os.path.exists(details_cache_file):
        try:
            with open(details_cache_file, 'r', encoding='utf-8') as f:
                details = json.load(f)
        except Exception:
            pass
            
    if not details:
        try:
            details = get_complete_match_details(match_id, home, away)
        except Exception as e:
            return False, f"获取比赛详情数据失败: {str(e)}", ""

    similar_trend_data = {}
    win_probability_data = {}
    comp_name = ""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                all_matches = json.load(f)
            for m in all_matches:
                if str(m.get('id')) == str(match_id):
                    similar_trend_data = m.get('similar_trend', {})
                    win_probability_data = m.get('win_probability', {})
                    comp_name = m.get('competition', '')
                    break
        except Exception as e_db:
            print("Failed to load match meta from parsed_matches:", e_db)

    # 拼装 Prompt 上下文
    context_lines = []
    context_lines.append(f"【一、 比赛基本信息】")
    context_lines.append(f"- 赛事性质：{details.get('competition', '') or comp_name or '未知赛事'}")
    context_lines.append(f"- 对阵双方：主队 {home} vs 客队 {away}")
    
    context_lines.append(f"\n【二、 独家情报与基本面标签 (SWOT)】")
    swot = details.get('pros_cons', {})
    context_lines.append(f"主队有利/不利：")
    context_lines.append(f"主队有利情报：")
    for item in swot.get('home', {}).get('pros', []):
        context_lines.append(f"- {item}")
    context_lines.append(f"主队不利情报：")
    for item in swot.get('home', {}).get('cons', []):
        context_lines.append(f"- {item}")
    context_lines.append(f"\n客队有利/不利：")
    context_lines.append(f"客队有利情报：")
    for item in swot.get('away', {}).get('pros', []):
        context_lines.append(f"- {item}")
    context_lines.append(f"客队不利情报：")
    for item in swot.get('away', {}).get('cons', []):
        context_lines.append(f"- {item}")
        
    context_lines.append(f"\n【三、 伤停与阵容名单】")
    injuries = details.get('injuries', {})
    injuries_home = injuries.get('home', {}) if isinstance(injuries, dict) else {}
    injuries_away = injuries.get('away', {}) if isinstance(injuries, dict) else {}
    context_lines.append(f"主队伤停：")
    for p in injuries_home.get('injuries', []):
        context_lines.append(f"- 伤病: {p.get('name', '')} ({p.get('position', '')}) - 原因: {p.get('reason', '')} - 状态: {p.get('status', '')}")
    for p in injuries_home.get('suspensions', []):
        context_lines.append(f"- 停赛: {p.get('name', '')} ({p.get('position', '')}) - 原因: {p.get('reason', '')} - 状态: {p.get('status', '')}")
    if not injuries_home.get('injuries', []) and not injuries_home.get('suspensions', []):
        context_lines.append(f"- 暂无核心伤病与停赛")
    context_lines.append(f"客队伤停：")
    for p in injuries_away.get('injuries', []):
        context_lines.append(f"- 伤病: {p.get('name', '')} ({p.get('position', '')}) - 原因: {p.get('reason', '')} - 状态: {p.get('status', '')}")
    for p in injuries_away.get('suspensions', []):
        context_lines.append(f"- 停赛: {p.get('name', '')} ({p.get('position', '')}) - 原因: {p.get('reason', '')} - 状态: {p.get('status', '')}")
    if not injuries_away.get('injuries', []) and not injuries_away.get('suspensions', []):
        context_lines.append(f"- 暂无核心伤病与停赛")
        
    context_lines.append(f"\n【四、 历史交锋与两队近期战绩】")
    h2h_data = details.get('h2h', {})
    h2h_matches = h2h_data.get('matches', []) if isinstance(h2h_data, dict) else []
    context_lines.append(f"历史对决交锋：")
    for idx, match in enumerate(h2h_matches[:10]):
        context_lines.append(f"- {match.get('date', '')} {match.get('home', '')} {match.get('score', '')} {match.get('away', '')} (赛事: {match.get('competition', '')}, 结果: {match.get('result', '')})")
    if not h2h_matches:
        context_lines.append(f"- 暂无历史交锋数据")
        
    recent = details.get('recent_results', {})
    recent_home = recent.get('home', []) if isinstance(recent, dict) else []
    recent_away = recent.get('away', []) if isinstance(recent, dict) else []
    context_lines.append(f"主队近期战绩：")
    for idx, match in enumerate(recent_home[:10]):
        context_lines.append(f"- {match.get('date', '')} {match.get('home', '')} {match.get('score', '')} {match.get('away', '')} (赛事: {match.get('competition', '')}, 结果: {match.get('result', '')})")
    context_lines.append(f"客队近期战绩：")
    for idx, match in enumerate(recent_away[:10]):
        context_lines.append(f"- {match.get('date', '')} {match.get('home', '')} {match.get('score', '')} {match.get('away', '')} (赛事: {match.get('competition', '')}, 结果: {match.get('result', '')})")

    odds_index = details.get('odds_index', [])
    context_lines.append(f"\n【赔率指数初始与即时变盘水位数据】")
    for item in odds_index:
        company = item.get('company')
        eu = item.get('europe', {})
        init = eu.get('initial', [1.0, 1.0, 1.0])
        inst = eu.get('instant', [1.0, 1.0, 1.0])
        context_lines.append(f"- 公司: {company} | 初始赔率: 主胜 {init[0]} 平局 {init[1]} 客胜 {init[2]} | 即时赔率: 主胜 {inst[0]} 平局 {inst[1]} 客胜 {inst[2]}")
        
    for item in odds_index:
        company = item.get('company')
        h = item.get('handicap', {})
        init = h.get('initial', [1.0, 1.0])
        inst = h.get('instant', [1.0, 1.0])
        context_lines.append(f"- 公司: {company} | 初始盘口: {h.get('initial_line', '')} (主水 {init[0]} / 客水 {init[1]}) | 即时盘口: {h.get('instant_line', '')} (主水 {inst[0]} / 客水 {inst[1]})")
        
    for item in odds_index:
        company = item.get('company')
        ou = item.get('over_under', {})
        init = ou.get('initial', [1.0, 1.0])
        inst = ou.get('instant', [1.0, 1.0])
        context_lines.append(f"- 公司: {company} | 初始盘口: {ou.get('initial_line', '')} (大球水 {init[0]} / 小球水 {init[1]}) | 即时盘口: {ou.get('instant_line', '')} (大球水 {inst[0]} / 小球水 {inst[1]})")

    all_companies = [
        ("36*", "2"), ("皇*", "3"), ("立*", "5"), ("澳*", "7"),
        ("威***", "9"), ("易**", "10"), ("韦*", "11"), ("Inter*", "13"),
        ("12*", "14"), ("利*", "15"), ("盈*", "16"), ("18**", "17")
    ]
    for company_name, cid in all_companies:
        try:
            cached_trend = get_cached_odds_detail(match_id, cid)
            if cached_trend:
                all_tables = cached_trend
                if all_tables and len(all_tables) >= 3:
                    table_names = ["让球 (Handicap)", "胜平负 (1X2)", "大小球 (Over/Under)"]
                    for tbl_idx, rows in enumerate(all_tables[:3]):
                        t_name = table_names[tbl_idx]
                        context_lines.append(f"- {company_name} {t_name} 变盘路径 (按时间倒序，最近 10 次变盘):")
                        if not rows:
                            context_lines.append("  (暂无该项变盘明细)")
                            continue
                        for r in rows[:10]:
                            time_str = r.get('change_time', '')
                            if tbl_idx == 1:
                                context_lines.append(f"  * 时间: {time_str} | 主胜 {r.get('home')} | 平局 {r.get('draw')} | 客胜 {r.get('away')}")
                            else:
                                context_lines.append(f"  * 时间: {time_str} | 盘口 {r.get('line')} | 上/大 {r.get('home')} | 下/小 {r.get('away')}")
        except Exception:
            pass

    context_str = "\n".join(context_lines)
    return True, "", context_str

def run_single_version(version_idx, match_id, api_base, api_key, model_name, system_prompt, context_str):
    global ai_tasks
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = f"{api_base}/chat/completions"
    
    # 根据版本索引微调 temperature 以及提示语，确保三个版本具有不一样的推演切入点
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请针对以下赛事数据进行深度量化研判。请计算重点机构欧指的隐含概率变化，并通过基本面多维特征与临场盘水交叉审计，找出本场最具数学期望值（Value）的投资方向：\n\n(注意：这是第 {version_idx+1} 次研判，请提供独特的分析切入点与结论)\n\n{context_str}"}
        ],
        "temperature": 0.3 + (version_idx * 0.15),
        "stream": True
    }
    
    import requests
    r = requests.post(url, headers=headers, json=payload, timeout=90, stream=True)
    if r.status_code != 200:
        err_text = ""
        try:
            for line in r.iter_lines():
                if line:
                    err_text += line.decode('utf-8')
        except:
            pass
        raise Exception(f"大模型接口请求失败: HTTP {r.status_code} - {err_text or r.text}")
        
    ai_output = ""
    in_reasoning = False
    
    for line in r.iter_lines():
        if not line:
            continue
        line_str = line.decode('utf-8').strip()
        if line_str.startswith("data:"):
            data_content = line_str[5:].strip()
            if data_content == "[DONE]":
                break
            try:
                chunk = json.loads(data_content)
                delta = chunk['choices'][0]['delta']
                
                reasoning = delta.get('reasoning_content', '')
                content = delta.get('content', '')
                
                if reasoning:
                    if not in_reasoning:
                        ai_output += "<think>\n"
                        in_reasoning = True
                    ai_output += reasoning
                else:
                    if in_reasoning:
                        ai_output += "\n</think>\n"
                        in_reasoning = False
                    if content:
                        ai_output += content
                        
                ai_tasks[str(match_id)]['reports'][version_idx] = ai_output
            except Exception:
                pass
                
    if in_reasoning:
        ai_output += "\n</think>\n"
        ai_tasks[str(match_id)]['reports'][version_idx] = ai_output
        
    return ai_output

def run_cro_aggregation(match_id, api_base, api_key, model_name, combined_reports):
    global ai_tasks
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = f"{api_base}/chat/completions"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": CRO_SYSTEM_PROMPT},
            {"role": "user", "content": f"请立刻对以下3份报告进行风险敞口审计，并输出最终执行执行单：\n\n{combined_reports}"}
        ],
        "temperature": 0.1,
        "stream": False  # 使用非流式以确保稳定性
    }
    import requests
    r = requests.post(url, headers=headers, json=payload, timeout=90)
    if r.status_code != 200:
        raise Exception(f"收敛层大模型接口请求失败: HTTP {r.status_code} - {r.text}")
    
    res_data = r.json()
    message = res_data['choices'][0]['message']
    ai_output = message.get('content', '')
    return ai_output

def run_ai_analysis_thread(match_id, api_base, api_key, model_name, system_prompt, context_str, ai_cache_file):
    global ai_tasks
    try:
        ai_tasks[str(match_id)] = {
            'status': 'processing', 
            'reports': ['', '', ''],
            'status_list': ['processing', 'processing', 'processing'],
            'final_ticket': ''
        }
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(
                    run_single_version, 
                    i, match_id, api_base, api_key, model_name, system_prompt, context_str
                ): i for i in range(3)
            }
            
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    future.result()
                    ai_tasks[str(match_id)]['status_list'][idx] = 'completed'
                except Exception as sub_e:
                    print(f"Sub-thread {idx} failed for match {match_id}: {sub_e}")
                    ai_tasks[str(match_id)]['status_list'][idx] = 'failed'
                    ai_tasks[str(match_id)]['reports'][idx] = f"【该版本研判生成出错: {str(sub_e)}】"
        
        # 判断是否全都失败
        st_list = ai_tasks[str(match_id)]['status_list']
        if all(s == 'failed' for s in st_list):
            raise Exception("三个版本的 AI 研判全部请求失败。")
            
        # 并发执行完毕，开始构建聚合上下文
        reports_list = [ai_tasks[str(match_id)]['reports'][i] for i in range(3)]
        combined_reports = f"报告1:\n{reports_list[0]}\n\n报告2:\n{reports_list[1]}\n\n报告3:\n{reports_list[2]}"
        
        # 串行调用大模型进行收敛层聚合
        final_ticket = run_cro_aggregation(match_id, api_base, api_key, model_name, combined_reports)
        ai_tasks[str(match_id)]['final_ticket'] = final_ticket
        
        final_reports = ai_tasks[str(match_id)]['reports']
        with open(ai_cache_file, 'w', encoding='utf-8') as cache_f:
            json.dump({
                'reports': final_reports,
                'final_ticket': final_ticket
            }, cache_f, ensure_ascii=False, indent=2)
            
        ai_tasks[str(match_id)]['status'] = 'completed'
    except Exception as e:
        print(f"Background AI Thread error for match {match_id}: {e}")
        ai_tasks[str(match_id)] = {'status': 'failed', 'error': str(e)}

@app.route('/api/match_ai_analysis', methods=['POST'])
def match_ai_analysis():
    global ai_tasks
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': 'Missing request body'})
        
    match_id = str(data.get('match_id'))
    home = data.get('home_team')
    away = data.get('away_team')
    force = data.get('force') == True
    
    if not match_id or not home or not away:
        return jsonify({'success': False, 'error': 'Missing match details (id, home_team, away_team)'})
        
    # 1. 读取 AI 配置
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
            
    if not system_prompt:
        system_prompt = DEFAULT_SYSTEM_PROMPT
            
    if not api_key:
        return jsonify({'success': False, 'error': '请先在顶部“AI配置中心”中配置您的 API Key。'})
        
    ai_cache_file = os.path.join(CACHE_DIR, f'ai_analysis_{match_id}.json')
    
    # 2. 如果非强刷，优先命中缓存
    if not force:
        if os.path.exists(ai_cache_file):
            try:
                with open(ai_cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                if 'reports' in cache_data:
                    return jsonify({
                        'success': True, 
                        'status': 'completed', 
                        'cached': True, 
                        'reports': cache_data['reports'],
                        'final_ticket': cache_data.get('final_ticket', '')
                    })
                elif 'text' in cache_data:
                    return jsonify({
                        'success': True, 
                        'status': 'completed', 
                        'cached': True, 
                        'reports': [cache_data['text'], '', ''],
                        'final_ticket': ''
                    })
            except Exception:
                pass
        return jsonify({
            'success': True, 
            'status': 'idle', 
            'cached': False, 
            'reports': ['', '', ''],
            'final_ticket': ''
        })

    # 3. 检查是否有任务正在跑
    task = ai_tasks.get(match_id)
    if task and task['status'] == 'processing':
        return jsonify({'success': True, 'status': 'processing', 'message': '该比赛的 AI 预测报告正在后台异步生成中，请耐心等候...'})
        
    # 清理历史缓存以重新生成
    if os.path.exists(ai_cache_file):
        try:
            os.remove(ai_cache_file)
        except:
            pass
            
    # 4. 获取最新的详情和盘口并构建上下文
    success, err_msg, context_str = build_match_prompt_context(match_id, home, away)
    if not success:
        return jsonify({'success': False, 'error': err_msg})
        
    # 5. 后台拉起独立线程并发请求三个版本的 AI
    ai_tasks[match_id] = {
        'status': 'processing', 
        'reports': ['', '', ''],
        'status_list': ['processing', 'processing', 'processing'],
        'final_ticket': ''
    }
    t = threading.Thread(
        target=run_ai_analysis_thread,
        args=(match_id, api_base, api_key, model_name, system_prompt, context_str, ai_cache_file)
    )
    t.daemon = True
    t.start()
    
    return jsonify({
        'success': True,
        'status': 'processing',
        'message': 'AI后台异步托管成功！三版本分析正在云端并发进行中。'
    })

@app.route('/api/ai_analysis_status', methods=['GET'])
def ai_analysis_status():
    global ai_tasks
    match_id = request.args.get('match_id')
    if not match_id:
        return jsonify({'success': False, 'error': 'Missing match_id'})
        
    ai_cache_file = os.path.join(CACHE_DIR, f'ai_analysis_{match_id}.json')
    
    # 优先检测有无物理缓存生成
    if os.path.exists(ai_cache_file):
        try:
            with open(ai_cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            if 'reports' in cache_data:
                return jsonify({
                    'success': True, 
                    'status': 'completed', 
                    'reports': cache_data['reports'],
                    'final_ticket': cache_data.get('final_ticket', ''),
                    'status_list': ['completed', 'completed', 'completed']
                })
            elif 'text' in cache_data:
                # 兼容老版本单个文本缓存
                return jsonify({
                    'success': True,
                    'status': 'completed',
                    'reports': [cache_data['text'], '', ''],
                    'final_ticket': '',
                    'status_list': ['completed', 'completed', 'completed']
                })
        except Exception:
            pass
            
    task = ai_tasks.get(str(match_id))
    if task:
        if task['status'] == 'failed':
            return jsonify({'success': True, 'status': 'failed', 'error': task.get('error', '未知大模型异常')})
        return jsonify({
            'success': True, 
            'status': task['status'], 
            'reports': task.get('reports', ['', '', '']),
            'final_ticket': task.get('final_ticket', ''),
            'status_list': task.get('status_list', ['processing', 'processing', 'processing'])
        })
        
    return jsonify({'success': True, 'status': 'idle'})



@app.route('/api/debug_find_kst')
def debug_find_kst():
    import re
    from detail_scraper import fetch_html_with_bypass, GLOBAL_ODDS_OPENER, GLOBAL_ODDS_CJ, HEADERS
    url_target = "https://odds.leisu.com/trend-4459808-2"
    headers = HEADERS.copy()
    headers['Origin'] = 'https://odds.leisu.com'
    headers['Referer'] = 'https://odds.leisu.com/'
    try:
        html = fetch_html_with_bypass(url_target, 'odds.leisu.com', GLOBAL_ODDS_OPENER, GLOBAL_ODDS_CJ, headers=headers)
        
        # 匹配 17835 开头的 10 位数字，但我们要过滤掉 td 节点的干扰
        num_matches = re.finditer(r'\b(17835\d{5})\b', html)
        previews = []
        for m in num_matches:
            idx = m.start()
            val = m.group(1)
            context_str = html[max(0, idx-60): min(len(html), idx+60)]
            # 过滤掉 key="17835..." 这种明细 td 属性
            if 'key=' in context_str or 'class=' in context_str:
                continue
            previews.append(f"Val={val} Context: " + context_str.strip().replace('\n', ' '))
                
        return jsonify({
            'success': True,
            'html_length': len(html),
            'filtered_count': len(previews),
            'previews': previews
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/debug_cmd')
def debug_cmd():
    cmd = request.args.get('cmd')
    if not cmd:
        return "Missing cmd"
    try:
        import subprocess
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        return jsonify({
            'returncode': res.returncode,
            'stdout': res.stdout,
            'stderr': res.stderr
        })
    except Exception as e:
        return str(e)

@app.route('/api/odds_debug')
def get_odds_debug_log():
    from detail_scraper import ODDS_DEBUG_LOG
    return jsonify({
        'success': True,
        'logs': ODDS_DEBUG_LOG
    })

if __name__ == '__main__':
    # Run locally or on server port 5000, listening on all interfaces
    app.run(host='0.0.0.0', port=5000)
