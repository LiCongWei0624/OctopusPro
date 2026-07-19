# -*- coding: utf-8 -*-
from flask import Flask, jsonify, render_template, request, send_from_directory
import json
import os
import datetime
import re
import tempfile
import threading
import time
import uuid
from leisu_crawler import fetch_matches
from detail_scraper import get_complete_match_details, get_odds_detail_via_playwright, get_real_odds
from scraper import scrape_desktop_matches
from prediction_tracker import init_database, prediction_detail, record_prediction, settle_finished_predictions, summary as prediction_summary

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

DATA_FILE = os.path.join(os.path.dirname(__file__), 'parsed_matches.json')
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
AI_ANALYSIS_CACHE_VERSION = 3
MAX_BATCH_ANALYSIS_SIZE = 6
BATCH_CONCURRENT_MATCHES = 6
PREMATCH_STATUSES = {1, 13}
LIVE_STATUSES = {2, 3, 4, 5, 7, 10}
ANALYSIS_STATUSES = PREMATCH_STATUSES | LIVE_STATUSES
TERMINAL_STATUSES = {8, 9, 11, 12}
PREDICTION_DB_FILE = os.path.join(os.path.dirname(__file__), 'prediction_history.sqlite3')
BATCH_STATE_FILE = os.path.join(CACHE_DIR, 'latest_batch_ai_state.json')
LIVE_DETAILS_CACHE_TTL_SECONDS = 90

# The browser can issue overlapping refreshes. Keep the shared fixture file
# coherent and avoid repeatedly decoding several megabytes for every request.
_match_store_lock = threading.RLock()
_match_store_cache = {'mtime_ns': None, 'matches': [], 'by_id': {}}
_refresh_lock = threading.Lock()
_refresh_scheduler_started = False

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
- **【最佳价值切入】**：[具体临场盘口与方向] | **预期回报形态**：[严格遵循标准让球盘清算规则] | **风控逻辑**：[基于资金动能或防守价值的理由]

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
- **首席CRO聚合逻辑**：[解释其对主单的保护对冲逻辑，或者因降档收敛而保留的独立高期望值逻辑]

#### 三、 📉 资金分配与风险边际铁律
- **单场总头寸控制**：本次策略总计消耗 [X] 个标准单位（单场最高绝不超过 1.5 个单位）。
- **执行纪律提示**：[明确风控线，严格遵守仓位纪律]"""

PREDICTION_POLICY = """这是足球预测链路。输入会明确标记为“赛前分析”或“滚球分析”，必须严格按该模式判断：
1. 赛前分析不得使用走地赔率、已结束比分或赛后数据；滚球分析可以使用输入中的当前比分与走地盘口，但不得把它们表述为赛前证据。
2. 盘口高水、未跟盘或机构间差异只能作为不确定性证据，绝不能自动反向推荐受让方或小球；必须同时列出支持与反对该方向的实际数据。
3. 情报、伤停、交锋或赔率缺失时，明确标记缺失并降低置信度，但仍按产品要求给出方向。
4. 不得编造资金流、庄家意图、EV 百分比、xG 或历史统计。让球和大小球必须使用输入中存在的具体盘口。"""

ANALYST_OUTPUT_LIMIT = """输出应是可执行的分析摘要，而非逐项复述原始数据：
1. 只保留影响结论的证据、反方证据、三个市场结论和风险条件；避免重复解释相同盘口。
2. 使用简洁的 Markdown，全文不超过 1,200 个汉字或等量内容。
3. 不得输出思维链、内部推演过程或与结论无关的泛泛说明。"""

TRACKING_OUTPUT_CONTRACT = """报告最后必须附上唯一一个 JSON 代码块，供赛后自动结算，格式严格如下：
```json
{"prediction_record":{"one_x_two":"home|draw|away","asian_handicap":{"team":"home|away","line":-0.25},"over_under":{"side":"over|under","line":2.5},"confidence":"high|medium|low"}}
```
让球 `line` 是推荐球队获得的让球值：主队让 0.25 写 team=home、line=-0.25；客队受让 0.25 写 team=away、line=0.25。只能填入输入中存在的盘口。"""

if not os.path.exists(CACHE_DIR):
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
init_database(PREDICTION_DB_FILE)


def load_match_store():
    if not os.path.exists(DATA_FILE):
        return [], {}

    try:
        mtime_ns = os.stat(DATA_FILE).st_mtime_ns
    except OSError:
        return [], {}

    with _match_store_lock:
        if _match_store_cache['mtime_ns'] == mtime_ns:
            return _match_store_cache['matches'], _match_store_cache['by_id']
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                matches = json.load(f)
            if not isinstance(matches, list):
                raise ValueError('parsed_matches.json must contain a list')
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f'Failed to load match store: {exc}')
            return [], {}

        _match_store_cache.update({
            'mtime_ns': mtime_ns,
            'matches': matches,
            'by_id': {str(match.get('id')): match for match in matches},
        })
        return _match_store_cache['matches'], _match_store_cache['by_id']


def save_match_store(matches):
    directory = os.path.dirname(DATA_FILE)
    with _match_store_lock:
        fd, temp_path = tempfile.mkstemp(prefix='parsed_matches_', suffix='.json', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(matches, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, DATA_FILE)
            mtime_ns = os.stat(DATA_FILE).st_mtime_ns
            _match_store_cache.update({
                'mtime_ns': mtime_ns,
                'matches': matches,
                'by_id': {str(match.get('id')): match for match in matches},
            })
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

def get_weekday_cn(date_obj):
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return weekdays[date_obj.weekday()]


def _normalise_status(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _merged_status(previous, incoming):
    """Keep a confirmed terminal score from regressing during a stale refresh."""
    old_status = _normalise_status(previous)
    new_status = _normalise_status(incoming)
    if old_status in TERMINAL_STATUSES and new_status not in TERMINAL_STATUSES:
        return old_status
    return new_status

def merge_date_matches(date_str, mobile_matches, desktop_matches):
    d = datetime.datetime.strptime(date_str, "%Y%m%d").date()
    target_date_formatted = f"{d.strftime('%m-%d')} {get_weekday_cn(d)}"
    
    existing_matches, _ = load_match_store()
            
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
            item['status'] = _merged_status(item.get('status'), m.get('status', 1))
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
            existing_item['status'] = _merged_status(existing_item.get('status'), dm_status)
                
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
                item['status'] = _merged_status(item.get('status'), dm.get('status', 1))
                
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
        
    save_match_store(other_date_matches)
        
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
            # The browser only needs the configuration shape.  Returning the
            # stored provider key to any unauthenticated visitor exposed it.
            safe_config = config.copy()
            safe_config['api_key'] = ''
            return jsonify({'success': True, 'data': safe_config})
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
    
    existing_key = ''
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                existing_key = json.load(f).get('api_key', '')
        except Exception:
            pass

    config = {
        # A blank field means “keep the server-side key”, so editing only the
        # prompt/model in the UI cannot erase it after GET redaction.
        'api_key': data.get('api_key', '').strip() or existing_key,
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


def refresh_match_data(date_str):
    """Refresh one fixture date while serialising crawler and file updates."""
    with _refresh_lock:
        today_str = datetime.date.today().strftime('%Y%m%d')
        if date_str == today_str:
            desktop_matches = scrape_desktop_matches(date_str)
            return merge_date_matches(date_str, [], desktop_matches)
        new_matches = fetch_matches(date_str, n_values=[1, 2, 3, 4, 5, 7])
        return merge_date_matches(date_str, new_matches, [])


def _scheduled_today_refresh():
    while True:
        time.sleep(10 * 60)
        try:
            today_str = datetime.date.today().strftime('%Y%m%d')
            refreshed = refresh_match_data(today_str)
            print(f'Automatic fixture refresh completed: {len(refreshed)} matches for {today_str}')
        except Exception as exc:
            print(f'Automatic fixture refresh failed: {exc}')


def start_refresh_scheduler():
    global _refresh_scheduler_started
    if _refresh_scheduler_started:
        return
    _refresh_scheduler_started = True
    threading.Thread(target=_scheduled_today_refresh, name='fixture-refresh', daemon=True).start()


@app.route('/api/matches')
def get_matches():
    today_str = request.args.get('today')
    if not today_str:
        today_str = datetime.date.today().strftime('%Y%m%d')
        
    has_today = False
    data, _ = load_match_store()
    if data:
        try:
            d = datetime.datetime.strptime(today_str, "%Y%m%d").date()
            target_date_formatted = f"{d.strftime('%m-%d')} {get_weekday_cn(d)}"
            for m in data:
                if m.get('date') == target_date_formatted:
                    has_today = True
                    break
        except (TypeError, ValueError):
            pass
            
    if not has_today:
        try:
            data = refresh_match_data(today_str)
        except Exception as e:
            if not data:
                err_str = str(e)
                if "IP_ACL_BLACKLIST" in err_str:
                    friendly_err = "当前您的出网 IP 已被雷速安全防护暂时拦截（Tengine IP ACL 黑名单），请更换网络或等待 5-10 分钟系统自愈解封"
                else:
                    friendly_err = f"Failed to fetch initial matches: {err_str}"
                return jsonify({'success': False, 'error': friendly_err})

    # parsed_matches.json holds several dates.  Returning the full file here
    # made every date tab contain historical finished fixtures.
    try:
        d = datetime.datetime.strptime(today_str, "%Y%m%d").date()
        target_date_formatted = f"{d.strftime('%m-%d')} {get_weekday_cn(d)}"
        data = [m for m in data if m.get('date') == target_date_formatted]
    except Exception:
        pass
                
    return jsonify({'success': True, 'data': data})

@app.route('/api/refresh')
def refresh_matches():
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.date.today().strftime('%Y%m%d')
        
    try:
        updated_list = refresh_match_data(date_str)
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
    _, matches_by_id = load_match_store()
    match_meta = matches_by_id.get(str(match_id))
    if match_meta:
        try:
            is_finished = int(match_meta.get('status', 1)) in TERMINAL_STATUSES
        except (TypeError, ValueError):
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
        else:
            try:
                cache_valid = time.time() - os.path.getmtime(cache_file) < LIVE_DETAILS_CACHE_TTL_SECONDS
            except OSError:
                pass
                
    if cache_valid:
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not data.get('odds_index'):
                # A finished-match snapshot is otherwise permanent. Do not
                # preserve an incomplete odds response from a transient WAF
                # or upstream failure; refetch it when the fixture is opened.
                data = None
            if data is not None:
                return jsonify({'success': True, 'data': data})
        except Exception as e:
            pass # fallback to scrape
            
    try:
        details = get_complete_match_details(match_id, home, away)
        # A detail scrape can occasionally finish with an empty odds payload
        # after a transient WAF/upstream response. Retry only that isolated
        # endpoint before caching so an incomplete snapshot is never served as
        # a successful detail result.
        if not details.get('odds_index'):
            details['odds_index'] = get_real_odds(match_id)
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
    _, matches_by_id = load_match_store()
    match_meta = matches_by_id.get(str(match_id))
    if match_meta:
        is_finished = str(match_meta.get('status')) == '8'
            
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


def has_final_output(text):
    """A completed reasoning stream must contain content after its <think> block."""
    if not isinstance(text, str):
        return False
    stripped = text.lstrip()
    if not stripped.startswith('<think>'):
        return bool(stripped)
    closing_index = stripped.rfind('</think>')
    visible = stripped[closing_index + len('</think>'):].strip() if closing_index >= 0 else ''
    return bool(visible)


def extract_final_output(text):
    """Return only the report body; reasoning is retained for the UI, not re-sent to CRO."""
    if not isinstance(text, str):
        return ''
    stripped = text.lstrip()
    if not stripped.startswith('<think>'):
        return stripped
    closing_index = stripped.rfind('</think>')
    return stripped[closing_index + len('</think>'):].strip() if closing_index >= 0 else ''


def is_complete_analysis_cache(cache_data):
    reports = cache_data.get('reports') if isinstance(cache_data, dict) else None
    return (
        isinstance(reports, list)
        and len(reports) == 3
        and all(has_final_output(report) for report in reports)
        and has_final_output(cache_data.get('final_ticket', ''))
    )

ai_tasks = {}
batch_ai_tasks = {}
_batch_ai_tasks_lock = threading.RLock()

import concurrent.futures


def _persist_latest_batch_state(batch_id):
    """Persist the latest batch so a browser refresh can restore its progress view."""
    with _batch_ai_tasks_lock:
        batch = batch_ai_tasks.get(batch_id)
        if not batch:
            return
        payload = {'id': batch_id, 'batch': batch}
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix='batch_ai_', suffix='.json', dir=CACHE_DIR)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, BATCH_STATE_FILE)
    except Exception as error:
        print(f'Failed to persist batch state: {error}')
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def _restore_latest_batch_state():
    """Restore the last viewable batch; interrupted workers are safely marked failed."""
    if not os.path.exists(BATCH_STATE_FILE):
        return
    try:
        with open(BATCH_STATE_FILE, 'r', encoding='utf-8') as f:
            stored = json.load(f)
        batch_id = str(stored.get('id', '')).strip()
        batch = stored.get('batch')
        if not batch_id or not isinstance(batch, dict) or not isinstance(batch.get('items'), list):
            return
        for item in batch['items']:
            if item.get('status') in {'queued', 'preparing', 'processing'}:
                item['status'] = 'failed'
                item['error'] = '服务重启导致任务中断，可仅重试该场。'
        if batch.get('status') == 'processing':
            batch['status'] = 'completed'
        batch_ai_tasks[batch_id] = batch
    except Exception as error:
        print(f'Failed to restore batch state: {error}')


def _load_ai_runtime_config():
    """Load the shared model settings used by both single and batch analysis."""
    api_key = ""
    api_base = "https://opencode.ai/zen/v1"
    model_name = "minimax-m2.5-free"
    system_prompt = ""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            api_key = cfg.get('api_key', '')
            api_base = cfg.get('api_base', api_base)
            model_name = cfg.get('model_name', model_name)
            system_prompt = cfg.get('system_prompt', '')
        except Exception:
            pass

    if not system_prompt:
        system_prompt = DEFAULT_SYSTEM_PROMPT
    if not api_key:
        return False, '请先在顶部“AI配置中心”中配置您的 API Key。', None
    return True, '', {
        'api_key': api_key,
        'api_base': api_base.rstrip('/'),
        'model_name': model_name,
        'system_prompt': system_prompt,
    }


def _has_reusable_prematch_cache(match_id):
    """Only completed, current-version pre-match reports may be reused in a batch."""
    ai_cache_file = os.path.join(CACHE_DIR, f'ai_analysis_{match_id}.json')
    if not os.path.exists(ai_cache_file):
        return False
    try:
        with open(ai_cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        return (
            cache_data.get('analysis_version') == AI_ANALYSIS_CACHE_VERSION
            and cache_data.get('analysis_mode') == 'prematch'
            and is_complete_analysis_cache(cache_data)
        )
    except Exception:
        return False


def _batch_snapshot(batch_id):
    """Return a compact, browser-safe progress view without exposing report bodies."""
    with _batch_ai_tasks_lock:
        batch = batch_ai_tasks.get(batch_id)
        if not batch:
            return None
        items = [dict(item) for item in batch['items']]
        for item in items:
            status = item['status']
            if status == 'queued':
                item['phase'] = '等待数据准备'
            elif status == 'preparing':
                item['phase'] = '整理情报、伤停、阵容、战绩与盘口'
            elif status == 'processing':
                task = ai_tasks.get(item['match_id'], {})
                if task.get('status') == 'failed':
                    item['phase'] = 'AI 分析失败'
                    item['error'] = task.get('error', item.get('error', '未知错误'))
                else:
                    status_list = task.get('status_list', [])
                    completed_versions = sum(value == 'completed' for value in status_list)
                    failed_versions = sum(value == 'failed' for value in status_list)
                    if completed_versions == 3:
                        item['phase'] = 'CRO 正在汇总最终执行单'
                    elif failed_versions:
                        item['phase'] = f'AI 三路研判中（完成 {completed_versions}/3，失败 {failed_versions}）'
                    else:
                        item['phase'] = f'AI 三路研判中（完成 {completed_versions}/3）'
            elif status == 'completed':
                item['phase'] = '分析完成'
            elif status == 'cached':
                item['phase'] = '已复用赛前报告缓存'
            elif status == 'skipped':
                item['phase'] = '已跳过'
            elif status == 'failed':
                item['phase'] = '分析失败'
        counts = {
            'total': len(items),
            'completed': sum(item['status'] in {'completed', 'cached'} for item in items),
            'failed': sum(item['status'] == 'failed' for item in items),
            'processing': sum(item['status'] in {'preparing', 'queued', 'processing'} for item in items),
            'cached': sum(item['status'] == 'cached' for item in items),
            'skipped': sum(item['status'] == 'skipped' for item in items),
        }
        return {
            'id': batch_id,
            'status': batch['status'],
            'counts': counts,
            'items': items,
        }


def _run_batch_ai_analysis(batch_id, runtime_config):
    """Prepare details serially and run each selected match independently.

    Detail scraping keeps shared anti-bot state, so it deliberately stays on this
    coordinator thread. Once prepared, up to six matches run concurrently; each
    retains its own prompt context, task key, and match-specific cache file.
    """
    try:
        with _batch_ai_tasks_lock:
            items = batch_ai_tasks[batch_id]['items']
        pending = [item for item in items if item['status'] == 'queued']
        active = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=BATCH_CONCURRENT_MATCHES) as executor:
            while pending or active:
                while pending and len(active) < BATCH_CONCURRENT_MATCHES:
                    item = pending.pop(0)
                    with _batch_ai_tasks_lock:
                        item['status'] = 'preparing'

                    success, error, context_str = build_match_prompt_context(
                        item['match_id'], item['home_team'], item['away_team'], item['analysis_mode']
                    )
                    if not success:
                        with _batch_ai_tasks_lock:
                            item['status'] = 'failed'
                            item['error'] = error
                        continue

                    ai_cache_file = os.path.join(CACHE_DIR, f"ai_analysis_{item['match_id']}.json")
                    if os.path.exists(ai_cache_file):
                        try:
                            os.remove(ai_cache_file)
                        except OSError:
                            pass

                    prediction_metadata = {
                        'match_id': item['match_id'],
                        'home_team': item['home_team'],
                        'away_team': item['away_team'],
                        'kickoff': item['kickoff'],
                        'competition': item['competition'],
                        'fixture_date': item['fixture_date'],
                        'fixture_status': item['fixture_status'],
                        'analysis_mode': item['analysis_mode'],
                    }
                    with _batch_ai_tasks_lock:
                        item['status'] = 'processing'
                    future = executor.submit(
                        run_ai_analysis_thread,
                        item['match_id'], runtime_config['api_base'], runtime_config['api_key'],
                        runtime_config['model_name'], runtime_config['system_prompt'], context_str,
                        ai_cache_file, prediction_metadata, item['analysis_mode'],
                    )
                    active[future] = item

                if not active:
                    continue
                done, _ = concurrent.futures.wait(
                    active, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in done:
                    item = active.pop(future)
                    try:
                        future.result()
                    except Exception as error:
                        task = {'status': 'failed', 'error': str(error)}
                    else:
                        task = ai_tasks.get(item['match_id'], {})
                    with _batch_ai_tasks_lock:
                        if task.get('status') == 'completed':
                            item['status'] = 'completed'
                        else:
                            item['status'] = 'failed'
                            item['error'] = task.get('error', 'AI 分析未完成，请单独重试。')

        with _batch_ai_tasks_lock:
            batch_ai_tasks[batch_id]['status'] = 'completed'
        _persist_latest_batch_state(batch_id)
    except Exception as error:
        print(f"Batch AI analysis error for batch {batch_id}: {error}")
        with _batch_ai_tasks_lock:
            batch = batch_ai_tasks.get(batch_id)
            if batch:
                batch['status'] = 'failed'
        _persist_latest_batch_state(batch_id)


@app.route('/api/batch_ai_analysis', methods=['POST'])
def batch_ai_analysis():
    data = request.get_json(silent=True) or {}
    requested_matches = data.get('matches')
    if not isinstance(requested_matches, list) or not requested_matches:
        return jsonify({'success': False, 'error': '请先选择至少一场赛事。'})

    requested_ids = []
    for match in requested_matches:
        match_id = str(match.get('id', '') if isinstance(match, dict) else match).strip()
        if match_id and match_id not in requested_ids:
            requested_ids.append(match_id)
    if not requested_ids:
        return jsonify({'success': False, 'error': '未找到有效赛事。'})
    if len(requested_ids) > MAX_BATCH_ANALYSIS_SIZE:
        return jsonify({'success': False, 'error': f'单次最多批量分析 {MAX_BATCH_ANALYSIS_SIZE} 场，请先缩小筛选范围。'})
    ok, error, runtime_config = _load_ai_runtime_config()
    if not ok:
        return jsonify({'success': False, 'error': error})

    _, matches_by_id = load_match_store()
    items = []
    for match_id in requested_ids:
        fixture = matches_by_id.get(match_id)
        if not fixture:
            continue
        try:
            fixture_status = int(fixture.get('status', 1))
        except (TypeError, ValueError):
            fixture_status = None
        if fixture_status not in ANALYSIS_STATUSES:
            continue

        mode = 'live' if fixture_status in LIVE_STATUSES else 'prematch'
        item = {
            'match_id': match_id,
            'home_team': fixture.get('home_team', ''),
            'away_team': fixture.get('away_team', ''),
            'competition': fixture.get('competition', ''),
            'kickoff': f"{fixture.get('date', '')} {fixture.get('time', '')}".strip(),
            'fixture_date': fixture.get('date', ''),
            'fixture_status': fixture_status,
            'analysis_mode': mode,
            'status': 'queued',
        }
        existing_task = ai_tasks.get(match_id)
        if existing_task and existing_task.get('status') == 'processing':
            item['status'] = 'skipped'
            item['error'] = '该赛事已有分析任务在运行。'
        elif mode == 'prematch' and _has_reusable_prematch_cache(match_id):
            item['status'] = 'cached'
        items.append(item)

    if not items:
        return jsonify({'success': False, 'error': '当前筛选中没有可分析的未开赛或进行中赛事。'})

    batch_id = f"batch-{uuid.uuid4().hex}"
    with _batch_ai_tasks_lock:
        batch_ai_tasks[batch_id] = {
            'status': 'processing',
            'created_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'items': items,
        }
    _persist_latest_batch_state(batch_id)

    if any(item['status'] == 'queued' for item in items):
        worker = threading.Thread(
            target=_run_batch_ai_analysis,
            args=(batch_id, runtime_config),
            daemon=True,
        )
        worker.start()
    else:
        with _batch_ai_tasks_lock:
            batch_ai_tasks[batch_id]['status'] = 'completed'

    return jsonify({'success': True, 'batch_id': batch_id, 'batch': _batch_snapshot(batch_id)})


@app.route('/api/batch_ai_analysis_status')
def batch_ai_analysis_status():
    batch_id = request.args.get('batch_id', '').strip()
    batch = _batch_snapshot(batch_id)
    if not batch:
        return jsonify({'success': False, 'error': '批量任务不存在或已过期。'})
    return jsonify({'success': True, 'batch': batch})


@app.route('/api/batch_ai_analysis_latest')
def batch_ai_analysis_latest():
    with _batch_ai_tasks_lock:
        if not batch_ai_tasks:
            return jsonify({'success': True, 'batch': None})
        batch_id = max(batch_ai_tasks, key=lambda key: batch_ai_tasks[key].get('created_at', ''))
    return jsonify({'success': True, 'batch': _batch_snapshot(batch_id)})


_restore_latest_batch_state()


@app.route('/api/batch_ai_analysis_result')
def batch_ai_analysis_result():
    """Return only one completed match's CRO execution ticket for batch quick view."""
    batch_id = request.args.get('batch_id', '').strip()
    match_id = request.args.get('match_id', '').strip()
    if not batch_id or not match_id:
        return jsonify({'success': False, 'error': '缺少批量任务或比赛标识。'}), 400

    with _batch_ai_tasks_lock:
        batch = batch_ai_tasks.get(batch_id)
        item = next((row for row in batch['items'] if row['match_id'] == match_id), None) if batch else None
        if not item:
            return jsonify({'success': False, 'error': '该比赛不属于当前批量任务。'}), 404
        item_data = dict(item)

    if item_data['status'] not in {'completed', 'cached'}:
        return jsonify({'success': False, 'error': '该比赛的最终执行单尚未生成。'}), 409

    ai_cache_file = os.path.join(CACHE_DIR, f'ai_analysis_{match_id}.json')
    try:
        with open(ai_cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        if not is_complete_analysis_cache(cache_data):
            raise ValueError('报告缓存不完整')
        return jsonify({
            'success': True,
            'match': {
                'match_id': match_id,
                'home_team': item_data.get('home_team', ''),
                'away_team': item_data.get('away_team', ''),
            },
            'final_ticket': extract_final_output(cache_data.get('final_ticket', '')),
        })
    except Exception as error:
        return jsonify({'success': False, 'error': f'读取最终执行单失败：{str(error)}'}), 500


def build_match_prompt_context(match_id, home, away, analysis_mode='prematch'):
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
    match_meta = {}
    _, matches_by_id = load_match_store()
    match_meta = matches_by_id.get(str(match_id), {})
    if match_meta:
        similar_trend_data = match_meta.get('similar_trend', {})
        win_probability_data = match_meta.get('win_probability', {})
        comp_name = match_meta.get('competition', '')

    # 拼装 Prompt 上下文
    context_lines = []
    context_lines.append(f"【一、 比赛基本信息】")
    context_lines.append(f"- 赛事性质：{details.get('competition', '') or comp_name or '未知赛事'}")
    context_lines.append(f"- 对阵双方：主队 {home} vs 客队 {away}")
    if match_meta:
        if analysis_mode == 'live':
            context_lines.append(f"- 分析模式：滚球分析 | 当前比分：{match_meta.get('score', '') or '待同步'} | 比赛状态：{match_meta.get('status', '')}")
            context_lines.append("- 盘口口径：允许使用当前走地盘口；结论仅适用于当前时点，下一次变盘后应重新生成。")
        else:
            context_lines.append(f"- 分析模式：赛前分析 | 开赛时间：{match_meta.get('date', '')} {match_meta.get('time', '')}")
            context_lines.append("- 盘口口径：仅使用赛前即时盘口，不使用走地赔率。")
    
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
            {"role": "system", "content": PREDICTION_POLICY},
            {"role": "system", "content": ANALYST_OUTPUT_LIMIT},
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
            {"role": "system", "content": PREDICTION_POLICY},
            {"role": "system", "content": TRACKING_OUTPUT_CONTRACT},
            {"role": "system", "content": "最终执行单只保留共识、两项以内的建议、风险条件和 prediction_record；全文不超过 800 个汉字或等量内容。"},
            {"role": "user", "content": f"请立刻对以下3份报告进行风险敞口审计，并输出最终执行执行单：\n\n{combined_reports}"}
        ],
        "temperature": 0.1,
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
        raise Exception(f"收敛层大模型接口请求失败: HTTP {r.status_code} - {err_text or r.text}")
        
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
                        
                ai_tasks[str(match_id)]['final_ticket'] = ai_output
            except Exception:
                pass
                
    if in_reasoning:
        ai_output += "\n</think>\n"
        ai_tasks[str(match_id)]['final_ticket'] = ai_output
        
    return ai_output

def run_ai_analysis_thread(match_id, api_base, api_key, model_name, system_prompt, context_str, ai_cache_file, prediction_metadata, analysis_mode):
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
            sub_errors = []
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    future.result()
                    ai_tasks[str(match_id)]['status_list'][idx] = 'completed'
                except Exception as sub_e:
                    print(f"Sub-thread {idx} failed for match {match_id}: {sub_e}")
                    sub_errors.append(str(sub_e))
                    ai_tasks[str(match_id)]['status_list'][idx] = 'failed'
                    ai_tasks[str(match_id)]['reports'][idx] = f"【该版本研判生成出错: {str(sub_e)}】"
        
        # 判断是否全都失败
        st_list = ai_tasks[str(match_id)]['status_list']
        if all(s == 'failed' for s in st_list):
            detail = sub_errors[0] if sub_errors else '未返回可用错误信息'
            raise Exception(f"三个版本的 AI 研判全部请求失败：{detail}")

        incomplete_reports = [idx + 1 for idx, report in enumerate(ai_tasks[str(match_id)]['reports']) if not has_final_output(report)]
        if incomplete_reports:
            raise Exception(f"第 {', '.join(map(str, incomplete_reports))} 份研判只返回了思考过程，未生成正文。请重新生成。")
            
        # 并发执行完毕，开始构建聚合上下文
        # The CRO judges each analyst's conclusion, not its raw reasoning trace.
        # Keeping traces out of this prompt cuts a large redundant model input while
        # preserving them unchanged in the UI and analysis cache.
        reports_list = [extract_final_output(ai_tasks[str(match_id)]['reports'][i]) for i in range(3)]
        combined_reports = f"报告1:\n{reports_list[0]}\n\n报告2:\n{reports_list[1]}\n\n报告3:\n{reports_list[2]}"
        
        # 串行调用大模型进行收敛层聚合
        final_ticket = run_cro_aggregation(match_id, api_base, api_key, model_name, combined_reports)
        if not has_final_output(final_ticket):
            raise Exception("CRO 只返回了思考过程，未生成最终执行单。请重新生成。")
        ai_tasks[str(match_id)]['final_ticket'] = final_ticket
        
        final_reports = ai_tasks[str(match_id)]['reports']
        with open(ai_cache_file, 'w', encoding='utf-8') as cache_f:
            json.dump({
                'analysis_version': AI_ANALYSIS_CACHE_VERSION,
                'analysis_mode': analysis_mode,
                'reports': final_reports,
                'final_ticket': final_ticket
            }, cache_f, ensure_ascii=False, indent=2)

        try:
            record_prediction(
                PREDICTION_DB_FILE, prediction_metadata, model_name,
                system_prompt + '\n' + PREDICTION_POLICY + '\n' + TRACKING_OUTPUT_CONTRACT,
                context_str, final_ticket,
            )
        except Exception as tracking_error:
            # Tracking must never invalidate a completed user-facing analysis.
            print(f"Prediction tracking failed for match {match_id}: {tracking_error}")
            
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
        
    match_id = str(data.get('match_id', '')).strip()
    home = data.get('home_team')
    away = data.get('away_team')
    force = data.get('force') == True
    
    if not match_id or not home or not away:
        return jsonify({'success': False, 'error': 'Missing match details (id, home_team, away_team)'})

    # The backend owns the mode decision: pre-match and in-play analysis use
    # different data semantics, while terminal fixtures remain ineligible.
    match_status = None
    match_metadata = None
    _, matches_by_id = load_match_store()
    match_metadata = matches_by_id.get(match_id)
    if match_metadata:
        try:
            match_status = int(match_metadata.get('status', 1))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': '比赛状态格式异常，请先同步最新赛事。'})
    if match_status is None:
        return jsonify({'success': False, 'error': '未在当前赛事列表中找到该比赛。请先同步最新赛事。'})
    if match_status not in ANALYSIS_STATUSES:
        return jsonify({'success': False, 'error': '仅支持未开赛、待定或进行中的赛事分析；已结束、取消或推迟赛事不能生成新报告。'})
    analysis_mode = 'live' if match_status in LIVE_STATUSES else 'prematch'
        
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
                
                cache_matches_mode = cache_data.get('analysis_mode') == analysis_mode
                if cache_matches_mode and cache_data.get('analysis_version') == AI_ANALYSIS_CACHE_VERSION and is_complete_analysis_cache(cache_data):
                    return jsonify({
                        'success': True, 
                        'status': 'completed', 
                        'cached': True, 
                        'live_snapshot': analysis_mode == 'live',
                        'reports': cache_data['reports'],
                        'final_ticket': cache_data.get('final_ticket', '')
                    })
                if not is_complete_analysis_cache(cache_data):
                    os.remove(ai_cache_file)
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
    success, err_msg, context_str = build_match_prompt_context(match_id, home, away, analysis_mode)
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
        args=(
            match_id, api_base, api_key, model_name, system_prompt, context_str, ai_cache_file,
            {
                'match_id': match_id,
                'home_team': match_metadata.get('home_team', home),
                'away_team': match_metadata.get('away_team', away),
                'kickoff': f"{match_metadata.get('date', '')} {match_metadata.get('time', '')}".strip(),
                'competition': match_metadata.get('competition', ''),
                'fixture_date': match_metadata.get('date', ''),
                'fixture_status': match_status,
                'analysis_mode': analysis_mode,
            },
            analysis_mode,
        )
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
            
            if cache_data.get('analysis_version') == AI_ANALYSIS_CACHE_VERSION and is_complete_analysis_cache(cache_data):
                return jsonify({
                    'success': True, 
                    'status': 'completed', 
                    'reports': cache_data['reports'],
                    'final_ticket': cache_data.get('final_ticket', ''),
                    'status_list': ['completed', 'completed', 'completed']
                })
            if not is_complete_analysis_cache(cache_data):
                os.remove(ai_cache_file)
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


def _enrich_prediction_samples(samples, matches_by_id):
    """Backfill filter fields for legacy prediction rows from the match store."""
    for sample in samples:
        fixture = matches_by_id.get(str(sample.get('match_id')), {})
        if not fixture:
            continue
        if not sample.get('competition'):
            sample['competition'] = fixture.get('competition', '')
        if not sample.get('fixture_date'):
            sample['fixture_date'] = fixture.get('date', '')
        if sample.get('fixture_status') is None:
            sample['fixture_status'] = fixture.get('status')
        if not sample.get('kickoff'):
            sample['kickoff'] = f"{fixture.get('date', '')} {fixture.get('time', '')}".strip()


@app.route('/api/prediction_backtest')
def prediction_backtest():
    """Settle completed tracked predictions and return transparent aggregate metrics."""
    try:
        matches, matches_by_id = load_match_store()
        settled = settle_finished_predictions(PREDICTION_DB_FILE, matches)
        data = prediction_summary(PREDICTION_DB_FILE)
        _enrich_prediction_samples(data.get('recent', []), matches_by_id)
        return jsonify({'success': True, 'newly_settled': settled, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': f'回测数据处理失败: {str(e)}'})


@app.route('/api/prediction_backtest/<int:prediction_id>')
def prediction_backtest_detail(prediction_id):
    """Return one backtest sample's fixture input, prediction, and settlement."""
    try:
        detail = prediction_detail(PREDICTION_DB_FILE, prediction_id)
        if not detail:
            return jsonify({'success': False, 'error': '未找到该预测样本'}), 404
        _, matches_by_id = load_match_store()
        _enrich_prediction_samples([detail], matches_by_id)
        return jsonify({'success': True, 'data': detail})
    except Exception as e:
        return jsonify({'success': False, 'error': f'读取预测样本失败: {str(e)}'})



if __name__ == '__main__':
    # Run locally or on server port 5000, listening on all interfaces
    start_refresh_scheduler()
    app.run(host='0.0.0.0', port=5000)
