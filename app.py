# -*- coding: utf-8 -*-
from flask import Flask, jsonify, render_template, request, send_from_directory
import json
import os
import datetime
import hashlib
import functools
import math
import re
import tempfile
import threading
import time
import uuid
import sqlite3
from contextlib import closing
from leisu_crawler import fetch_matches
from detail_scraper import get_complete_match_details, get_odds_detail_via_playwright, get_real_odds
from scraper import scrape_desktop_matches
from prediction_tracker import init_database, prediction_detail, record_prediction, settle_finished_predictions, summary as prediction_summary

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

DATA_FILE = os.path.join(os.path.dirname(__file__), 'parsed_matches.json')
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
AI_ANALYSIS_CACHE_VERSION = 8
STRATEGY_VERSION = 'dual-market-v3'
MAX_BATCH_ANALYSIS_SIZE = 6
BATCH_CONCURRENT_MATCHES = 6
# Odds history comes from one WAF-protected upstream. Prepare fixtures one at a
# time so a multi-match batch cannot multiply requests against that shared host.
BATCH_DETAIL_CONCURRENCY = 1
AI_VERSION_TIMEOUT_SECONDS = 480
CRO_TIMEOUT_SECONDS = 120
MAX_REASONING_CHARACTERS = 50000  # 单次研判思考字数上限（超过5万字无正文输出，判定为模型死循环并强行熔断重试）
MAX_SINGLE_VERSION_STREAM_SECONDS = 360  # 单次研判流式处理绝对耗时硬上限 (6分钟)
MODEL_CONNECT_TIMEOUT_SECONDS = 30
MODEL_STREAM_READ_TIMEOUT_SECONDS = 300
MODEL_REQUEST_CONCURRENCY = 12
MODEL_REQUEST_INTERVAL_SECONDS = 10
MODEL_REQUEST_MAX_ATTEMPTS = 4
MODEL_REQUEST_RETRY_DELAY_SECONDS = 1.5
BATCH_MATCH_TIMEOUT_SECONDS = 600
BATCH_HEARTBEAT_TIMEOUT_SECONDS = 5700
MIN_REQUIRED_ODDS_COMPANIES = 3
RECOMMENDED_ODDS_COMPANIES = 6
TREND_MARKETS = {"1": "让球", "3": "大小球"}
TREND_FETCH_MAX_ATTEMPTS = 3
TREND_FETCH_RETRY_DELAY_SECONDS = 3
# Keep the six-request strategic-company burst serialized but avoid adding
# almost a second of artificial delay after every successful network round-trip.
TREND_REQUEST_MIN_INTERVAL_SECONDS = 0.15
PREFERRED_TREND_COMPANY_IDS = ('22', '2', '3')
PREMATCH_STATUSES = {1, 13}
LIVE_STATUSES = {2, 3, 4, 5, 7, 10}
ANALYSIS_STATUSES = PREMATCH_STATUSES | LIVE_STATUSES
TERMINAL_STATUSES = {8, 9, 11, 12}
PREDICTION_DB_FILE = os.path.join(os.path.dirname(__file__), 'prediction_history.sqlite3')
BATCH_STATE_FILE = os.path.join(CACHE_DIR, 'latest_batch_ai_state.json')
ANALYSIS_TRACE_DIR = os.path.join(CACHE_DIR, 'analysis_traces')
LIVE_DETAILS_CACHE_TTL_SECONDS = 90
PREMATCH_AI_CACHE_TTL_SECONDS = 90

class ApiKeyPool:
    """Thread-safe API Key pool supporting multi-account load balancing and 429 cooldowns."""
    def __init__(self, key_source=None):
        self._lock = threading.RLock()
        self._index = 0
        self._keys = []
        self._cooldowns = {}  # {key: timestamp_when_available}
        if key_source:
            self.set_keys(key_source)

    def set_keys(self, key_source):
        with self._lock:
            keys = []
            if isinstance(key_source, list):
                for k in key_source:
                    if isinstance(k, str) and k.strip():
                        keys.append(k.strip())
            elif isinstance(key_source, str):
                raw_parts = re.split(r'[\r\n,;]+', key_source)
                for part in raw_parts:
                    k = part.strip()
                    if k:
                        keys.append(k)
            seen = set()
            self._keys = [k for k in keys if not (k in seen or seen.add(k))]
            self._index = 0

    def get_keys(self):
        with self._lock:
            return list(self._keys)

    def key_count(self):
        with self._lock:
            return len(self._keys)

    def get_key(self, preferred_key=None, exclude_keys=None):
        with self._lock:
            if not self._keys:
                clean_pref = str(preferred_key or '').strip()
                if clean_pref and ',' not in clean_pref and '\n' not in clean_pref and ';' not in clean_pref:
                    return clean_pref
                return ''
            
            clean_pref = str(preferred_key or '').strip()
            now = time.monotonic()
            if clean_pref and ',' not in clean_pref and '\n' not in clean_pref and ';' not in clean_pref and clean_pref in self._keys:
                if self._cooldowns.get(clean_pref, 0.0) <= now:
                    return clean_pref

            exclude = set(exclude_keys or [])
            candidates = [k for k in self._keys if k not in exclude]
            if not candidates:
                candidates = list(self._keys)
            healthy_candidates = [k for k in candidates if self._cooldowns.get(k, 0.0) <= now]
            if healthy_candidates:
                key = healthy_candidates[self._index % len(healthy_candidates)]
                self._index = (self._index + 1) % len(self._keys)
                return key
            candidates_by_expiry = sorted(candidates, key=lambda k: self._cooldowns.get(k, 0.0))
            earliest_key = candidates_by_expiry[0]
            wait_time = self._cooldowns.get(earliest_key, 0.0) - now
            if 0 < wait_time <= 15.0:
                time.sleep(wait_time)
            return earliest_key

    def report_rate_limit(self, key, cooldown_seconds=20.0):
        if not key:
            return
        with self._lock:
            self._cooldowns[key] = time.monotonic() + cooldown_seconds
            print(f"[ApiKeyPool] Key {key[:6]}... rate-limited (429), cooling down for {cooldown_seconds}s")

    def report_success(self, key):
        if not key:
            return
        with self._lock:
            self._cooldowns.pop(key, None)

global_api_key_pool = ApiKeyPool()

# Detail scraping shares the upstream anti-bot session. Keep this limiter global
# so a batch cannot accidentally turn six fixtures into a WAF burst.
_detail_prepare_semaphore = threading.BoundedSemaphore(BATCH_DETAIL_CONCURRENCY)
_trend_request_lock = threading.Lock()
_trend_next_request_at = 0.0
_model_request_semaphore = threading.BoundedSemaphore(MODEL_REQUEST_CONCURRENCY)
_model_last_model_request = 0.0
_rate_limit_lock = threading.Lock()
_model_rate_limit_backoff = 5.0  # starts at 5s, dynamic failover

# The browser can issue overlapping refreshes. Keep the shared fixture file
# coherent and avoid repeatedly decoding several megabytes for every request.
_match_store_lock = threading.RLock()
_match_store_cache = {'mtime_ns': None, 'matches': [], 'by_id': {}}
_refresh_lock = threading.Lock()
_refresh_scheduler_started = False

DEFAULT_SYSTEM_PROMPT = """# Role: 顶级量化体育精算师 & 博彩机构风险控制专家

## Profile:
你负责对公开赛前数据进行可复核的量化分析。只使用输入中明确提供的赔率、走势、战绩、伤停与阵容；区分可观察事实与推断，不猜测博彩公司意图。核心任务是比较市场去水概率、固定进球基线与基本面证据，在亚洲让球和大小球两个独立市场中识别可验证的价格偏差；证据不足时输出 no_bet。

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
4. 战意与赛程密集度 (权重 20%)，以下五个子任务必须逐项完成，严禁遗漏：
   4a. **积分战意审计**：结合【五、 联赛积分榜对比】分析两队积分分差与夺冠/争四/保级驱动力，识别是否具备升班马属性。
   4b. **半全场韧性评估**：结合【七、 半全场胜负统计】评估落后翻盘率与领先被逆转率。
   4c. **进球节奏与体能分析**：结合【六、 进球时间段分布】的 6 个时段数据，评估球队是属于"抢开局慢热型"还是"下半场体能崩盘型"。
   4d. **主力缺阵折损定量**：对比伤停名单，识别缺阵人员是否为核心射手或防守中坚，定量折算主力核心缺席对进攻端进球率/防守端零封率的折损比例。
   4e. **强弱交手特征提取**：对比近 10 场对手在积分榜上的排名，将积分榜前 25% 定义为强队（上游）、后 25% 定义为弱队（下游），计算两队面对强队和弱队时的场均得失球差异，分析其是属于"硬仗韧性佳"还是"虐菜极其稳定"（欺软怕硬特征）。

### Step 2: 赔率隐含概率与三家公司市场审计
1. **还原抽水（Margin）**：计算初盘与即时盘的还原率，剔除博彩公司的利润抽水，还原两队的纯市场隐含概率。
2. **三家公司职责**：
   - **Pinnacle**：作为高流动性价格参考，观察其初盘到即时盘的盘口与水位变化。
   - **Bet365**：作为大众市场价格参考，用于判断市场报价是否同步。
   - **皇冠**：作为亚洲盘口参考，重点核对让球与大小球门槛是否一致。
3. **可观察变化审计**：只描述三家公司实际出现的升降盘、升降水及分歧。公司一致变化可以作为市场信号，但不能单独证明比赛方向；公司分歧只降低置信度，不能自动推出反向结论。必须将盘口变化与基本面、固定概率基线及可执行水位共同核验。

### Step 3: 标准盘口数学模型退化推演与价值洼地识别
对比即时盘口水位与后端提供的固定概率基线，使用以下公式量化正期望值：
- **期望值公式**：EV = (真实概率 × 赔率) - 1。若 EV > 0 则该方向存在正期望价值。
- 必须在报告中输出核心推荐方向的具体 EV 数值（保留两位小数），作为排序依据。
- 找出哪一方的赔率具备真正的正期望值（+EV），EV 越高排序越靠前。

---

## 输出格式（结构化精细报告）

### 📑 赛事全维度量化精算审计报告

#### 一、 基本面骨架与核心变量加权
- **特征加权评分**：状态( /30) | 主客场( /30) | 伤停克制( /20) | 战意赛程( /20)
- **积分战意与半全场纠偏**：[结合积分榜分差与半全场逆转率，对主客队真实拉力进行细节纠偏，指出是否具备升班马背景]
- **主力缺阵与攻防折损率**：[对比伤停名单，核算核心射手/防守主力缺席对攻防能力的定量折损]
- **进球节奏与强弱交手审计**：[分析 6 个时段进球集中度与得失球率，判定抢开局/慢热/体能崩盘类型；对比近 10 场面对积分榜前 25%(强队)和后 25%(弱队)的场均得失球差异，提炼虐菜/硬仗表现]
- **核心量化拉力点**：[直接融合有利与不利情报，客观描述对比赛走势影响最大的关键基本面变量]

#### 二、 盘口语言解码：隐含概率与风控审计
- **隐含概率转换**：初盘隐含概率（胜% / 平% / 负%） ➡️ 即时隐含概率（胜% / 平% / 负%）
- **三家公司变化审计**：[逐项比较 Pinnacle、Bet365、皇冠的盘口与水位变化，明确一致信号、分歧和数据缺失，不推断公司主观意图]
- **大小球动态风险**：[分析大小球门槛变化与大/小球方的真实赔付敞口]

#### 三、 市场价格与数学期望推演
- **市场基线区间**：[根据输入中的固定进球基线与去水概率，给出可复核的概率区间]
- **价值洼地（Value Betting）识别**：[结合去水概率、固定基线 EV 与基本面证据，指出可验证的价格偏差；没有则 no_bet]

#### 四、 📊 操盘手终极研判结论（量化期望值排序）

##### 1. 亚洲让球盘推荐
- **【最佳价值切入】**：[具体临场盘口与方向，或 no_bet] | **预期回报形态**：[严格遵循标准让球盘清算规则] | **风控逻辑**：[基于可观察数据与价格偏差的理由]

##### 2. 总进球数（大小球）推荐
- **【最佳价值切入】**：[大球或小球 + 临场盘口] | **风控逻辑**：[理由]
- **【高频进球区间】**：[进球数区间]

### 🎯 两个独立市场的最终结论
[分别给出亚洲让球与大小球的推荐或 no_bet，并按证据强度排序；不得添加输入中不存在的盘口]"""

CRO_SYSTEM_PROMPT = """# Role: 量化基金首席风险官（CRO）& 终极决策共识审计长

## Profile:
你负责审核同一模型基于同一数据生成的3份赛事研判报告。你的任务是去重证据、核对盘口与固定基线、保留真实分歧，并输出一张可审计的风险决策单。不得把文本一致当作独立验证；没有可验证优势时必须输出 no_bet。

## ⚠️ 终极柔性聚合规则（最高准则）：
1. **共识归纳（证据去重）**：深度比对3份报告中的推荐与证据来源。同一模型基于同一份赔率、战绩或伤停数据得到相同结论，只能算一份证据，绝不能因 2 份或 3 份文本重复就判定为【核心共识项】或提高置信度。只有当基本面、去水市场概率、反方审计三类证据分别支持同一方向，才可标为核心项；必须同时列出反方证据。
2. **多维冲突处理协议**：
   - **亚洲让球盘软化**：若下属小组对让球方向发生对立分歧，不得把“高水、欧亚脱节或机构差异”视为自动反向信号。只有可观察的赔率变化与至少两项直接基本面证据共同支持时才采信该方向；否则降级为低置信观察，不得强行反手。
   - **大小球玩法软化**：大小球出现大/小方向完全对立时，不得把争议强行转化为中置进球区间或对冲单。必须保留分歧、降低置信度；缺乏独立量化优势时不输出该市场的主推荐。
3. **精算清算校验**：严格复核各报告的亚盘表述。必须明确整数让球盘口（如 +1、+2 等）在刚好净胜对应球数时的结算结果为“走水保本（退还本金）”，纠正 any 关于整数盘“赢半/输半”的业余常识笔误。
4. **资金下注指引（Staking Plan）**：必须使用2%固定均注防线模型。以1个标准单位（Unit）为基准，根据共识与动能强度，给出精确的资金分配比例。

---

## 输出格式（必须是精简的一页纸下注执行单）

### 📊 基金风控中心·终极下注执行单

#### 一、 3次量化研判·证据去重与分歧审计
- 【可验证的共同证据】：[只归纳来自不同数据维度的同向证据，不把报告数量当作证据数量]
- 【冲突与反方证据】：[列出盘口、固定基线、基本面之间的冲突；冲突无法解释时降低置信度或 no_bet]

#### 二、 🎯 终极执行买入方案（精简收敛版，最多保留 2 个选项）

##### 【执行主单·核心动能/共识项】
- **投资项目**：[具体盘口与方向，例如：大田市民 -0.25，或 济州联 0]
- **注码权重**：[精确到单位，例如：1.0 标准单位（Unit）]
- **首席CRO聚合逻辑**：[说明该选项相对去水市场概率的优势、独立证据和标准清算边界；若不足则写 no_bet]

##### 【第二独立市场】（若无可验证优势则写“无/no_bet”）
- **投资项目**：[另一个独立市场中输入真实存在的具体盘口与方向]
- **注码权重**：[精确到单位，例如：0.5 标准单位（Unit）]
- **首席CRO聚合逻辑**：[解释该独立市场是否存在可验证优势及其风险边界]

#### 三、 📉 资金分配与风险边际铁律
- **单场总头寸控制**：本次策略总计消耗 [X] 个标准单位（单场最高绝不超过 1.5 个单位）。
- **执行纪律提示**：[明确风控线，严格遵守仓位纪律]"""

PREDICTION_POLICY = """这是足球预测链路。输入会明确标记为“赛前分析”或“滚球分析”，必须严格按该模式判断：
0. **市场中性与反偏置铁律（优先于所有角色设定）**：先以去水后的即时赔率作为市场基线，再比较基本面证据。不得因为“高水、退盘、未跟盘、机构差异、热门”就默认反选平局、受让方或小球；这些现象只能降低某一方向的置信度，不能单独构成反向推荐理由。
1. 赛前分析不得使用走地赔率、已结束比分或赛后数据；滚球分析可以使用输入中的当前比分与走地盘口，但不得把它们表述为赛前证据。
2. 仅分析和输出亚洲让球、大小球两个市场；不得输出胜平负推荐、平局对冲或将胜平负写入 prediction_record。每个市场必须同时列出：市场基线方向、推荐方向、推荐概率、该方向的反方证据。只有推荐概率相对去水市场概率存在明确增量，才可称为 Value 或正 EV；无法计算时不得编造 EV。
3. **反向方向准入门槛**：
   - 平局：不得因“机构安全阀”或低比分叙事直接推荐；必须同时具备明确的平局基本面证据和相对市场平局概率的定量优势。
   - 受让方：不得仅因上盘高水、退盘或“诱上”推荐；必须同时具备至少两项直接基本面证据，并说明为何盘口让步不足以覆盖这些证据。
   - 小球：不得仅因降盘、低水或历史小球率推荐；必须同时审计双方近期进攻、失球和进球时段，并明确大球的反方风险。
4. 三个分析版本使用同一数据和同一模型，结论相同不是独立验证。CRO 只能把一致性当作摘要，不得把“2/3 共识”单独升级为高置信度或强制下注依据；证据来源重叠时按单一证据处理。
5. 情报、伤停、交锋或赔率缺失时，明确标记缺失并降低置信度；缺失赔率时不得使用盘口语言给出强结论。若任一市场没有可验证的概率优势，必须明确选择 no_bet；不得为了填满执行单而给出方向。
6. 不得编造市场参与者行为、公司意图、EV 百分比、xG 或历史统计。只能描述输入中可观察到的赔率变化。让球和大小球必须使用输入中存在的具体盘口。
7. **置信度校准铁律**：仅当以下条件同时满足时方可标注 high 置信度：(a) 赔率方向与基本面完全一致；(b) 推荐方向相对去水市场概率有明确量化优势；(c) 核心数据维度无缺失；(d) 存在充分的反方证据审计。若任一条件不满足，最高只能标注 medium。数据大面积缺失时只能标注 low。"""

ANALYST_OUTPUT_LIMIT = """输出应是可执行的分析摘要，而非逐项复述原始数据：
1. 只保留影响结论的证据、反方证据、两个市场结论和风险条件；避免重复解释相同盘口。
2. 使用简洁的 Markdown，全文不超过 1,600 个汉字或等量内容。
3. 不得输出思维链、内部推演过程或与结论无关的泛泛说明。"""

TRACKING_OUTPUT_CONTRACT = """报告最后必须附上唯一一个 JSON 代码块，供赛后自动结算，格式严格如下：
```json
{"prediction_record":{"status":"bet|no_bet","asian_handicap":{"team":"home|away","line":-0.25}|null,"over_under":{"side":"over|under","line":2.5}|null,"confidence":"high|medium|low","reason":"简短依据"}}
```
只分析和结算让球、大小球，严禁附带胜平负字段。若两市场均无量化优势，写 status=no_bet，两个市场均为 null；no_bet 不进入赢盘率。若 status=bet，至少推荐一个市场。让球 `line` 是推荐球队获得的让球值：主队让 0.25 写 team=home、line=-0.25；客队受让 0.25 写 team=away、line=0.25。只能填入输入中存在的盘口。"""

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
DEFAULT_TRACKING_COHORT_ID = 'dual-market-v2-validation-1'
DEFAULT_TRACKING_COHORT_NAME = '双市场 v2 - 验证批次 1'


def _tracking_cohort_state(config):
    """Normalize persistent backtest cohorts without changing the strategy."""
    cohorts = config.get('tracking_cohorts') if isinstance(config, dict) else None
    if not isinstance(cohorts, list):
        cohorts = []
    normalized = []
    seen = set()
    for cohort in cohorts:
        cohort_id = str(cohort.get('id', '')).strip() if isinstance(cohort, dict) else ''
        name = str(cohort.get('name', '')).strip() if isinstance(cohort, dict) else ''
        if cohort_id and name and cohort_id not in seen:
            normalized.append({'id': cohort_id, 'name': name, 'strategy_version': STRATEGY_VERSION})
            seen.add(cohort_id)
    if not normalized:
        normalized.append({
            'id': DEFAULT_TRACKING_COHORT_ID,
            'name': DEFAULT_TRACKING_COHORT_NAME,
            'strategy_version': STRATEGY_VERSION,
        })
    active_id = str(config.get('active_tracking_cohort', '')).strip() if isinstance(config, dict) else ''
    if active_id not in {cohort['id'] for cohort in normalized}:
        active_id = normalized[-1]['id']
    return normalized, active_id


def _read_config_file():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as config_file:
            data = json.load(config_file)
        if isinstance(data, dict):
            key_source = data.get('api_key') or data.get('api_keys')
            if key_source:
                global_api_key_pool.set_keys(key_source)
            return data
        return {}
    except Exception:
        return {}


def _attach_tracking_cohort_state(config):
    cohorts, active_id = _tracking_cohort_state(config)
    config['tracking_cohorts'] = cohorts
    config['active_tracking_cohort'] = active_id
    return config

@app.route('/api/ai_config', methods=['GET'])
def get_ai_config():
    if os.path.exists(CONFIG_FILE):
        try:
            config = _attach_tracking_cohort_state(_read_config_file())
            # Strategy prompts are versioned in code so UI edits cannot leave
            # batch and single-match analysis on incompatible prompt versions.
            config['system_prompt'] = DEFAULT_SYSTEM_PROMPT
            config['strategy_version'] = STRATEGY_VERSION
            # The browser only needs the configuration shape. Returning the
            # stored provider key to any unauthenticated visitor exposed it.
            safe_config = config.copy()
            safe_config['api_key'] = ''
            safe_config['key_count'] = global_api_key_pool.key_count()
            return jsonify({'success': True, 'data': safe_config})
        except Exception as e:
            pass
    # 默认值兜底，避免全新部署时文件不存在导致前端加载卡死
    default_config = {
        'api_key': '',
        'api_base': 'https://opencode.ai/zen/v1',
        'model_name': 'deepseek-v4-flash-free',
        'system_prompt': DEFAULT_SYSTEM_PROMPT,
        'strategy_version': STRATEGY_VERSION,
        'key_count': global_api_key_pool.key_count(),
    }
    _attach_tracking_cohort_state(default_config)
    return jsonify({'success': True, 'data': default_config})

@app.route('/api/ai_config', methods=['POST'])
def save_ai_config():
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': '提交内容为空。'})
    
    existing_config = _read_config_file()
    existing_key = existing_config.get('api_key', '')
    cohorts, active_cohort = _tracking_cohort_state(existing_config)

    raw_key_input = str(data.get('api_key', '')).strip()
    active_key = raw_key_input or existing_key

    config = {
        'api_key': active_key,
        'api_base': data.get('api_base', 'https://opencode.ai/zen/v1'),
        'model_name': data.get('model_name', 'minimax-m2.5-free'),
        'system_prompt': DEFAULT_SYSTEM_PROMPT,
        'strategy_version': STRATEGY_VERSION,
        'tracking_cohorts': cohorts,
        'active_tracking_cohort': active_cohort,
    }
    
    global_api_key_pool.set_keys(active_key)
    
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True, 'message': "Config saved successfully", 'key_count': global_api_key_pool.key_count()})
    except Exception as e:
        return jsonify({'success': False, 'error': f"Write config error: {str(e)}"})


@app.route('/api/prediction_backtest/cohorts', methods=['POST'])
def create_prediction_backtest_cohort():
    """Start a fresh comparison cohort while retaining all prior samples."""
    config = _read_config_file()
    cohorts, _ = _tracking_cohort_state(config)
    next_number = len(cohorts) + 1
    cohort_id = f'dual-market-v2-validation-{next_number}'
    while any(cohort['id'] == cohort_id for cohort in cohorts):
        next_number += 1
        cohort_id = f'dual-market-v2-validation-{next_number}'
    cohort = {
        'id': cohort_id,
        'name': f'双市场 v2 - 验证批次 {next_number}',
        'strategy_version': STRATEGY_VERSION,
    }
    cohorts.append(cohort)
    config['tracking_cohorts'] = cohorts
    config['active_tracking_cohort'] = cohort_id
    config['strategy_version'] = STRATEGY_VERSION
    config['system_prompt'] = DEFAULT_SYSTEM_PROMPT
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as config_file:
            json.dump(config, config_file, ensure_ascii=False, indent=2)
        return jsonify({'success': True, 'data': {'cohort': cohort, 'active_cohort': cohort_id}})
    except Exception as error:
        return jsonify({'success': False, 'error': f'创建统计批次失败: {str(error)}'})

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


# ---------------------------------------------------------------------------
# 全局任务守卫线程 (P0-1)
# 每 60s 扫描一次所有进行中的 AI 任务，若心跳超过 TASK_HARD_TIMEOUT 秒
# 没有更新则强制标记为 timed_out，防止任务永久卡死。
# ---------------------------------------------------------------------------
TASK_HARD_TIMEOUT_SECONDS = 1200  # 20 分钟

def _task_watchdog_loop():
    """Background daemon: reap stalled ai_tasks and batch items."""
    while True:
        try:
            time.sleep(60)
            now = time.time()
            # --- 单场 ai_tasks ---
            for key, task in list(ai_tasks.items()):
                if not isinstance(task, dict):
                    continue
                if task.get('status') != 'processing':
                    continue
                age = now - task.get('heartbeat_at', now)
                if age > TASK_HARD_TIMEOUT_SECONDS:
                    print(f'[Watchdog] ai_task={key} 心跳超时 {int(age//60)} 分钟，强制标记 timed_out')
                    task['status'] = 'timed_out'
                    task['error'] = f'任务已超时（{int(age//60)} 分钟无响应），请重试'
                    # 把仍在 processing 的研判标为 failed
                    for idx, st in enumerate(task.get('status_list', [])):
                        if st == 'processing':
                            task['status_list'][idx] = 'failed'
                            out = (task.get('analyst_outputs') or [None, None, None])[idx]
                            if isinstance(out, dict) and out.get('status') not in ('completed', 'failed'):
                                out['status'] = 'failed'
                                out['error_msg'] = '任务守卫：心跳超时，强制终止'

            # --- 批量 batch_ai_tasks ---
            with _batch_ai_tasks_lock:
                batch_snapshot = dict(batch_ai_tasks)
            for batch_id, batch in batch_snapshot.items():
                if batch.get('status') != 'processing':
                    continue
                for item in batch.get('items', []):
                    if item.get('status') != 'processing':
                        continue
                    item_age = now - item.get('heartbeat_at', now)
                    if item_age > TASK_HARD_TIMEOUT_SECONDS:
                        print(f'[Watchdog] batch={batch_id} match={item.get("match_id")} 心跳超时 {int(item_age//60)} 分钟，强制标 timed_out')
                        item['status'] = 'timed_out'
                        item['phase'] = f'任务超时（{int(item_age//60)} 分钟无响应）'
                        # 同步 ai_task
                        task_key = item.get('task_key', item.get('match_id', ''))
                        if task_key in ai_tasks and isinstance(ai_tasks[task_key], dict):
                            ai_tasks[task_key]['status'] = 'timed_out'
        except Exception as e:
            print(f'[Watchdog] 异常: {e}')


def _start_task_watchdog():
    threading.Thread(target=_task_watchdog_loop, name='task-watchdog', daemon=True).start()
    print('[Watchdog] 任务守卫线程已启动（超时阈值 20 分钟）')


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
            has_odds = data.get('odds_index') and len(data['odds_index']) > 0
            has_standings = data.get('standings') is not None
            has_goal_dist = data.get('goal_distribution') is not None
            
            # 若比赛未完场，必须确保赔率、积分、进球分布全部存在，否则判定为残缺缓存直接失效重新拉取
            if not is_finished:
                if not has_odds or not has_standings or not has_goal_dist:
                    data = None
            else:
                # 已完场赛事，仅校验是否存在赔率指数
                if not has_odds:
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
        _invalidate_ai_cache_if_market_changed(match_id, details)
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


def _trend_companies_from_odds(odds_index):
    """Return companies for trend fetching: preferred 3 first, then fill from available."""
    companies_by_cid = {}
    failures = []
    for item in odds_index if isinstance(odds_index, list) else []:
        company_name = str(item.get('company', '')).strip()
        cid = item.get('cid')
        if not company_name or cid in (None, ''):
            failures.append(f'{company_name or "未知公司"}: 缺少公司 cid，无法获取变盘历史')
            continue
        cid = str(cid)
        if cid not in companies_by_cid:
            companies_by_cid[cid] = (company_name, cid)
    # Use PREFERRED_TREND_COMPANY_IDS as priority order (tests mock this)
    preferred = PREFERRED_TREND_COMPANY_IDS
    companies = []
    seen = set()
    for cid in preferred:
        if cid in companies_by_cid:
            companies.append(companies_by_cid[cid])
            seen.add(cid)
    # Fill with remaining available companies up to 3 total
    for cid in companies_by_cid:
        if len(companies) >= 3:
            break
        if cid not in seen:
            companies.append(companies_by_cid[cid])
            seen.add(cid)
    return companies, failures


def _trend_markets_for_company(odds_item):
    """Return market types that this company actually quotes for the fixture.

    New snapshots explicitly mark absent markets.  Older snapshots did not, so
    preserve their conservative behaviour until a fresh detail snapshot exists.
    """
    markets = []
    handicap = odds_item.get('handicap', {}) if isinstance(odds_item, dict) else {}
    totals = odds_item.get('over_under', {}) if isinstance(odds_item, dict) else {}
    if handicap.get('available', True):
        markets.append('1')
    if totals.get('available', True):
        markets.append('3')
    return markets


def _valid_trend_history(candidate):
    if not isinstance(candidate, list) or not candidate:
        return False
    return any(
        isinstance(row, dict)
        and _number(row.get('line')) is not None
        and _number(row.get('home')) is not None
        and _number(row.get('away')) is not None
        for row in candidate
    )


def _fetch_trend_with_global_pacing(match_id, cid, type_val):
    """Serialize WAF-protected odds calls across all batch workers."""
    global _trend_next_request_at
    with _trend_request_lock:
        delay = _trend_next_request_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        try:
            return get_odds_detail_via_playwright(match_id, cid, type_val)
        finally:
            import random
            _trend_next_request_at = time.monotonic() + TREND_REQUEST_MIN_INTERVAL_SECONDS + random.uniform(0.1, 0.3)


def _refresh_required_trend_history(match_id, odds_index, analysis_mode='prematch'):
    """Fetch fresh handicap and totals trends for the three strategic companies.

    Each company/market pair is retried before the fixture is rejected. Existing
    cache files are removed before a fresh request, so stale trend data cannot
    silently qualify a batch analysis.
    """
    failures = []
    refreshed = 0
    companies, company_failures = _trend_companies_from_odds(odds_index)
    failures.extend(company_failures)
    markets_by_cid = {
        str(item.get('cid')): _trend_markets_for_company(item)
        for item in odds_index if isinstance(item, dict) and item.get('cid') not in (None, '')
    }
    expected = sum(len(markets_by_cid.get(cid, [])) for _, cid in companies)
    if not companies:
        return False, '赔率快照中没有可用于趋势抓取的公司', {
            'required': expected, 'refreshed': refreshed, 'failures': failures, 'complete': False,
        }

    for company_name, cid in companies:
        for type_val in markets_by_cid.get(cid, []):
            market_name = TREND_MARKETS[type_val]
            cache_path = os.path.join(CACHE_DIR, f'odds_detail_{match_id}_{cid}_{type_val}.json')
            try:
                if os.path.exists(cache_path):
                    os.remove(cache_path)
            except OSError as error:
                failures.append(f'{company_name}{market_name}: 旧缓存清理失败 {error}')
                continue
            data = None
            last_error = ''
            for attempt in range(1, TREND_FETCH_MAX_ATTEMPTS + 1):
                try:
                    candidate = _fetch_trend_with_global_pacing(match_id, cid, type_val)
                except Exception as error:
                    candidate = None
                    last_error = str(error)
                else:
                    mode_candidate = _trend_rows_for_analysis_mode(candidate, analysis_mode)
                    if _valid_trend_history(mode_candidate):
                        data = mode_candidate
                        break
                    if analysis_mode == 'prematch' and _valid_trend_history(candidate):
                        last_error = '返回内容仅含走地记录，缺少赛前走势'
                    else:
                        last_error = candidate.get('error', '返回为空') if isinstance(candidate, dict) else '返回为空'
                if attempt < TREND_FETCH_MAX_ATTEMPTS:
                    time.sleep(TREND_FETCH_RETRY_DELAY_SECONDS * attempt)

            if data is None:
                failures.append(
                    f'{company_name}{market_name}: 连续 {TREND_FETCH_MAX_ATTEMPTS} 次获取失败 ({last_error})'
                )
                continue

            temp_path = None
            try:
                fd, temp_path = tempfile.mkstemp(prefix='odds_detail_', suffix='.json', dir=CACHE_DIR)
                with os.fdopen(fd, 'w', encoding='utf-8') as cache_file:
                    json.dump(data, cache_file, ensure_ascii=False)
                    cache_file.flush()
                    os.fsync(cache_file.fileno())
                os.replace(temp_path, cache_path)
                temp_path = None
                refreshed += 1
            except OSError as error:
                failures.append(f'{company_name}{market_name}: 缓存写入失败 {error}')
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)

    coverage_ratio = (refreshed / expected) if expected > 0 else 0.0
    complete = (expected > 0) and (refreshed == expected)
    degraded = (not complete) and (refreshed >= 1) and (coverage_ratio >= 0.55 or refreshed >= 8)

    quality = {
        'required': expected,
        'refreshed': refreshed,
        'failures': failures,
        'complete': complete,
        'degraded': degraded,
        'coverage_ratio': round(coverage_ratio, 3),
        'companies': [name for name, _ in companies],
        'markets_by_company': {
            name: [TREND_MARKETS[type_val] for type_val in markets_by_cid.get(cid, [])]
            for name, cid in companies
        },
        'attempts_per_market': TREND_FETCH_MAX_ATTEMPTS,
    }
    if not expected:
        return False, '赔率快照中没有可用的让球或大小球市场', quality
    if not complete and not degraded:
        return False, f"变盘历史未达到极小降级门槛（{refreshed}/{expected}，覆盖率 {coverage_ratio:.1%} < 55.0%）：{'；'.join(failures)}", quality
    return True, '', quality


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


def validate_report_recommendation_consistency(report_text):
    """Validate directional, line, odds, and EV consistency in analyst reports.

    Returns (is_valid, warning_message).
    """
    body = extract_final_output(report_text)
    if not body:
        return True, ''

    # Check for direct contradiction between EV analysis team preference vs recommendation team
    # Example: text says "真实期望值在[客/下盘]" but recommendation says "【最佳价值切入】：[主队]"
    ev_away_match = re.search(r'真实期望值在[：:\s]*(?:客队|客|下盘)', body)
    ev_home_match = re.search(r'真实期望值在[：:\s]*(?:主队|主|上盘)', body)

    rec_section = re.search(r'亚洲让球盘推荐.*?(?=总进球数|\Z)', body, re.DOTALL)
    if rec_section:
        rec_text = rec_section.group(0)
        rec_home = bool(re.search(r'【最佳价值切入】[：:\s]*[^\n]*(?:主|主队)', rec_text))
        rec_away = bool(re.search(r'【最佳价值切入】[：:\s]*[^\n]*(?:客|客队)', rec_text))

        if ev_away_match and rec_home and not rec_away:
            return False, "分析论证明确指出‘真实期望值在客队/下盘’，但 Asian 让球盘推荐项却切入‘主队’，存在方向倒置冲突"
        if ev_home_match and rec_away and not rec_home:
            return False, "分析论证明确指出‘真实期望值在主队/上盘’，但 Asian 让球盘推荐项却切入‘客队’，存在方向倒置冲突"

    return True, ''


def _market_snapshot_hash(details):
    """Hash the current odds snapshot so refreshed markets invalidate old reports."""
    payload = (details or {}).get('odds_index', []) if isinstance(details, dict) else []
    if isinstance(payload, list):
        payload = sorted(
            payload,
            key=lambda row: (str(row.get('cid', '')), str(row.get('company', '')))
            if isinstance(row, dict) else str(row),
        )
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _is_reusable_analysis_cache(cache_data, analysis_mode, now=None):
    """Only a recent pre-match report may be shown without a fresh snapshot."""
    if not isinstance(cache_data, dict):
        return False
    if analysis_mode != 'prematch':
        return False
    if (
        cache_data.get('analysis_version') != AI_ANALYSIS_CACHE_VERSION
        or cache_data.get('analysis_mode') != analysis_mode
        or not cache_data.get('snapshot_hash')
        or not cache_data.get('market_snapshot_hash')
        or not is_complete_analysis_cache(cache_data)
    ):
        return False
    try:
        captured_at = datetime.datetime.fromisoformat(cache_data['snapshot_captured_at'])
    except (KeyError, TypeError, ValueError):
        return False
    age = (now or datetime.datetime.now()) - captured_at
    return datetime.timedelta(0) <= age <= datetime.timedelta(seconds=PREMATCH_AI_CACHE_TTL_SECONDS)


def _invalidate_ai_cache_if_market_changed(match_id, details):
    """Discard a report when a refreshed detail response carries new odds."""
    cache_path = os.path.join(CACHE_DIR, f'ai_analysis_{match_id}.json')
    if not os.path.exists(cache_path):
        return False
    try:
        with open(cache_path, 'r', encoding='utf-8') as cache_file:
            cache_data = json.load(cache_file)
        if cache_data.get('market_snapshot_hash') == _market_snapshot_hash(details):
            return False
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    try:
        os.remove(cache_path)
        return True
    except OSError:
        return False


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


def _analysis_trace_path(match_id, trace_id):
    return os.path.join(ANALYSIS_TRACE_DIR, f'{match_id}_{trace_id}.json')


def _persist_analysis_trace(match_id, task_key, model_name, analysis_mode):
    """Persist inspectable model I/O for both successful and failed runs.

    The trace excludes HTTP headers, API keys, and raw reasoning. It stores
    prompts, visible report content, timestamps, and errors.
    """
    task = ai_tasks.get(task_key, {})
    trace_id = task.get('trace_id')
    if not trace_id:
        return None
    def audit_output(output):
        """Keep visible answers for review without retaining raw model reasoning."""
        if not isinstance(output, dict):
            return output
        audit = dict(output)
        if audit.pop('reasoning', ''):
            audit['reasoning_omitted'] = True
        return audit

    payload = {
        'trace_version': 1,
        'trace_id': trace_id,
        'match_id': str(match_id),
        'analysis_mode': analysis_mode,
        'model_name': model_name,
        'output_capture': 'visible-content-only',
        'status': task.get('status', 'unknown'),
        'phase': task.get('phase', 'ai'),
        'error': task.get('error', ''),
        'started_at': task.get('started_at'),
        'finished_at': time.time(),
        'snapshot_hash': task.get('snapshot_hash', ''),
        'analysis_input': task.get('analysis_input', ''),
        'analyst_inputs': task.get('analyst_inputs', []),
        'analyst_outputs': [audit_output(output) for output in task.get('analyst_outputs', [])],
        'analyst_reports': [extract_final_output(report) for report in task.get('reports', [])],
        'cro_input': task.get('cro_input'),
        'cro_output': audit_output(task.get('cro_output')),
        'final_report': extract_final_output(task.get('final_ticket', '')),
    }
    os.makedirs(ANALYSIS_TRACE_DIR, exist_ok=True)
    trace_path = _analysis_trace_path(match_id, trace_id)
    temp_path = f'{trace_path}.tmp'
    with open(temp_path, 'w', encoding='utf-8') as trace_file:
        json.dump(payload, trace_file, ensure_ascii=False, indent=2)
        trace_file.flush()
        os.fsync(trace_file.fileno())
    os.replace(temp_path, trace_path)
    return trace_path


def _persist_preparation_failure_trace(match_id, stage, error, details=None, trend_quality=None):
    """Persist an audit trace for details or odds preparation failure before AI starts."""
    trace_id = f"prep_failed_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    payload = {
        'trace_version': 1,
        'trace_id': trace_id,
        'match_id': str(match_id),
        'status': 'failed',
        'phase': f'preparation_{stage}',
        'error': str(error),
        'finished_at': time.time(),
        'details_available': bool(details),
        'trend_quality': trend_quality or {},
    }
    os.makedirs(ANALYSIS_TRACE_DIR, exist_ok=True)
    trace_path = _analysis_trace_path(match_id, trace_id)
    temp_path = f'{trace_path}.tmp'
    try:
        with open(temp_path, 'w', encoding='utf-8') as trace_file:
            json.dump(payload, trace_file, ensure_ascii=False, indent=2)
            trace_file.flush()
            os.fsync(trace_file.fileno())
        os.replace(temp_path, trace_path)
        return trace_path
    except OSError:
        return None


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
    tracking_cohorts = []
    active_tracking_cohort = DEFAULT_TRACKING_COHORT_ID
    env_api_key = os.environ.get('LINSHU_AI_API_KEY') or os.environ.get('OPENAI_API_KEY')
    if env_api_key:
        api_key = env_api_key.strip()
    if os.path.exists(CONFIG_FILE):
        try:
            cfg = _read_config_file()
            if not api_key:
                api_key = cfg.get('api_key', '')
            api_base = cfg.get('api_base', api_base)
            model_name = cfg.get('model_name', model_name)
            tracking_cohorts, active_tracking_cohort = _tracking_cohort_state(cfg)
        except Exception:
            pass

    if not tracking_cohorts:
        tracking_cohorts, active_tracking_cohort = _tracking_cohort_state({})
    active_cohort = next(
        cohort for cohort in tracking_cohorts if cohort['id'] == active_tracking_cohort
    )

    system_prompt = DEFAULT_SYSTEM_PROMPT
    if not api_key:
        return False, '请先在顶部“AI配置中心”中配置您的 API Key。', None
    return True, '', {
        'api_key': api_key,
        'api_base': api_base.rstrip('/'),
        'model_name': model_name,
        'system_prompt': system_prompt,
        'tracking_cohort_id': active_cohort['id'],
        'tracking_cohort_name': active_cohort['name'],
    }


def _detail_cache_path(match_id):
    return os.path.join(CACHE_DIR, f'details_{match_id}.json')


def _detail_quality_report(details):
    """Return an auditable completeness report; do not treat empty placeholders as valid data."""
    details = details if isinstance(details, dict) else {}
    pros_cons = details.get('pros_cons')
    injuries = details.get('injuries')
    h2h = details.get('h2h')
    recent = details.get('recent_results')
    odds = details.get('odds_index')

    odds_count = len(odds) if isinstance(odds, list) else 0
    odds_warning = None
    if MIN_REQUIRED_ODDS_COMPANIES <= odds_count < RECOMMENDED_ODDS_COMPANIES:
        odds_warning = f"赔率样本较少（仅 {odds_count} 家），已继续分析"

    checks = {
        'intelligence': isinstance(pros_cons, dict) and all(key in pros_cons for key in ('home', 'away')),
        'lineup_injuries': isinstance(injuries, dict) and all(key in injuries for key in ('home', 'away')),
        'history': isinstance(h2h, dict) and isinstance(h2h.get('matches'), list),
        # Recent form is required; an empty list usually means collection is incomplete,
        # so the batch must not start AI analysis from a partial snapshot.
        'recent_form': isinstance(recent, dict) and bool(recent.get('home')) and bool(recent.get('away')),
        'odds_snapshot': isinstance(odds, list) and len(odds) >= MIN_REQUIRED_ODDS_COMPANIES,
    }
    labels = {
        'intelligence': '情报数据',
        'lineup_injuries': '伤停与阵容',
        'history': '历史交锋',
        'recent_form': '近期战绩',
        'odds_snapshot': f'最少 {MIN_REQUIRED_ODDS_COMPANIES} 家赔率指数',
    }
    missing = [key for key, passed in checks.items() if not passed]
    # Only odds shortage blocks the snapshot; other missing dimensions
    # (intelligence, lineup, H2H, recent form) are logged as warnings only.
    snapshot_blocked = not checks.get('odds_snapshot', False)
    return {
        'passed': not snapshot_blocked,
        'blocked_reason': ('赔率指数不足' if snapshot_blocked else None),
        'checks': checks,
        'missing': missing,
        'missing_labels': [labels[key] for key in missing],
        'odds_companies': odds_count,
        'odds_warning': odds_warning,
    }


def _prepare_analysis_snapshot(match_id, home, away, force_refresh=True):
    """Fetch a fresh, validated detail snapshot for an analysis execution.

    This intentionally uses the same scraper and WAF session as single-match
    detail loading. The semaphore serializes upstream-sensitive collection;
    Data collection is capped at two fixtures to protect the upstream session;
    the AI stage may fan out to all six validated fixtures.
    """
    try:
        with _detail_prepare_semaphore:
            # 每次抓取前清理全局 CookieJar，避免残留的 WAF cookie 导致 TCP 连接异常
            from detail_scraper import GLOBAL_CJ, GLOBAL_ODDS_CJ, _GLOBAL_CJ_LOCK, _GLOBAL_ODDS_CJ_LOCK
            with _GLOBAL_CJ_LOCK:
                GLOBAL_CJ.clear()
            with _GLOBAL_ODDS_CJ_LOCK:
                GLOBAL_ODDS_CJ.clear()
            details = get_complete_match_details(match_id, home, away)
            if not details.get('odds_index'):
                details['odds_index'] = get_real_odds(match_id)
    except Exception as error:
        return False, f'详情数据抓取失败：{error}', None, None

    quality = _detail_quality_report(details)
    if not quality['passed']:
        # Only odds shortage (< 3 companies) blocks the snapshot
        return False, f"数据校验未通过：{quality['blocked_reason']}", details, quality
    if quality['missing']:
        # Non-blocking missing dimensions are logged for monitoring
        print(f"[{match_id}] 数据维度警告：缺少 {', '.join(quality['missing_labels'])}，继续分析")

    snapshot = {
        'captured_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'match_id': str(match_id),
        'quality': quality,
        'details': details,
        'market_hash': _market_snapshot_hash(details),
    }
    snapshot_payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
    snapshot['hash'] = hashlib.sha256(snapshot_payload.encode('utf-8')).hexdigest()
    try:
        with open(_detail_cache_path(match_id), 'w', encoding='utf-8') as cache_file:
            json.dump(details, cache_file, ensure_ascii=False, indent=2)
    except OSError as error:
        return False, f'详情数据缓存写入失败：{error}', details, quality
    return True, '', details, snapshot


def _has_reusable_prematch_cache(match_id):
    """Only completed, current-version pre-match reports may be reused in a batch."""
    ai_cache_file = os.path.join(CACHE_DIR, f'ai_analysis_{match_id}.json')
    if not os.path.exists(ai_cache_file):
        return False
    try:
        with open(ai_cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        return _is_reusable_analysis_cache(cache_data, 'prematch')
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
                item['phase'] = item.get('prepare_phase', '正在获取比赛数据')
            elif status == 'validating':
                item['phase'] = '正在校验数据完整性'
            elif status == 'processing':
                task = ai_tasks.get(item.get('task_key', item['match_id']), {})
                if task.get('status') in {'failed', 'timed_out'}:
                    item['phase'] = 'AI 分析失败'
                    item['error'] = task.get('error', item.get('error', '未知错误'))
                    if task.get('phase') == 'cro' and all(has_final_output(report) for report in task.get('reports', [])):
                        item['retry_scope'] = 'cro'
                    elif item.get('cached_context_str'):
                        item['retry_scope'] = 'ai'
                else:
                    status_list = task.get('status_list', [])
                    analyst_outputs = task.get('analyst_outputs', [])
                    v_details = []
                    for idx in range(3):
                        out = analyst_outputs[idx] if idx < len(analyst_outputs) else None
                        if not out or not isinstance(out, dict):
                            v_details.append({'v': idx + 1, 'status': 'waiting', 'label': f'研判{idx+1}: ⏳ 排队', 'len': 0, 'error_msg': ''})
                        else:
                            st = out.get('status', 'processing')
                            c_len = len(out.get('content', ''))
                            err = str(out.get('error', '') or out.get('error_msg', ''))[:120]
                            if st == 'completed':
                                v_details.append({'v': idx + 1, 'status': 'completed', 'label': f'研判{idx+1}: ✅ 完成({c_len}字)', 'len': c_len, 'error_msg': ''})
                            elif st == 'failed':
                                short_err = err[:40] + '…' if len(err) > 40 else err
                                v_details.append({'v': idx + 1, 'status': 'failed', 'label': f'研判{idx+1}: ❌ 失败', 'len': 0, 'error_msg': err})
                            elif c_len > 0:
                                v_details.append({'v': idx + 1, 'status': 'streaming', 'label': f'研判{idx+1}: ⚡ 生成中({c_len}字)', 'len': c_len, 'error_msg': ''})
                            elif st == 'streaming' or out.get('reasoning_received'):
                                r_len = out.get('reasoning_len', 0)
                                if r_len > 10000:
                                    r_label = f'研判{idx+1}: 🧠 推理中({r_len}字 ⚠️偏长)'
                                elif r_len > 0:
                                    r_label = f'研判{idx+1}: 🧠 推理中({r_len}字)'
                                else:
                                    r_label = f'研判{idx+1}: 🧠 推理中'
                                v_details.append({'v': idx + 1, 'status': 'streaming', 'label': r_label, 'len': 0, 'error_msg': ''})
                            else:
                                v_details.append({'v': idx + 1, 'status': 'waiting', 'label': f'研判{idx+1}: ⏳ 等待中', 'len': 0, 'error_msg': ''})
                    item['versions_detail'] = v_details


                    completed_versions = sum(value == 'completed' for value in status_list)
                    failed_versions = sum(value == 'failed' for value in status_list)
                    if completed_versions == 3:
                        item['phase'] = 'CRO 正在风控审计汇总最终执行单...'
                    elif failed_versions:
                        item['phase'] = f'AI 三路并行研判中（已完成 {completed_versions}/3，失败 {failed_versions}）'
                    else:
                        item['phase'] = f'AI 三路并行研判中（已完成 {completed_versions}/3）'
            elif status == 'completed':
                item['phase'] = '分析完成'
            elif status == 'cached':
                item['phase'] = '已复用赛前报告缓存'
            elif status == 'skipped':
                item['phase'] = '已跳过'
            elif status == 'timed_out':
                item['phase'] = '分析超时，可重试'
            elif status == 'failed':
                item['phase'] = '分析失败'
            elif status == 'cancelled':
                item['phase'] = item.get('phase', '已手动取消')
                item['versions_detail'] = [{'v': i+1, 'status': 'cancelled', 'label': f'研判{i+1}: 🚫 已取消', 'len': 0, 'error_msg': ''} for i in range(3)]
        counts = {
            'total': len(items),
            'completed': sum(item['status'] in {'completed', 'cached'} for item in items),
            'failed': sum(item['status'] in {'failed', 'timed_out'} for item in items),
            'timed_out': sum(item['status'] == 'timed_out' for item in items),
            'cancelled': sum(item['status'] == 'cancelled' for item in items),
            'processing': sum(item['status'] in {'preparing', 'validating', 'queued', 'processing'} for item in items),
            'cached': sum(item['status'] == 'cached' for item in items),
            'skipped': sum(item['status'] == 'skipped' for item in items),
        }
        return {
            'id': batch_id,
            'status': batch['status'],
            'counts': counts,
            'items': items,
        }


def _process_single_batch_item_pipeline(item, batch_id, runtime_config):
    """Self-contained asynchronous match analysis worker.

    Serializes upstream anti-bot data scraping via _detail_prepare_semaphore, then
    immediately fans out to multi-key parallel AI analysis without blocking other items.
    """
    match_id = item['match_id']
    with _batch_ai_tasks_lock:
        item['status'] = 'preparing'
        item['prepare_phase'] = '正在获取情报、阵容、战绩与赔率'
        item['started_at'] = time.time()
        item['heartbeat_at'] = time.time()

    success, error, details, snapshot = _prepare_analysis_snapshot(
        match_id, item['home_team'], item['away_team'], force_refresh=True
    )
    if not success:
        with _batch_ai_tasks_lock:
            item['status'] = 'failed'
            item['error'] = error
        return

    with _batch_ai_tasks_lock:
        item['prepare_phase'] = f"正在同步本场 {len(details.get('odds_index', []))} 家公司的让球与大小球变盘历史"
        item['heartbeat_at'] = time.time()

    trends_ok, trend_error, trend_quality = _refresh_required_trend_history(
        match_id, details.get('odds_index', []), item['analysis_mode']
    )
    snapshot['trend_quality'] = trend_quality
    if not trends_ok:
        with _batch_ai_tasks_lock:
            item['status'] = 'failed'
            item['error'] = trend_error
        return

    with _batch_ai_tasks_lock:
        item['status'] = 'validating'
        item['prepare_phase'] = '详情和变盘历史校验通过，正在构建独立分析上下文'
        item['data_quality'] = snapshot.get('quality', {})
        item['trend_quality'] = trend_quality
        item['snapshot_hash'] = snapshot.get('hash', '')
        item['snapshot_captured_at'] = snapshot.get('captured_at', '')
        item['heartbeat_at'] = time.time()

    success, error, context_str = build_match_prompt_context(
        match_id, item['home_team'], item['away_team'], item['analysis_mode'],
        details=details, trend_quality=trend_quality
    )
    if not success:
        with _batch_ai_tasks_lock:
            item['status'] = 'failed'
            item['error'] = error
        return

    ai_cache_file = os.path.join(CACHE_DIR, f"ai_analysis_{match_id}.json")
    if os.path.exists(ai_cache_file):
        try:
            os.remove(ai_cache_file)
        except OSError:
            pass

    prediction_metadata = {
        'match_id': match_id,
        'home_team': item['home_team'],
        'away_team': item['away_team'],
        'kickoff': item['kickoff'],
        'competition': item['competition'],
        'fixture_date': item['fixture_date'],
        'fixture_status': item['fixture_status'],
        'analysis_mode': item['analysis_mode'],
        'strategy_version': STRATEGY_VERSION,
        'tracking_cohort_id': runtime_config['tracking_cohort_id'],
        'tracking_cohort_name': runtime_config['tracking_cohort_name'],
        'market_catalog': _instant_market_catalog(
            details, _build_probability_baseline(details, item['home_team'], item['away_team'])
        ),
    }
    task_key = f"{batch_id}:{match_id}:{uuid.uuid4().hex}"
    with _batch_ai_tasks_lock:
        item['task_key'] = task_key
        item['status'] = 'processing'
        item['prepare_phase'] = ''
        item['heartbeat_at'] = time.time()

    # Fan out to 3 parallel AI versions + CRO synthesis using ApiKeyPool
    run_ai_analysis_thread(
        match_id, runtime_config['api_base'], runtime_config['api_key'],
        runtime_config['model_name'], runtime_config['system_prompt'], context_str,
        ai_cache_file, prediction_metadata, item['analysis_mode'], task_key, snapshot,
    )

    with _batch_ai_tasks_lock:
        task = ai_tasks.get(task_key, {})
        if task.get('status') == 'completed':
            item['status'] = 'completed'
        else:
            item['status'] = 'failed'
            item['error'] = task.get('error', 'AI 分析未完成，请单独重试。')
        _persist_latest_batch_state(batch_id)


def _run_batch_ai_analysis(batch_id, runtime_config):
    """Execute all queued match pipelines in parallel across the ThreadPoolExecutor."""
    try:
        with _batch_ai_tasks_lock:
            items = batch_ai_tasks[batch_id]['items']
        pending = [item for item in items if item['status'] == 'queued']

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_BATCH_ANALYSIS_SIZE) as executor:
            futures = [
                executor.submit(_process_single_batch_item_pipeline, item, batch_id, runtime_config)
                for item in pending
            ]
            concurrent.futures.wait(futures)

        with _batch_ai_tasks_lock:
            batch = batch_ai_tasks.get(batch_id)
            if batch:
                batch['status'] = 'completed'
                batch['finished_at'] = time.time()
        _persist_latest_batch_state(batch_id)
    except Exception as error:
        print(f"[Batch AI Engine] Batch {batch_id} unexpected failure: {error}")
        with _batch_ai_tasks_lock:
            batch = batch_ai_tasks.get(batch_id)
            if batch:
                batch['status'] = 'failed'
        _persist_latest_batch_state(batch_id)


def _run_batch_cro_retry(batch_id, match_id, task_key, runtime_config):
    """Retry only the CRO phase when all three analyst reports already exist."""
    try:
        task = ai_tasks.get(task_key, {})
        reports = task.get('reports', [])
        if len(reports) != 3 or not all(has_final_output(report) for report in reports):
            raise ValueError('三版本报告不完整，无法只重试 CRO。')
        reports_list = [extract_final_output(report) for report in reports]
        combined_reports = f"报告1:\n{reports_list[0]}\n\n报告2:\n{reports_list[1]}\n\n报告3:\n{reports_list[2]}"
        ai_tasks[task_key]['phase'] = 'cro'
        ai_tasks[task_key]['status'] = 'processing'
        ai_tasks[task_key]['heartbeat_at'] = time.time()
        final_ticket = _retry_model_operation(
            lambda: run_cro_aggregation(
                match_id, runtime_config['api_base'], runtime_config['api_key'],
                runtime_config['model_name'], combined_reports, task_key,
            ),
            lambda: bool(extract_final_output(ai_tasks.get(task_key, {}).get('final_ticket', ''))),
        )
        if not has_final_output(final_ticket):
            raise ValueError('CRO 未返回最终执行预测。')
        ai_tasks[task_key]['final_ticket'] = final_ticket
        ai_tasks[task_key]['status'] = 'completed'
        with _batch_ai_tasks_lock:
            batch = batch_ai_tasks.get(batch_id, {})
            item = next((row for row in batch.get('items', []) if str(row.get('match_id')) == str(match_id)), None)
            if not item:
                raise ValueError('批量任务中未找到该比赛。')
            cache_path = os.path.join(CACHE_DIR, f'ai_analysis_{match_id}.json')
            with open(cache_path, 'w', encoding='utf-8') as cache_file:
                json.dump({
                    'analysis_version': AI_ANALYSIS_CACHE_VERSION,
                    'analysis_mode': item.get('analysis_mode', 'prematch'),
                    'reports': reports,
                    'final_ticket': final_ticket,
                    'snapshot_hash': item.get('snapshot_hash', ''),
                    'market_snapshot_hash': item.get('market_snapshot_hash', ''),
                    'snapshot_captured_at': item.get('snapshot_captured_at', ''),
                }, cache_file, ensure_ascii=False, indent=2)
            item['status'] = 'completed'
            item.pop('error', None)
            item.pop('retry_scope', None)
            item['heartbeat_at'] = time.time()
            batch['status'] = 'completed' if not any(row.get('status') in {'queued', 'preparing', 'validating', 'processing'} for row in batch.get('items', [])) else 'processing'
    except Exception as error:
        current = ai_tasks.get(task_key, {})
        ai_tasks[task_key] = {
            **current,
            'status': 'failed',
            'phase': 'cro',
            'error': str(error),
            'heartbeat_at': time.time(),
        }
        with _batch_ai_tasks_lock:
            batch = batch_ai_tasks.get(batch_id, {})
            item = next((row for row in batch.get('items', []) if str(row.get('match_id')) == str(match_id)), None)
            if item:
                item['status'] = 'failed'
                item['error'] = str(error)
                item['retry_scope'] = 'cro'
    finally:
        _persist_latest_batch_state(batch_id)


def _prepare_batch_item(batch_id, item):
    """Collect and validate one fixture before it is eligible for AI work."""
    t0 = time.time()
    def _set_phase(msg):
        elapsed = int(time.time() - t0)
        with _batch_ai_tasks_lock:
            item['prepare_phase'] = msg if elapsed < 2 else f'{msg}（已用 {elapsed}s）'
            item['heartbeat_at'] = time.time()

    with _batch_ai_tasks_lock:
        item['status'] = 'preparing'
        item['prepare_phase'] = '① 获取赛事详情（情报 + 阵容 + H2H）...'
        item['started_at'] = t0
        item['heartbeat_at'] = t0
    _persist_latest_batch_state(batch_id)

    success, error, details, snapshot = _prepare_analysis_snapshot(
        item['match_id'], item['home_team'], item['away_team'], force_refresh=True
    )
    if not success:
        _persist_preparation_failure_trace(item['match_id'], 'details', error)
        return False, error, None, None

    odds_count = len(details.get('odds_index', []))
    _set_phase(f'② 同步赔率走势（{odds_count} 家公司）...')
    with _batch_ai_tasks_lock:
        item['data_quality'] = snapshot.get('quality', {})
        item['snapshot_hash'] = snapshot.get('hash', '')
        item['market_snapshot_hash'] = snapshot.get('market_hash', '')
        item['snapshot_captured_at'] = snapshot.get('captured_at', '')

    trends_ok, trend_error, trend_quality = _refresh_required_trend_history(
        item['match_id'], details.get('odds_index', []), item['analysis_mode']
    )
    snapshot['trend_quality'] = trend_quality
    snapshot['market_catalog'] = _instant_market_catalog(
        details, _build_probability_baseline(details, item['home_team'], item['away_team'])
    )
    if not trends_ok:
        _persist_preparation_failure_trace(item['match_id'], 'trend', trend_error, details=details, trend_quality=trend_quality)
        print(f"[{item['match_id']}] 趋势历史获取失败（非阻塞）：{trend_error}，继续分析")
        snapshot['trend_quality'] = {'required': 0, 'refreshed': 0, 'failures': [trend_error], 'complete': False}

    _set_phase('③ 校验数据质量并构建分析上下文...')
    with _batch_ai_tasks_lock:
        item['status'] = 'validating'
        item['trend_quality'] = trend_quality

    success, error, context_str = build_match_prompt_context(
        item['match_id'], item['home_team'], item['away_team'], item['analysis_mode'],
        details=details, trend_quality=trend_quality
    )
    if success:
        elapsed_total = int(time.time() - t0)
        with _batch_ai_tasks_lock:
            item['prepare_phase'] = f'✅ 数据准备完成（共 {elapsed_total}s）'
    return success, error, context_str, snapshot


def _run_batch_ai_analysis_v2(batch_id, runtime_config):
    """Two-stage batch pipeline: safe data preparation, then six isolated AI jobs."""
    prepared = []
    try:
        with _batch_ai_tasks_lock:
            items = [item for item in batch_ai_tasks[batch_id]['items'] if item['status'] == 'queued']

        # Preparation stage: sequential (BATCH_DETAIL_CONCURRENCY=1 anyway)
        for item in items:
            success, error, context_str, snapshot = _prepare_batch_item(batch_id, item)
            if item.get('status') == 'timed_out':
                continue
            if not success:
                with _batch_ai_tasks_lock:
                    item['status'] = 'failed'
                    item['error'] = str(error)
                _persist_latest_batch_state(batch_id)
                continue
            prepared.append((item, context_str, snapshot))
            # Cache for retry_ai reuse (no need to re-scrape if AI fails)
            with _batch_ai_tasks_lock:
                item['cached_context_str'] = context_str
                item['cached_snapshot'] = snapshot
            _persist_latest_batch_state(batch_id)

        with concurrent.futures.ThreadPoolExecutor(max_workers=BATCH_CONCURRENT_MATCHES) as ai_executor:
            active = {}
            for item, context_str, snapshot in prepared:
                ai_cache_file = os.path.join(CACHE_DIR, f"ai_analysis_{item['match_id']}.json")
                if os.path.exists(ai_cache_file):
                    try:
                        os.remove(ai_cache_file)
                    except OSError:
                        pass
                task_key = f"{batch_id}:{item['match_id']}:{uuid.uuid4().hex}"
                metadata = {
                    'match_id': item['match_id'], 'home_team': item['home_team'], 'away_team': item['away_team'],
                    'kickoff': item['kickoff'], 'competition': item['competition'], 'fixture_date': item['fixture_date'],
                    'fixture_status': item['fixture_status'], 'analysis_mode': item['analysis_mode'],
                    'strategy_version': STRATEGY_VERSION,
                    'tracking_cohort_id': runtime_config['tracking_cohort_id'],
                    'tracking_cohort_name': runtime_config['tracking_cohort_name'],
                    'market_catalog': snapshot.get('market_catalog'),
                }
                with _batch_ai_tasks_lock:
                    item['task_key'] = task_key
                    item['status'] = 'processing'
                    item['prepare_phase'] = ''
                    item['started_at'] = time.time()
                    item['heartbeat_at'] = time.time()
                future = ai_executor.submit(
                    run_ai_analysis_thread, item['match_id'], runtime_config['api_base'], runtime_config['api_key'],
                    runtime_config['model_name'], runtime_config['system_prompt'], context_str, ai_cache_file,
                    metadata, item['analysis_mode'], task_key, snapshot,
                )
                active[future] = item

            while active:
                done, _ = concurrent.futures.wait(active, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
                now = time.time()
                for future, item in list(active.items()):
                    if now - item.get('started_at', now) <= BATCH_MATCH_TIMEOUT_SECONDS:
                        continue
                    active.pop(future, None)
                    future.cancel()
                    with _batch_ai_tasks_lock:
                        item['status'] = 'timed_out'
                        item['error'] = f'单场任务超过 {BATCH_MATCH_TIMEOUT_SECONDS} 秒未完成，已释放批次。'
                        task = ai_tasks.get(item.get('task_key', ''), {})
                        if task:
                            task['status'] = 'timed_out'
                            task['error'] = item['error']
                    _persist_latest_batch_state(batch_id)
                for future in done:
                    item = active.pop(future, None)
                    if not item:
                        continue
                    try:
                        future.result()
                    except Exception as error:
                        task = {'status': 'failed', 'error': str(error)}
                    else:
                        task = ai_tasks.get(item.get('task_key', ''), {})
                    with _batch_ai_tasks_lock:
                        if task.get('status') == 'completed':
                            item['status'] = 'completed'
                        elif item.get('status') != 'timed_out':
                            item['status'] = 'failed'
                            item['error'] = task.get('error', 'AI 分析未完成，请重试该场。')
                    _persist_latest_batch_state(batch_id)

        with _batch_ai_tasks_lock:
            batch_ai_tasks[batch_id]['status'] = 'completed'
    except Exception as error:
        print(f"Batch AI analysis error for batch {batch_id}: {error}")
        with _batch_ai_tasks_lock:
            batch = batch_ai_tasks.get(batch_id)
            if batch:
                batch['status'] = 'failed'
    finally:
        _persist_latest_batch_state(batch_id)


def _watch_batch_timeouts(batch_id):
    """Keep the user-facing batch terminal even if a third-party worker freezes."""
    while True:
        time.sleep(2)
        changed = False
        with _batch_ai_tasks_lock:
            batch = batch_ai_tasks.get(batch_id)
            if not batch or batch.get('status') != 'processing':
                return
            now = time.time()
            for item in batch.get('items', []):
                if item.get('status') not in {'queued', 'preparing', 'validating', 'processing'}:
                    continue
                started_at = item.get('started_at', now)
                if now - started_at <= BATCH_MATCH_TIMEOUT_SECONDS:
                    continue
                item['status'] = 'timed_out'
                item['error'] = f'任务超过 {BATCH_MATCH_TIMEOUT_SECONDS} 秒未完成，已自动释放。'
                item['heartbeat_at'] = now
                task = ai_tasks.get(item.get('task_key', ''), {})
                if task:
                    task['status'] = 'timed_out'
                    task['error'] = item['error']
                changed = True
            if not any(item.get('status') in {'queued', 'preparing', 'validating', 'processing'} for item in batch.get('items', [])):
                batch['status'] = 'completed'
                changed = True
        if changed:
            _persist_latest_batch_state(batch_id)
        if changed and _batch_snapshot(batch_id).get('status') != 'processing':
            return


@app.route('/api/batch_ai_analysis', methods=['POST'])
def batch_ai_analysis():
    data = request.get_json(force=True, silent=True) or {}
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
        # A batch always starts from a fresh verified data snapshot. Reusing an
        # old report here can silently carry stale odds or incomplete details.
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
            target=_run_batch_ai_analysis_v2,
            args=(batch_id, runtime_config),
            daemon=True,
        )
        worker.start()
        watchdog = threading.Thread(target=_watch_batch_timeouts, args=(batch_id,), daemon=True)
        watchdog.start()
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


@app.route('/api/debug_ai_state')
def debug_ai_state():
    """Diagnostic endpoint: expose semaphore, thread counts, live ai_tasks, and key health."""
    import threading as _threading
    semaphore_value = _model_request_semaphore._value  # remaining slots
    active_tasks = {}
    for k, v in list(ai_tasks.items()):
        if not isinstance(v, dict):
            continue
        active_tasks[k] = {
            'status': v.get('status'),
            'phase': v.get('phase'),
            'status_list': v.get('status_list'),
            'analyst_statuses': [
                (out.get('status') if isinstance(out, dict) else 'null')
                for out in (v.get('analyst_outputs') or [])
            ],
            'started_at': v.get('started_at'),
            'heartbeat_at': v.get('heartbeat_at'),
        }
    # P2-7: API key health summary
    key_health = []
    try:
        now_mono = time.monotonic()
        with global_api_key_pool._lock:
            keys = list(global_api_key_pool._keys)
            cooldowns = dict(global_api_key_pool._cooldowns)
        for key_str in keys:
            cd_until = cooldowns.get(key_str, 0.0)
            remaining = max(0.0, round(cd_until - now_mono, 1))
            key_health.append({
                'key_suffix': '***' + key_str[-6:] if len(key_str) >= 6 else '***',
                'in_cooldown': remaining > 0,
                'cooldown_remaining_s': remaining,
            })
    except Exception as e:
        key_health = [{'error': str(e)}]
    return jsonify({
        'success': True,
        'semaphore_remaining_slots': semaphore_value,
        'semaphore_capacity': MODEL_REQUEST_CONCURRENCY,
        'semaphore_in_use': MODEL_REQUEST_CONCURRENCY - semaphore_value,
        'active_ai_tasks_count': len(active_tasks),
        'active_ai_tasks': active_tasks,
        'thread_count': _threading.active_count(),
        'key_health': key_health,
        'watchdog_timeout_minutes': TASK_HARD_TIMEOUT_SECONDS // 60,
    })


@app.route('/api/batch_ai_analysis_retry_cro', methods=['POST'])
def retry_batch_cro():
    payload = request.get_json(force=True, silent=True) or {}
    batch_id = str(payload.get('batch_id', '')).strip()
    match_id = str(payload.get('match_id', '')).strip()
    if not batch_id or not match_id:
        return jsonify({'success': False, 'error': '缺少批量任务或比赛标识。'}), 400
    ok, error, runtime_config = _load_ai_runtime_config()
    if not ok:
        return jsonify({'success': False, 'error': error}), 400
    with _batch_ai_tasks_lock:
        batch = batch_ai_tasks.get(batch_id)
        item = next((row for row in (batch or {}).get('items', []) if str(row.get('match_id')) == match_id), None)
        if not item:
            return jsonify({'success': False, 'error': '未找到对应比赛。'}), 404
        task_key = item.get('task_key', '')
        task = ai_tasks.get(task_key, {})
        reports = task.get('reports', [])
        if len(reports) != 3 or not all(has_final_output(report) for report in reports):
            return jsonify({'success': False, 'error': '三版本报告不可用，请重试整场分析。'}), 409
        item['status'] = 'processing'
        item.pop('error', None)
        item['retry_scope'] = 'cro'
        item['heartbeat_at'] = time.time()
        batch['status'] = 'processing'
    worker = threading.Thread(
        target=_run_batch_cro_retry,
        args=(batch_id, match_id, task_key, runtime_config),
        daemon=True,
    )
    worker.start()
    _persist_latest_batch_state(batch_id)
    return jsonify({'success': True, 'batch': _batch_snapshot(batch_id)})


@app.route('/api/batch_ai_analysis_retry_ai', methods=['POST'])
def retry_batch_ai():
    """P1-6: Retry only the AI analyst phase for one failed item (reuse existing context)."""
    payload = request.get_json(force=True, silent=True) or {}
    batch_id = str(payload.get('batch_id', '')).strip()
    match_id = str(payload.get('match_id', '')).strip()
    if not batch_id or not match_id:
        return jsonify({'success': False, 'error': '缺少批量任务或比赛标识。'}), 400
    ok, error, runtime_config = _load_ai_runtime_config()
    if not ok:
        return jsonify({'success': False, 'error': error}), 400
    with _batch_ai_tasks_lock:
        batch = batch_ai_tasks.get(batch_id)
        item = next((row for row in (batch or {}).get('items', []) if str(row.get('match_id')) == match_id), None)
        if not item:
            return jsonify({'success': False, 'error': '未找到对应比赛。'}), 404
        context_str = item.get('cached_context_str', '')
        snapshot = item.get('cached_snapshot')
        if not context_str:
            return jsonify({'success': False, 'error': '无缓存的分析上下文，请重新触发批量分析。'}), 409
        # Generate a fresh task key
        new_task_key = f"{batch_id}:{match_id}:{uuid.uuid4().hex}"
        item['task_key'] = new_task_key
        item['status'] = 'processing'
        item.pop('error', None)
        item.pop('retry_scope', None)
        item['heartbeat_at'] = time.time()
        batch['status'] = 'processing'
    ai_cache_file = os.path.join(CACHE_DIR, f"ai_analysis_{match_id}.json")
    metadata = {
        'match_id': match_id, 'home_team': item.get('home_team', ''), 'away_team': item.get('away_team', ''),
        'kickoff': item.get('kickoff', ''), 'competition': item.get('competition', ''),
        'fixture_date': item.get('fixture_date', ''), 'fixture_status': item.get('fixture_status', 1),
        'analysis_mode': item.get('analysis_mode', 'prematch'),
        'strategy_version': STRATEGY_VERSION,
        'tracking_cohort_id': runtime_config.get('tracking_cohort_id', ''),
        'tracking_cohort_name': runtime_config.get('tracking_cohort_name', ''),
        'market_catalog': (snapshot or {}).get('market_catalog'),
    }
    worker = threading.Thread(
        target=run_ai_analysis_thread,
        args=(match_id, runtime_config['api_base'], runtime_config['api_key'],
              runtime_config['model_name'], runtime_config['system_prompt'], context_str,
              ai_cache_file, metadata, item.get('analysis_mode', 'prematch'), new_task_key, snapshot),
        daemon=True,
    )
    worker.start()
    _persist_latest_batch_state(batch_id)
    return jsonify({'success': True, 'batch': _batch_snapshot(batch_id)})


@app.route('/api/batch_ai_analysis_cancel', methods=['POST'])
def cancel_batch():
    """强制取消一个进行中的批量任务（工作线程在下次心跳检测时自动退出）。"""
    payload = request.get_json(force=True, silent=True) or {}
    batch_id = str(payload.get('batch_id', '')).strip()
    if not batch_id:
        return jsonify({'success': False, 'error': '缺少 batch_id。'}), 400
    with _batch_ai_tasks_lock:
        batch = batch_ai_tasks.get(batch_id)
        if not batch:
            return jsonify({'success': False, 'error': '批次不存在。'}), 404
        if batch.get('status') not in {'processing'}:
            return jsonify({'success': False, 'error': f'批次当前状态为 {batch.get("status")}，无需取消。'}), 409
        batch['status'] = 'cancelled'
        cancelled_count = 0
        for item in batch.get('items', []):
            if item.get('status') in {'queued', 'preparing', 'validating', 'processing'}:
                item['status'] = 'cancelled'
                item['phase'] = '已手动取消'
                item['heartbeat_at'] = time.time()
                task_key = item.get('task_key', '')
                if task_key and task_key in ai_tasks and isinstance(ai_tasks[task_key], dict):
                    if ai_tasks[task_key].get('status') == 'processing':
                        ai_tasks[task_key]['status'] = 'cancelled'
                        ai_tasks[task_key]['error'] = '用户手动取消'
                cancelled_count += 1
    _persist_latest_batch_state(batch_id)
    print(f'[Cancel] 批次 {batch_id} 已手动取消，共取消 {cancelled_count} 个任务')
    return jsonify({'success': True, 'cancelled_count': cancelled_count, 'batch': _batch_snapshot(batch_id)})


@app.route('/api/batch_ai_analysis_cancel_all', methods=['POST'])
def cancel_all_batches():
    """核武器：强制取消所有进行中批量任务（彻底卡死时使用），并重置信号量。"""
    with _batch_ai_tasks_lock:
        total_cancelled = 0
        for batch_id, batch in batch_ai_tasks.items():
            if batch.get('status') != 'processing':
                continue
            batch['status'] = 'cancelled'
            for item in batch.get('items', []):
                if item.get('status') in {'queued', 'preparing', 'validating', 'processing'}:
                    item['status'] = 'cancelled'
                    item['phase'] = '已批量强制取消'
                    total_cancelled += 1
        for key, task in list(ai_tasks.items()):
            if isinstance(task, dict) and task.get('status') == 'processing':
                task['status'] = 'cancelled'
                task['error'] = '用户批量强制取消'
    try:
        _model_request_semaphore._value = MODEL_REQUEST_CONCURRENCY
    except Exception:
        pass
    print(f'[CancelAll] 强制取消所有批次，共 {total_cancelled} 项，信号量已重置')
    return jsonify({'success': True, 'total_cancelled': total_cancelled})

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


def _number(value):
    if value is None or value == '':
        return None
    match = re.search(r'-?\d+(?:\.\d+)?', str(value))
    return float(match.group()) if match else None


def _recent_goal_rates(matches, team_name, league_average):
    weighted_for = weighted_against = total_weight = 0.0
    for index, match in enumerate((matches or [])[:10]):
        score = str(match.get('score', '')).replace(':', '-')
        parts = score.split('-', 1)
        if len(parts) != 2:
            continue
        try:
            home_goals, away_goals = int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            continue
        weight = 0.88 ** index
        if match.get('home', '') == team_name:
            goals_for, goals_against = home_goals, away_goals
        elif match.get('away', '') == team_name:
            goals_for, goals_against = away_goals, home_goals
        else:
            continue
        weighted_for += goals_for * weight
        weighted_against += goals_against * weight
        total_weight += weight
    # ``league_average`` is per fixture, so each team's neutral scoring prior is half.
    team_average = league_average / 2.0
    denominator = total_weight + 4.0
    return (
        (weighted_for + team_average * 4.0) / denominator,
        (weighted_against + team_average * 4.0) / denominator,
    )


def _poisson_probability(value, mean):
    return math.exp(-mean) * (mean ** value) / math.factorial(value)


def _settlement_expectation(values):
    return sum(probability * (1 if margin > 0 else -1 if margin < 0 else 0) for margin, probability in values)


def _water_to_decimal(water):
    water = _number(water)
    return 1.0 + water if water is not None and 0.01 <= water <= 3.0 else None


def _fair_two_way_probabilities(first_water, second_water):
    first_decimal = _water_to_decimal(first_water)
    second_decimal = _water_to_decimal(second_water)
    if not first_decimal or not second_decimal:
        return None, None
    first_raw = 1.0 / first_decimal
    second_raw = 1.0 / second_decimal
    total = first_raw + second_raw
    return first_raw / total, second_raw / total


def _instant_market_catalog(details, baseline=None):
    """Return only executable current lines from this snapshot.

    Handicap lines use the normalized convention adopted by the tracking record:
    a negative number means that selected team gives goals, a positive number
    means it receives goals.  This lets the tracker reject an AI-invented line.
    """
    catalog = {
        'asian_handicap': {'home': [], 'away': [], 'quotes': []},
        'over_under': {'line': [], 'quotes': []},
    }
    for item in details.get('odds_index', []) if isinstance(details, dict) else []:
        handicap = item.get('handicap', {})
        home_line = _number(handicap.get('home_instant_line'))
        away_line = _number(handicap.get('away_instant_line'))
        if handicap.get('available', True) and home_line is not None and away_line is not None:
            catalog['asian_handicap']['home'].append(round(home_line, 2))
            catalog['asian_handicap']['away'].append(round(away_line, 2))
            home_water, away_water = (handicap.get('instant') or [None, None])[:2]
            home_probability, away_probability = _fair_two_way_probabilities(home_water, away_water)
            for team, line, water, probability in (
                ('home', home_line, home_water, home_probability),
                ('away', away_line, away_water, away_probability),
            ):
                decimal_odds = _water_to_decimal(water)
                if decimal_odds:
                    catalog['asian_handicap']['quotes'].append({
                        'company': item.get('company', ''), 'cid': str(item.get('cid', '')),
                        'team': team, 'line': round(line, 2), 'water': round(float(water), 3),
                        'decimal_odds': round(decimal_odds, 3),
                        'market_probability': round(probability, 5) if probability is not None else None,
                    })
        totals = item.get('over_under', {})
        total_line = _number(totals.get('instant_line'))
        if totals.get('available', True) and total_line is not None:
            catalog['over_under']['line'].append(round(total_line, 2))
            over_water, under_water = (totals.get('instant') or [None, None])[:2]
            over_probability, under_probability = _fair_two_way_probabilities(over_water, under_water)
            for side, water, probability in (
                ('over', over_water, over_probability),
                ('under', under_water, under_probability),
            ):
                decimal_odds = _water_to_decimal(water)
                if decimal_odds:
                    catalog['over_under']['quotes'].append({
                        'company': item.get('company', ''), 'cid': str(item.get('cid', '')),
                        'side': side, 'line': round(total_line, 2), 'water': round(float(water), 3),
                        'decimal_odds': round(decimal_odds, 3),
                        'market_probability': round(probability, 5) if probability is not None else None,
                    })
    for market in catalog.values():
        for key in ('home', 'away', 'line'):
            if key in market:
                market[key] = sorted(set(market[key]))
    if baseline:
        for quote in catalog['asian_handicap']['quotes']:
            value = baseline['handicap_expected_value'](quote['line'], quote['team'], quote['water'])
            quote['baseline_ev'] = round(value, 5) if value is not None else None
        for quote in catalog['over_under']['quotes']:
            value = baseline['total_expected_value'](quote['line'], quote['side'], quote['water'])
            quote['baseline_ev'] = round(value, 5) if value is not None else None
    return catalog


def _build_probability_baseline(details, home, away):
    """Return a transparent, league-shrunk scoring baseline without claiming xG."""
    standings = details.get('standings') if isinstance(details, dict) else []
    totals = [row.get('total', 0) or 0 for row in standings or []]
    goals_for = [row.get('goals_for', 0) or 0 for row in standings or []]
    total_matches = sum(totals) / 2
    league_average = sum(goals_for) / total_matches if total_matches else 2.6
    league_average = min(4.2, max(1.6, league_average))

    recent = details.get('recent_results', {}) if isinstance(details, dict) else {}
    home_for, home_against = _recent_goal_rates(recent.get('home', []), home, league_average)
    away_for, away_against = _recent_goal_rates(recent.get('away', []), away, league_average)
    home_mean = min(4.5, max(0.35, ((home_for + away_against) / 2) * 1.05))
    away_mean = min(4.5, max(0.35, ((away_for + home_against) / 2) * 0.95))

    score_probabilities = {}
    for home_goals in range(9):
        for away_goals in range(9):
            score_probabilities[(home_goals, away_goals)] = (
                _poisson_probability(home_goals, home_mean) * _poisson_probability(away_goals, away_mean)
            )
    normalizer = sum(score_probabilities.values())
    score_probabilities = {score: probability / normalizer for score, probability in score_probabilities.items()}

    def total_expectation(line, side):
        split_lines = (line - 0.25, line + 0.25) if round(line * 4) % 2 else (line,)
        expected = 0.0
        for split_line in split_lines:
            values = []
            for (home_goals, away_goals), probability in score_probabilities.items():
                margin = home_goals + away_goals - split_line
                values.append(((margin if side == 'over' else -margin), probability))
            expected += _settlement_expectation(values) / len(split_lines)
        return expected

    def handicap_expectation(team_line, team):
        split_lines = (team_line - 0.25, team_line + 0.25) if round(team_line * 4) % 2 else (team_line,)
        expected = 0.0
        for split_line in split_lines:
            values = []
            for (home_goals, away_goals), probability in score_probabilities.items():
                diff = home_goals - away_goals if team == 'home' else away_goals - home_goals
                values.append((diff + split_line, probability))
            expected += _settlement_expectation(values) / len(split_lines)
        return expected

    def settlement_ev(margins, water):
        water = _number(water)
        if water is None:
            return None
        return sum(
            probability * (water if margin > 0 else -1.0 if margin < 0 else 0.0)
            for margin, probability in margins
        )

    def total_expected_value(line, side, water):
        split_lines = (line - 0.25, line + 0.25) if round(line * 4) % 2 else (line,)
        expected = 0.0
        for split_line in split_lines:
            margins = [
                ((home_goals + away_goals - split_line) * (1 if side == 'over' else -1), probability)
                for (home_goals, away_goals), probability in score_probabilities.items()
            ]
            value = settlement_ev(margins, water)
            if value is None:
                return None
            expected += value / len(split_lines)
        return expected

    def handicap_expected_value(team_line, team, water):
        split_lines = (team_line - 0.25, team_line + 0.25) if round(team_line * 4) % 2 else (team_line,)
        expected = 0.0
        for split_line in split_lines:
            margins = [
                ((home_goals - away_goals if team == 'home' else away_goals - home_goals) + split_line, probability)
                for (home_goals, away_goals), probability in score_probabilities.items()
            ]
            value = settlement_ev(margins, water)
            if value is None:
                return None
            expected += value / len(split_lines)
        return expected

    return {
        'league_average': round(league_average, 2),
        'home_mean': round(home_mean, 2),
        'away_mean': round(away_mean, 2),
        'total_mean': round(home_mean + away_mean, 2),
        'total_expectation': total_expectation,
        'handicap_expectation': handicap_expectation,
        'total_expected_value': total_expected_value,
        'handicap_expected_value': handicap_expected_value,
    }


def _goal_phase_features(details):
    """Summarize timing and half/full data without inventing predictive weights."""
    goal_distribution = details.get('goal_distribution', {}) if isinstance(details, dict) else {}
    features = {}
    for side in ('home', 'away'):
        source = goal_distribution.get(side, {}).get('all', {}) if isinstance(goal_distribution, dict) else {}
        scored = source.get('scored', []) if isinstance(source, dict) else []
        conceded = source.get('conceded', []) if isinstance(source, dict) else []
        scored_counts = [int(_number(row[0] if isinstance(row, list) and row else row) or 0) for row in scored[:6]]
        conceded_counts = [int(_number(row[0] if isinstance(row, list) and row else row) or 0) for row in conceded[:6]]
        if len(scored_counts) == 6:
            features[f'{side}_early_scored_share'] = round(sum(scored_counts[:3]) / max(1, sum(scored_counts)), 3)
            features[f'{side}_late_scored_share'] = round(sum(scored_counts[3:]) / max(1, sum(scored_counts)), 3)
        if len(conceded_counts) == 6:
            features[f'{side}_late_conceded_share'] = round(sum(conceded_counts[3:]) / max(1, sum(conceded_counts)), 3)

    half_full = details.get('half_full_stats', []) if isinstance(details, dict) else []
    total = 0
    second_half_reversal = 0
    for item in half_full if isinstance(half_full, list) else []:
        count = sum(_number(item.get(key)) or 0 for key in ('home_win', 'draw', 'away_win'))
        total += count
        if str(item.get('label', '')) in {'胜负', '负胜', '平胜', '平负'}:
            second_half_reversal += count
    if total:
        features['half_full_change_rate'] = round(second_half_reversal / total, 3)
    return features


def _trend_summary(rows):
    """Extract observable path facts, never an inferred bookmaker intention."""
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    if not rows:
        return None
    newest, oldest = rows[0], rows[-1]
    newest_line = _number(newest.get('line'))
    oldest_line = _number(oldest.get('line'))
    newest_home = _number(newest.get('home'))
    oldest_home = _number(oldest.get('home'))
    newest_away = _number(newest.get('away'))
    oldest_away = _number(oldest.get('away'))
    return {
        'updates': len(rows),
        'line_change': round(newest_line - oldest_line, 3) if newest_line is not None and oldest_line is not None else None,
        'home_water_change': round(newest_home - oldest_home, 3) if newest_home is not None and oldest_home is not None else None,
        'away_water_change': round(newest_away - oldest_away, 3) if newest_away is not None and oldest_away is not None else None,
        'latest_time': str(newest.get('change_time', '')),
    }


def _trend_rows_for_analysis_mode(rows, analysis_mode):
    """Keep pre-match snapshots separate from in-play market history.

    For live mode the function returns only rows that are explicitly
    in-play (have a match minute or a live match_status).  Legacy rows
    with no explicit state are kept if they carry a score or a minute-
    like change_time.
    """
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    is_live = (analysis_mode == 'live')
    filtered = []
    for row in rows:
        has_explicit_state = 'match_minute' in row or 'match_status' in row
        minute = str(row.get('match_minute', '') or '').strip()
        try:
            status = int(row.get('match_status', 1))
        except (TypeError, ValueError):
            status = 1
        if has_explicit_state:
            if (is_live and minute):
                filtered.append(row)
                continue
            if (not is_live and not minute and status in PREMATCH_STATUSES):
                filtered.append(row)
                continue
            continue
        # Legacy rows (no explicit state)
        change_time = str(row.get('change_time', '') or '').strip()
        score = str(row.get('score', '') or '').strip()
        legacy_live_time = bool(re.fullmatch(r'(?:\d{1,3}\+?|中场|半场|HT)', change_time, re.IGNORECASE))
        if is_live:
            if legacy_live_time or score:
                filtered.append(row)
            continue
        if not score and not legacy_live_time:
            filtered.append(row)
    return filtered


def _normalize_handicap_trend_direction(rows):
    """Convert the API's opposing line sign to handicap applied to home."""
    normalized = []
    for row in rows:
        item = dict(row)
        line = _number(item.get('line'))
        if line is not None and item.get('source') == 'api_compact':
            signed_line = -line
            item['line'] = str(signed_line)
            item['line_zh'] = str(signed_line)
        normalized.append(item)
    return normalized


def build_match_prompt_context(match_id, home, away, analysis_mode='prematch', details=None, trend_quality=None):
    """Build one immutable match-specific prompt from a validated snapshot."""
    if details is None:
        details_cache_file = _detail_cache_path(match_id)
        if os.path.exists(details_cache_file):
            try:
                with open(details_cache_file, 'r', encoding='utf-8') as f:
                    details = json.load(f)
            except Exception:
                details = None

    if not details:
        try:
            details = get_complete_match_details(match_id, home, away)
            if not details.get('odds_index'):
                details['odds_index'] = get_real_odds(match_id)
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

    # 注入数据完整度信号，让 AI 知道哪些维度的数据缺失
    missing_dims = []
    if not details.get('odds_index'):
        missing_dims.append("赔率指数")
    if not details.get('standings'):
        missing_dims.append("联赛积分榜")
    if not details.get('goal_distribution') or not (details.get('goal_distribution', {}).get('home') or details.get('goal_distribution', {}).get('away')):
        missing_dims.append("进球时段分布")
    if not details.get('half_full_stats'):
        missing_dims.append("半全场统计")
    h2h_check = details.get('h2h', {})
    if not (h2h_check.get('matches') if isinstance(h2h_check, dict) else []):
        missing_dims.append("历史交锋")
    if missing_dims:
        context_lines.append(f"⚠️ 数据完整度警告: 以下维度缺失 → {', '.join(missing_dims)}。涉及缺失维度的分析结论应自动降低置信度，并在报告中标注[数据缺失]。")
    if isinstance(trend_quality, dict) and trend_quality.get('failures'):
        context_lines.append(
            f"⚠️ 变盘历史完整度警告: 已获取 {trend_quality.get('refreshed', 0)}/{trend_quality.get('required', 0)} 份让球/大小球历史。"
            "缺失公司的走势不得被推断或用旧数据替代；本场不得标注 high 置信度。"
        )

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
    standings = details.get('standings', [])
    # 构建积分榜球队名 → 排名的映射，用于标注近期战绩中对手的实力档次
    standings_rank_map = {}
    total_teams_in_league = 0
    if isinstance(standings, list) and standings:
        total_teams_in_league = len(standings)
        for row in standings:
            t_name = row.get('team_name', '')
            t_pos = row.get('position', 0)
            if t_name and t_pos:
                standings_rank_map[t_name] = t_pos

    def _annotate_opponent(match_record, our_team_name):
        """为近期战绩中的对手标注积分榜排名和强弱档次"""
        opponent = match_record.get('away', '') if match_record.get('home', '') == our_team_name else match_record.get('home', '')
        rank = standings_rank_map.get(opponent, 0)
        if rank and total_teams_in_league:
            top_cutoff = max(1, int(total_teams_in_league * 0.25))
            bottom_cutoff = int(total_teams_in_league * 0.75)
            if rank <= top_cutoff:
                return f"[#{rank}·强队]"
            elif rank > bottom_cutoff:
                return f"[#{rank}·弱队]"
            else:
                return f"[#{rank}]"
        return ""

    context_lines.append(f"主队近期战绩：")
    for idx, match in enumerate(recent_home[:10]):
        tag = _annotate_opponent(match, home)
        context_lines.append(f"- {match.get('date', '')} {match.get('home', '')} {match.get('score', '')} {match.get('away', '')} (赛事: {match.get('competition', '')}, 结果: {match.get('result', '')}) {tag}")
    context_lines.append(f"客队近期战绩：")
    for idx, match in enumerate(recent_away[:10]):
        tag = _annotate_opponent(match, away)
        context_lines.append(f"- {match.get('date', '')} {match.get('home', '')} {match.get('score', '')} {match.get('away', '')} (赛事: {match.get('competition', '')}, 结果: {match.get('result', '')}) {tag}")

    # 预计算近期战绩统计摘要，减少 AI 手动数数的幻觉风险
    def _form_summary(matches, team_name):
        """计算近N场的胜平负/进失球/面对强弱队战绩统计"""
        w, d, l, gf, ga = 0, 0, 0, 0, 0
        vs_strong_w, vs_strong_l, vs_weak_w, vs_weak_l = 0, 0, 0, 0
        for m in matches[:10]:
            result = m.get('result', '')
            if result == '胜':
                w += 1
            elif result == '平':
                d += 1
            elif result == '负':
                l += 1
            # 解析比分
            score = m.get('score', '')
            try:
                parts = score.replace(':', '-').split('-')
                h_goals, a_goals = int(parts[0].strip()), int(parts[1].strip())
                if m.get('home', '') == team_name:
                    gf += h_goals
                    ga += a_goals
                else:
                    gf += a_goals
                    ga += h_goals
            except:
                pass
            # 面对强弱队统计
            opponent = m.get('away', '') if m.get('home', '') == team_name else m.get('home', '')
            rank = standings_rank_map.get(opponent, 0)
            if rank and total_teams_in_league:
                top_cutoff = max(1, int(total_teams_in_league * 0.25))
                bottom_cutoff = int(total_teams_in_league * 0.75)
                if rank <= top_cutoff:
                    if result == '胜': vs_strong_w += 1
                    elif result == '负': vs_strong_l += 1
                elif rank > bottom_cutoff:
                    if result == '胜': vs_weak_w += 1
                    elif result == '负': vs_weak_l += 1
        n = w + d + l
        if n == 0:
            return None
        avg_gf = round(gf / n, 2)
        avg_ga = round(ga / n, 2)
        summary = f"近{n}场: {w}胜{d}平{l}负 | 场均进球{avg_gf} 场均失球{avg_ga}"
        if vs_strong_w or vs_strong_l:
            summary += f" | 对强队: {vs_strong_w}胜{vs_strong_l}负"
        if vs_weak_w or vs_weak_l:
            summary += f" | 对弱队: {vs_weak_w}胜{vs_weak_l}负"
        return summary

    home_form = _form_summary(recent_home, home)
    away_form = _form_summary(recent_away, away)
    if home_form:
        context_lines.append(f"📊 主队近期统计摘要: {home_form}")
    if away_form:
        context_lines.append(f"📊 客队近期统计摘要: {away_form}")

    context_lines.append(f"\n【五、 联赛积分榜对比】")
    standings = details.get('standings', [])
    if isinstance(standings, list) and standings:
        context_lines.append(f"- 联赛总队数: {len(standings)} | 强队线(前25%): 前{max(1, int(len(standings)*0.25))}名 | 弱队线(后25%): 后{max(1, int(len(standings)*0.25))}名")
        for row in standings:
            context_lines.append(f"- 排名 #{row.get('position', '-')} | 球队: {row.get('team_name', '未知')} | 赛: {row.get('total', 0)} | 胜/平/负: {row.get('won', 0)}/{row.get('draw', 0)}/{row.get('loss', 0)} | 得/失球: {row.get('goals_for', 0)}:{row.get('goals_against', 0)} | 积分: {row.get('points', 0)}")
    else:
        context_lines.append("- 暂无联赛积分榜数据")

    context_lines.append(f"\n【六、 进球时间段分布】")
    goal_dist = details.get('goal_distribution', {})
    if isinstance(goal_dist, dict) and (goal_dist.get('home') or goal_dist.get('away')):
        slots = ['0-15', '16-30', '31-45', '46-60', '61-75', '76-90']

        def format_goal_slots(all_data, key='scored'):
            """格式化 6 时段进/失球分布，key 可为 scored / conceded"""
            if not all_data or key not in all_data:
                return "暂无"
            raw = all_data.get(key, [])
            parts = []
            for idx, arr in enumerate(raw[:6]):
                val = arr[0] if isinstance(arr, list) and len(arr) > 0 else arr
                parts.append(f"{slots[idx]}分({val}球)")
            return " | ".join(parts)

        def format_first_goal_rate(all_data):
            """格式化先进球/先失球率（百分比）"""
            parts = []
            for key, label in [('first_scored', '先进球'), ('first_conceded', '先失球')]:
                raw = all_data.get(key, [])
                if raw:
                    total_pct = sum(arr[1] if isinstance(arr, list) and len(arr) > 1 else 0 for arr in raw[:6])
                    # 找出最密集的时段
                    max_idx = 0
                    max_val = 0
                    for idx, arr in enumerate(raw[:6]):
                        pct = arr[1] if isinstance(arr, list) and len(arr) > 1 else 0
                        if pct > max_val:
                            max_val = pct
                            max_idx = idx
                    if total_pct > 0:
                        parts.append(f"{label}率集中在{slots[max_idx]}分({max_val}%)")
            return " | ".join(parts) if parts else "暂无"

        for side, label in [('home', '主队'), ('away', '客队')]:
            side_data = goal_dist.get(side, {}).get('all', {})
            if side_data:
                context_lines.append(f"- {label}进球分布：{format_goal_slots(side_data, 'scored')}")
                context_lines.append(f"- {label}失球分布：{format_goal_slots(side_data, 'conceded')}")
                context_lines.append(f"- {label}先进球/先失球率：{format_first_goal_rate(side_data)}")
            else:
                context_lines.append(f"- {label}进失球分布：暂无数据")
    else:
        context_lines.append("- 暂无进球时间段分布数据")

    context_lines.append(f"\n【七、 半全场胜负统计 (近10场)】")
    half_full = details.get('half_full_stats', [])
    if isinstance(half_full, list) and half_full:
        half_full_strs = []
        for item in half_full:
            # total 字段可能为 0（数据源缺陷），用分拆字段求和作为实际频次
            hw = item.get('home_win', 0) or 0
            dr = item.get('draw', 0) or 0
            aw = item.get('away_win', 0) or 0
            actual_total = hw + dr + aw
            if actual_total > 0:
                half_full_strs.append(
                    f"{item.get('label', '')}(共{actual_total}次: 主胜{hw}/平{dr}/客胜{aw})"
                )
        if half_full_strs:
            context_lines.append(f"- 半全场分布: " + " | ".join(half_full_strs))
        else:
            context_lines.append("- 暂无非零频次的半全场历史数据")
    else:
        context_lines.append("- 暂无半全场胜负统计数据")

    phase_features = _goal_phase_features(details)
    if phase_features:
        context_lines.append("- 固定阶段特征: " + " | ".join(
            f"{key}={value:.1%}" for key, value in sorted(phase_features.items())
        ))

    odds_index = details.get('odds_index', [])
    baseline = _build_probability_baseline(details, home, away)
    context_lines.append(f"\n【八、 后端进球概率基线（固定算法，非 xG）】")
    context_lines.append(
        f"- 联赛场均总进球: {baseline['league_average']} | 主队进球均值: {baseline['home_mean']} | "
        f"客队进球均值: {baseline['away_mean']} | 本场总进球均值: {baseline['total_mean']}"
    )
    market_catalog = _instant_market_catalog(details, baseline)
    handicap_pairs = sorted({
        (round(home_line, 2), round(away_line, 2))
        for item in odds_index
        for home_line, away_line in [
            (_number(item.get('handicap', {}).get('home_instant_line')),
             _number(item.get('handicap', {}).get('away_instant_line')))
        ]
        if item.get('handicap', {}).get('available', True)
        and home_line is not None and away_line is not None
    })
    total_lines = sorted({
        line for item in odds_index
        if item.get('over_under', {}).get('available', True)
        and (line := _number(item.get('over_under', {}).get('instant_line'))) is not None
    })
    for home_line, away_line in handicap_pairs[:4]:
        home_score = baseline['handicap_expectation'](home_line, 'home')
        away_score = baseline['handicap_expectation'](away_line, 'away')
        context_lines.append(
            f"- 让球: 主队 {home_line:+g}={home_score:+.3f} | 客队 {away_line:+g}={away_score:+.3f}"
        )
    for line in total_lines[:4]:
        over_score = baseline['total_expectation'](line, 'over')
        under_score = baseline['total_expectation'](line, 'under')
        context_lines.append(
            f"- 大小球 {line}: 基线结算倾向 大={over_score:+.3f} | 小={under_score:+.3f}"
        )
    priced_quotes = market_catalog['asian_handicap']['quotes'] + market_catalog['over_under']['quotes']
    positive_quotes = [quote for quote in priced_quotes if (quote.get('baseline_ev') or 0) > 0]
    if positive_quotes:
        context_lines.append("- 可执行价格校验（仅下列报价的固定基线 EV 为正，其他方向必须 no_bet）:")
        for quote in sorted(positive_quotes, key=lambda item: item['baseline_ev'], reverse=True)[:8]:
            side = quote.get('team', quote.get('side', ''))
            context_lines.append(
                f"  * {quote['company']} | {side} {quote['line']:+g} | 水位 {quote['water']:.3f} "
                f"| 去水市场概率 {quote['market_probability']:.1%} | 固定基线 EV {quote['baseline_ev']:+.3f}"
            )
    else:
        context_lines.append("- 可执行价格校验: 没有任何即时报价在固定基线下为正 EV，本场必须 no_bet。")
    context_lines.append("- 该基线仅由近期实际比分与联赛均值推导；若与伤停或完整变盘证据冲突，必须降低置信度或 no_bet。若推荐方向与此基线相反，必须 no_bet。")
    context_lines.append(f"\n【赔率指数初始与即时变盘水位数据（按公司分组）】")
    for item in odds_index:
        company = item.get('company')
        # 欧指（胜平负）
        eu = item.get('europe', {})
        eu_init = eu.get('initial', [1.0, 1.0, 1.0])
        eu_inst = eu.get('instant', [1.0, 1.0, 1.0])
        # 亚洲让球盘
        h = item.get('handicap', {})
        h_init = h.get('initial', [1.0, 1.0])
        h_inst = h.get('instant', [1.0, 1.0])
        home_initial_line = _number(h.get('home_initial_line'))
        away_initial_line = _number(h.get('away_initial_line'))
        home_instant_line = _number(h.get('home_instant_line'))
        away_instant_line = _number(h.get('away_instant_line'))
        home_initial_label = f'{home_initial_line:+g}' if home_initial_line is not None else '缺失'
        away_initial_label = f'{away_initial_line:+g}' if away_initial_line is not None else '缺失'
        home_instant_label = f'{home_instant_line:+g}' if home_instant_line is not None else '缺失'
        away_instant_label = f'{away_instant_line:+g}' if away_instant_line is not None else '缺失'
        # 大小球
        ou = item.get('over_under', {})
        ou_init = ou.get('initial', [1.0, 1.0])
        ou_inst = ou.get('instant', [1.0, 1.0])
        context_lines.append(f"▸ {company}:")
        context_lines.append(f"  欧指: 初盘 主胜{eu_init[0]} 平{eu_init[1]} 客胜{eu_init[2]} → 即时 主胜{eu_inst[0]} 平{eu_inst[1]} 客胜{eu_inst[2]}")
        context_lines.append(
            f"  让球: 初盘 主队 {home_initial_label}/客队 {away_initial_label} "
            f"(主水{h_init[0]}/客水{h_init[1]}) → 即时 主队 {home_instant_label}/客队 {away_instant_label} "
            f"(主水{h_inst[0]}/客水{h_inst[1]})"
        )
        context_lines.append(f"  大小球: 初盘 {ou.get('initial_line', '')} (大{ou_init[0]}/小{ou_init[1]}) → 即时 {ou.get('instant_line', '')} (大{ou_inst[0]}/小{ou_inst[1]})")

    trend_companies, _ = _trend_companies_from_odds(odds_index)
    odds_by_cid = {
        str(item.get('cid')): item for item in odds_index
        if isinstance(item, dict) and item.get('cid') not in (None, '')
    }
    for company_name, cid in trend_companies:
        try:
            cached_trend = get_cached_odds_detail(match_id, cid)
            if cached_trend:
                all_tables = cached_trend
                if all_tables and len(all_tables) >= 3:
                    for type_val in _trend_markets_for_company(odds_by_cid.get(cid, {})):
                        market_name = TREND_MARKETS[type_val]
                        tbl_idx = int(type_val) - 1
                        rows = _trend_rows_for_analysis_mode(all_tables[tbl_idx], analysis_mode)
                        if type_val == '1':
                            rows = _normalize_handicap_trend_direction(rows)
                        t_name = f"{market_name} ({'Handicap' if type_val == '1' else 'Over/Under'})"
                        context_lines.append(f"- {company_name} {t_name} 变盘路径 (按时间倒序，最近 10 次变盘):")
                        if not rows:
                            context_lines.append("  (暂无该项变盘明细)")
                            continue
                        summary = _trend_summary(rows)
                        if summary:
                            facts = [f"变更 {summary['updates']} 次"]
                            if summary['line_change'] is not None:
                                facts.append(f"盘口变化 {summary['line_change']:+g}")
                            if summary['home_water_change'] is not None:
                                facts.append(
                                    f"{'主队水' if type_val == '1' else '大球水'}变化 "
                                    f"{summary['home_water_change']:+.3f}"
                                )
                            if summary['away_water_change'] is not None:
                                facts.append(
                                    f"{'客队水' if type_val == '1' else '小球水'}变化 "
                                    f"{summary['away_water_change']:+.3f}"
                                )
                            context_lines.append("  可观察路径摘要: " + " | ".join(facts))
                        for r in rows[:10]:
                            time_str = r.get('change_time', '')
                            sides = (
                                f"主队水 {r.get('home')} | 客队水 {r.get('away')}"
                                if type_val == '1'
                                else f"大球水 {r.get('home')} | 小球水 {r.get('away')}"
                            )
                            context_lines.append(f"  * 时间: {time_str} | 盘口 {r.get('line')} | {sides}")
        except Exception:
            pass

    context_str = "\n".join(context_lines)
    return True, "", context_str

# 三个版本的差异化审查视角，确保 CRO 聚合时能获得结构性对立面
_VERSION_PERSPECTIVES = [
    # 版本1：基本面主导（侧重战绩/伤停/战意驱动结论）
    "请针对以下赛事数据进行深度量化研判。本次研判要求以 Step 1 基本面为主驱动力（权重 60%），"
    "重点审计近期攻防效率、主力折损、强弱交手表现和战意驱动力，"
    "赔率盘口作为辅助校验维度。找出本场最具数学期望值（Value）的投资方向：\n\n{context_str}",
    # 版本2：市场基线审计（先计算价格，再判断是否存在偏差）
    "请针对以下赛事数据进行深度量化研判。本次研判要求以 Step 2 的去水市场概率为基线，"
    "逐项核验初盘与即时盘的可观察变化，并量化基本面对市场基线的支持或反对。"
    "不得猜测资金流、机构意图或诱盘；盘口变化不足以单独推出反向结论。"
    "只有存在可说明的概率增量时才推荐，否则明确写无量化优势：\n\n{context_str}",
    # 版本3：证伪审计（检验热门与反热门，不预设任何一方错误）
    "请针对以下赛事数据进行深度量化研判。本次研判要求以【证伪审计】视角切入：\n"
    "1. 同时检验市场热门方向、平局、受让方、小球的支持与反对证据，严禁预设热门必错；\n"
    "2. 平局、受让方或小球只有在相对去水市场概率存在明确优势，且有直接基本面证据时才可推荐；\n"
    "3. 若证据无法区分方向，明确写无量化优势，不要用冷门叙事填补结论。\n"
    "找出本场最具数学期望值（Value）的投资方向：\n\n{context_str}",
]


def _with_model_request_slot(function):
    """Limit simultaneous provider streams with key-pool aware concurrency."""
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        with _model_request_semaphore:
            now = time.monotonic()
            with _rate_limit_lock:
                global _model_last_model_request, _model_rate_limit_backoff
                min_interval = 0.1 if global_api_key_pool.key_count() > 1 else 0.5
                wait = min_interval - (now - _model_last_model_request)
                if wait > 0:
                    time.sleep(wait)
                _model_last_model_request = time.monotonic()
            return function(*args, **kwargs)
    return wrapped


def _read_error_body(r):
    """Extract error text from a response safely without triggering StreamConsumedError."""
    try:
        if hasattr(r, '_content') and r._content is not None:
            return (r.text or "")[:300]
    except Exception:
        pass
    try:
        err_parts = []
        for line in r.iter_lines(chunk_size=1):
            if line:
                err_parts.append(line.decode('utf-8', errors='ignore'))
            if len(err_parts) > 10:
                break
        text = "".join(err_parts).strip()
        if text:
            return text[:300]
    except Exception:
        pass
    return f"HTTP {getattr(r, 'status_code', 'Unknown')}"


class ModelNoContentError(Exception):
    """Raised when the model stream completed without delivering visible content."""
    pass


class ModelRateLimitError(Exception):
    """Raised when the provider returned HTTP 429."""
    def __init__(self, msg, original_text="", rate_limited_key=""):
        super().__init__(msg)
        self.original_text = original_text
        self.rate_limited_key = rate_limited_key


def _retry_model_operation(operation, has_visible_output):
    """Retry transient failures OR content-less responses up to max attempts with dynamic multi-key failover."""
    import requests

    retryable_errors = (
        TimeoutError,
        requests.exceptions.ConnectionError,
        requests.exceptions.ReadTimeout,
        requests.exceptions.SSLError,
    )
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            result = operation()
            if has_visible_output():
                return result
            print(f"Model returned only reasoning on attempt {attempt}/{max_attempts}")
            if attempt == max_attempts:
                raise ModelNoContentError(
                    f"模型连续 {max_attempts} 次仅返回思考过程，未生成可用正文"
                )
        except ModelRateLimitError as rle:
            has_other_keys = global_api_key_pool.key_count() > 1
            if has_other_keys:
                print(f"[429 Rate Limit] 触发多账号智能故障转移，轮换下一个健康 API Key (尝试 {attempt}/{max_attempts})...")
                time.sleep(0.3)
            else:
                with _rate_limit_lock:
                    global _model_rate_limit_backoff
                    _model_rate_limit_backoff = min(_model_rate_limit_backoff * 1.5, 30.0)
                    backoff = _model_rate_limit_backoff
                if attempt == max_attempts:
                    raise
                print(f"单 Key 被限流(429)，等待 {backoff:.0f}s 后第 {attempt}/{max_attempts} 次重试")
                time.sleep(backoff)
        except retryable_errors:
            if has_visible_output() or attempt == max_attempts:
                raise
            time.sleep(MODEL_REQUEST_RETRY_DELAY_SECONDS * attempt)


@_with_model_request_slot
def run_single_version(version_idx, match_id, api_base, api_key, model_name, system_prompt, context_str, task_key=None):
    global ai_tasks
    task_key = task_key or str(match_id)
    active_key = global_api_key_pool.get_key(preferred_key=api_key)
    headers = {
        "Authorization": f"Bearer {active_key}",
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
            {"role": "user", "content": _VERSION_PERSPECTIVES[version_idx].format(context_str=context_str)}
        ],
        "temperature": 0.25 + (version_idx * 0.15),
        "stream": True
    }
    if task_key in ai_tasks:
        ai_tasks[task_key].setdefault('analyst_inputs', [None, None, None])[version_idx] = {
            'version': version_idx + 1,
            'messages': payload['messages'],
            'temperature': payload['temperature'],
        }
        # Upgrade from 'waiting' → 'streaming' now that we have a semaphore slot.
        # Preserve started_at that was set during task initialisation.
        previous_out = ai_tasks[task_key].setdefault('analyst_outputs', [None, None, None])[version_idx] or {}
        ai_tasks[task_key]['analyst_outputs'][version_idx] = {
            'version': version_idx + 1,
            'status': 'streaming',
            'reasoning': '',
            'content': '',
            'started_at': previous_out.get('started_at', time.time()),
            'first_event_at': None,
            'first_visible_content_at': None,
            'reasoning_received': False,
            'reasoning_len': previous_out.get('reasoning_len', 0),
        }
        print(f"[AI Thread] match={match_id} 研判{version_idx+1} 已获槽位，开始向模型发送请求...")
    
    import requests
    r = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=(MODEL_CONNECT_TIMEOUT_SECONDS, MODEL_STREAM_READ_TIMEOUT_SECONDS),
        stream=True,
    )
    if r.status_code == 429:
        err_text = _read_error_body(r)
        r.close()
        global_api_key_pool.report_rate_limit(active_key, cooldown_seconds=25.0)
        raise ModelRateLimitError(
            f"大模型接口请求被限流 (HTTP 429): {err_text}",
            original_text=err_text,
            rate_limited_key=active_key,
        )
    if r.status_code != 200:
        err_text = _read_error_body(r)
        r.close()
        raise Exception(f"大模型接口请求失败: HTTP {r.status_code} - {err_text}")
        
    global_api_key_pool.report_success(active_key)
    ai_output = ""
    reasoning_omitted = False
    content_output = ""
    # stream_deadline is a rolling window: any received token resets it to now+120s.
    # This prevents thinking models from timing out mid-reasoning while still
    # catching genuinely stalled connections (no token for 120 consecutive seconds).
    _token_idle_window = 120
    stream_start_mono = time.monotonic()
    stream_deadline = stream_start_mono + _token_idle_window
    hard_deadline = stream_start_mono + MAX_SINGLE_VERSION_STREAM_SECONDS
    
    for line in r.iter_lines(chunk_size=1):
        now_mono = time.monotonic()
        if now_mono > hard_deadline:
            raise TimeoutError(f'研判单次流处理已达硬上限耗时 ({MAX_SINGLE_VERSION_STREAM_SECONDS}s)，强行熔断重试')
        if now_mono > stream_deadline:
            raise TimeoutError(f'Analyst stream idle for {_token_idle_window}s without any token')
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
                output_state = ai_tasks.get(task_key, {}).get('analyst_outputs', [None, None, None])[version_idx]
                if isinstance(output_state, dict):
                    event_time = time.time()
                    output_state['first_event_at'] = output_state.get('first_event_at') or event_time
                    output_state['last_event_at'] = event_time
                
                if reasoning:
                    reasoning_omitted = True
                    # Roll the idle window forward on every reasoning token.
                    stream_deadline = now_mono + _token_idle_window
                    if isinstance(output_state, dict):
                        output_state['reasoning_received'] = True
                        curr_r_len = output_state.get('reasoning_len', 0) + len(reasoning)
                        output_state['reasoning_len'] = curr_r_len
                        # 防死循环熔断：思考字数已超上限且仍未吐出正文，或者总思考超过 2 万字
                        if (curr_r_len > MAX_REASONING_CHARACTERS and not content_output) or curr_r_len > 25000:
                            print(f"[Circuit Breaker] 研判{version_idx+1} 思考字数达到 {curr_r_len} 字，判定为思考死循环，强行中断并触重试！")
                            raise TimeoutError(f'模型思考字数已达熔断上限 ({curr_r_len} > {MAX_REASONING_CHARACTERS}字)，判定为思考死循环，已强行中断重试')
                if content:
                    # Roll the idle window forward on every content token.
                    stream_deadline = now_mono + _token_idle_window
                    ai_output += content
                    content_output += content
                    if isinstance(output_state, dict):
                        output_state['first_visible_content_at'] = output_state.get('first_visible_content_at') or event_time
                        output_state['content'] = content_output
                        
                if ai_tasks.get(task_key, {}).get('status') == 'processing':
                    ai_tasks[task_key]['reports'][version_idx] = ai_output
            except Exception:
                pass
                
    if task_key in ai_tasks:
        previous_output = ai_tasks[task_key].get('analyst_outputs', [None, None, None])[version_idx] or {}
        ai_tasks[task_key].setdefault('analyst_outputs', [None, None, None])[version_idx] = {
            'version': version_idx + 1,
            'status': 'completed',
            'reasoning': '',
            'reasoning_omitted': reasoning_omitted,
            'content': content_output,
            'completed_at': time.time(),
            'first_event_at': previous_output.get('first_event_at'),
            'first_visible_content_at': previous_output.get('first_visible_content_at'),
            'reasoning_received': previous_output.get('reasoning_received', False),
        }
        
    return ai_output

@_with_model_request_slot
def run_cro_aggregation(match_id, api_base, api_key, model_name, combined_reports, task_key=None):
    global ai_tasks
    task_key = task_key or str(match_id)
    active_key = global_api_key_pool.get_key(preferred_key=api_key)
    headers = {
        "Authorization": f"Bearer {active_key}",
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
    if task_key in ai_tasks:
        ai_tasks[task_key]['cro_input'] = {
            'messages': payload['messages'],
            'temperature': payload['temperature'],
        }
        ai_tasks[task_key]['cro_output'] = {
            'status': 'streaming',
            'reasoning': '',
            'content': '',
            'started_at': time.time(),
            'first_event_at': None,
            'first_visible_content_at': None,
            'reasoning_received': False,
        }
    import requests
    r = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=(MODEL_CONNECT_TIMEOUT_SECONDS, MODEL_STREAM_READ_TIMEOUT_SECONDS),
        stream=True,
    )
    if r.status_code == 429:
        err_text = _read_error_body(r)
        r.close()
        global_api_key_pool.report_rate_limit(active_key, cooldown_seconds=25.0)
        raise ModelRateLimitError(
            f"收敛层大模型接口请求被限流 (HTTP 429): {err_text}",
            original_text=err_text,
            rate_limited_key=active_key,
        )
    if r.status_code != 200:
        err_text = _read_error_body(r)
        r.close()
        raise Exception(f"收敛层大模型接口请求失败: HTTP {r.status_code} - {err_text}")
        
    global_api_key_pool.report_success(active_key)
    ai_output = ""
    reasoning_omitted = False
    content_output = ""
    # CRO 流处理同样采用滚动 idle 窗口：每个 token 都将超时窗口延长。
    # 这防止慢思考模型被误杀，并用绝对硬上限（CRO_TIMEOUT_SECONDS * 3）屈杀真正卡死的情况。
    _cro_idle_window = CRO_TIMEOUT_SECONDS  # 120s 无 token 触发超时
    _cro_hard_limit = CRO_TIMEOUT_SECONDS * 3  # 360s 绝对硬上限
    cro_stream_start = time.monotonic()
    stream_deadline = cro_stream_start + _cro_idle_window
    hard_deadline = cro_stream_start + _cro_hard_limit
    for line in r.iter_lines(chunk_size=1):
        now_mono = time.monotonic()
        if now_mono > hard_deadline:
            raise TimeoutError(f'CRO 流处理已达绝对硬上限 ({_cro_hard_limit}s)，强行点火重试')
        if now_mono > stream_deadline:
            raise TimeoutError(f'CRO stream idle for {_cro_idle_window}s without any token')
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
                output_state = ai_tasks.get(task_key, {}).get('cro_output')
                if isinstance(output_state, dict):
                    event_time = time.time()
                    output_state['first_event_at'] = output_state.get('first_event_at') or event_time
                    output_state['last_event_at'] = event_time
                
                if reasoning:
                    reasoning_omitted = True
                    # 滚动窗口延长：每收到一个思考 token 就重置计时
                    stream_deadline = now_mono + _cro_idle_window
                    if isinstance(output_state, dict):
                        output_state['reasoning_received'] = True
                if content:
                    ai_output += content
                    content_output += content
                    # 滚动窗口延长：每收到一个正文 token 就重置计时
                    stream_deadline = now_mono + _cro_idle_window
                    if isinstance(output_state, dict):
                        output_state['first_visible_content_at'] = output_state.get('first_visible_content_at') or event_time
                        output_state['content'] = content_output
                        
                if ai_tasks.get(task_key, {}).get('status') == 'processing':
                    ai_tasks[task_key]['final_ticket'] = ai_output
            except Exception:
                pass
                
    if task_key in ai_tasks:
        previous_output = ai_tasks[task_key].get('cro_output') or {}
        ai_tasks[task_key]['cro_output'] = {
            'status': 'completed',
            'reasoning': '',
            'reasoning_omitted': reasoning_omitted,
            'content': content_output,
            'completed_at': time.time(),
            'first_event_at': previous_output.get('first_event_at'),
            'first_visible_content_at': previous_output.get('first_visible_content_at'),
            'reasoning_received': previous_output.get('reasoning_received', False),
        }
        
    return ai_output


def _cro_market_anchor_context(context_str):
    for marker in ('【八、 后端进球概率基线', '【赔率指数'):
        marker_index = context_str.find(marker)
        if marker_index >= 0:
            return context_str[marker_index:]
    return '(赔率与基线数据不可用)'


def run_ai_analysis_thread(match_id, api_base, api_key, model_name, system_prompt, context_str, ai_cache_file, prediction_metadata, analysis_mode, task_key=None, snapshot=None):
    global ai_tasks
    task_key = task_key or str(match_id)
    try:
        _now = time.time()
        # Pre-fill analyst_outputs with 'waiting' so the frontend immediately
        # shows "等待中" instead of "排队" while sub-threads queue for the semaphore.
        ai_tasks[task_key] = {
            'status': 'processing', 
            'reports': ['', '', ''],
            'status_list': ['processing', 'processing', 'processing'],
            'final_ticket': '',
            'analyst_inputs': [None, None, None],
            'analyst_outputs': [
                {'version': i + 1, 'status': 'waiting', 'reasoning': '', 'content': '',
                 'started_at': _now, 'first_event_at': None, 'first_visible_content_at': None,
                 'reasoning_received': False, 'reasoning_len': 0}
                for i in range(3)
            ],
            'cro_input': None,
            'cro_output': None,
            'started_at': _now,
            'heartbeat_at': _now,
            'snapshot_hash': (snapshot or {}).get('hash', ''),
            'analysis_input': context_str,
            'trace_id': uuid.uuid4().hex,
        }
        print(f"[AI Thread] match={match_id} task={task_key[:24]}... 已初始化，开始并行提交三路研判")
        
        def run_version_with_retry(version_idx):
            print(f"[AI Thread] match={match_id} 研判{version_idx+1} 线程已启动，等待模型请求槽位...")
            result = _retry_model_operation(
                lambda: run_single_version(
                    version_idx, match_id, api_base, api_key, model_name,
                    system_prompt, context_str, task_key,
                ),
                lambda: bool(extract_final_output(ai_tasks.get(task_key, {}).get('reports', ['', '', ''])[version_idx])),
            )
            print(f"[AI Thread] match={match_id} 研判{version_idx+1} 完成")
            return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(
                    run_version_with_retry,
                    i,
                ): i for i in range(3)
            }
            sub_errors = []
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    future.result()
                    ai_tasks[task_key]['status_list'][idx] = 'completed'
                    ai_tasks[task_key]['heartbeat_at'] = time.time()
                except Exception as sub_e:
                    print(f"Sub-thread {idx} failed for match {match_id}: {sub_e}")
                    sub_errors.append(str(sub_e))
                    ai_tasks[task_key]['status_list'][idx] = 'failed'
                    ai_tasks[task_key]['reports'][idx] = f"【该版本研判生成出错: {str(sub_e)}】"
                    previous_output = ai_tasks[task_key].get('analyst_outputs', [None, None, None])[idx] or {}
                    ai_tasks[task_key].setdefault('analyst_outputs', [None, None, None])[idx] = {
                        'version': idx + 1,
                        'status': 'failed',
                        'reasoning': '',
                        'content': previous_output.get('content', ''),
                        'error': str(sub_e),
                        'completed_at': time.time(),
                        'first_event_at': previous_output.get('first_event_at'),
                        'first_visible_content_at': previous_output.get('first_visible_content_at'),
                        'reasoning_received': previous_output.get('reasoning_received', False),
                    }
                    ai_tasks[task_key]['heartbeat_at'] = time.time()
        
        # 判断是否全都失败
        st_list = ai_tasks[task_key]['status_list']
        if all(s == 'failed' for s in st_list):
            detail = sub_errors[0] if sub_errors else '未返回可用错误信息'
            raise Exception(f"三个版本的 AI 研判全部请求失败：{detail}")

        incomplete_reports = [idx + 1 for idx, report in enumerate(ai_tasks[task_key]['reports']) if not has_final_output(report)]
        if incomplete_reports:
            raise Exception(f"第 {', '.join(map(str, incomplete_reports))} 份研判只返回了思考过程，未生成正文。请重新生成。")
            
        # 并发执行完毕，开始构建聚合上下文
        # The CRO judges each analyst's conclusion, not its raw reasoning trace.
        # Keeping traces out of this prompt cuts a large redundant model input while
        # preserving them unchanged in the UI and analysis cache.
        reports_list = [extract_final_output(ai_tasks[task_key]['reports'][i]) for i in range(3)]
        combined_reports = f"报告1:\n{reports_list[0]}\n\n报告2:\n{reports_list[1]}\n\n报告3:\n{reports_list[2]}"
        # 注入精简赔率锚点，让 CRO 能独立校验分析师对赔率变盘的表述是否准确
        combined_reports += (
            "\n\n【固定概率基线与原始赔率锚点（供 CRO 交叉校验）】\n"
            + _cro_market_anchor_context(context_str)
        )
        
        # 串行调用大模型进行收敛层聚合
        ai_tasks[task_key]['phase'] = 'cro'
        ai_tasks[task_key]['heartbeat_at'] = time.time()
        final_ticket = _retry_model_operation(
            lambda: run_cro_aggregation(match_id, api_base, api_key, model_name, combined_reports, task_key),
            lambda: bool(extract_final_output(ai_tasks.get(task_key, {}).get('final_ticket', ''))),
        )
        if not has_final_output(final_ticket):
            raise Exception("CRO 只返回了思考过程，未生成最终执行单。请重新生成。")
        if ai_tasks.get(task_key, {}).get('status') != 'processing':
            return
        ai_tasks[task_key]['final_ticket'] = final_ticket
        
        final_reports = ai_tasks[task_key]['reports']
        with open(ai_cache_file, 'w', encoding='utf-8') as cache_f:
            json.dump({
                'analysis_version': AI_ANALYSIS_CACHE_VERSION,
                'analysis_mode': analysis_mode,
                'reports': final_reports,
                'final_ticket': final_ticket,
                'analysis_input': context_str,
                'analyst_inputs': ai_tasks[task_key].get('analyst_inputs', []),
                'cro_input': ai_tasks[task_key].get('cro_input'),
                'trace_id': ai_tasks[task_key].get('trace_id'),
                'trace_path': _analysis_trace_path(match_id, ai_tasks[task_key].get('trace_id')),
                'snapshot_hash': (snapshot or {}).get('hash', ''),
                'market_snapshot_hash': (snapshot or {}).get('market_hash', ''),
                'snapshot_captured_at': (snapshot or {}).get('captured_at', ''),
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
            
        ai_tasks[task_key]['status'] = 'completed'
        ai_tasks[task_key]['heartbeat_at'] = time.time()
    except Exception as e:
        print(f"Background AI Thread error for match {match_id}: {e}")
        existing = ai_tasks.get(task_key, {})
        if existing.get('phase') == 'cro' and isinstance(existing.get('cro_output'), dict):
            if existing['cro_output'].get('status') == 'streaming':
                existing['cro_output'] = {
                    **existing['cro_output'],
                    'status': 'failed',
                    'error': str(e),
                    'completed_at': time.time(),
                }
        if existing.get('status') not in {'timed_out', 'cancelled'}:
            ai_tasks[task_key] = {
                'status': 'failed',
                'error': str(e),
                'reports': existing.get('reports', ['', '', '']),
                'status_list': existing.get('status_list', ['failed', 'failed', 'failed']),
                'final_ticket': existing.get('final_ticket', ''),
                'phase': existing.get('phase', 'ai'),
                'heartbeat_at': time.time(),
                'started_at': existing.get('started_at'),
                'snapshot_hash': existing.get('snapshot_hash', ''),
                'analysis_input': existing.get('analysis_input', context_str),
                'analyst_inputs': existing.get('analyst_inputs', [None, None, None]),
                'analyst_outputs': existing.get('analyst_outputs', [None, None, None]),
                'cro_input': existing.get('cro_input'),
                'cro_output': existing.get('cro_output'),
                'trace_id': existing.get('trace_id'),
            }
    finally:
        try:
            _persist_analysis_trace(match_id, task_key, model_name, analysis_mode)
        except Exception as trace_error:
            print(f"Analysis trace persistence failed for match {match_id}: {trace_error}")

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
        
    # 1. Read the fixed strategy and its active statistics cohort together.
    config_ok, config_error, runtime_config = _load_ai_runtime_config()
    if not config_ok:
        return jsonify({'success': False, 'error': config_error})
    api_key = runtime_config['api_key']
    api_base = runtime_config['api_base']
    model_name = runtime_config['model_name']
    system_prompt = runtime_config['system_prompt']
        
    ai_cache_file = os.path.join(CACHE_DIR, f'ai_analysis_{match_id}.json')
    
    # 2. 如果非强刷，优先命中缓存
    if not force:
        cache_state = 'miss'
        if os.path.exists(ai_cache_file):
            try:
                with open(ai_cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                if _is_reusable_analysis_cache(cache_data, analysis_mode):
                    return jsonify({
                        'success': True, 
                        'status': 'completed', 
                        'cached': True, 
                        'cache_state': 'fresh',
                        'reports': cache_data['reports'],
                        'final_ticket': cache_data.get('final_ticket', '')
                    })
                cache_state = 'stale'
                os.remove(ai_cache_file)
            except Exception:
                cache_state = 'invalid'
        return jsonify({
            'success': True, 
            'status': 'idle', 
            'cached': False, 
            'cache_state': cache_state,
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
            
    # 4. Single analysis follows the same data gate as batch analysis.
    success, err_msg, details, snapshot = _prepare_analysis_snapshot(
        match_id, home, away, force_refresh=True
    )
    if not success:
        return jsonify({'success': False, 'error': err_msg})
    trends_ok, trend_error, trend_quality = _refresh_required_trend_history(
        match_id, details.get('odds_index', []), analysis_mode
    )
    if not trends_ok:
        return jsonify({'success': False, 'error': trend_error})
    snapshot['trend_quality'] = trend_quality
    snapshot['market_catalog'] = _instant_market_catalog(
        details, _build_probability_baseline(details, home, away)
    )
    success, err_msg, context_str = build_match_prompt_context(
        match_id, home, away, analysis_mode, details=details, trend_quality=trend_quality
    )
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
                'strategy_version': STRATEGY_VERSION,
                'tracking_cohort_id': runtime_config['tracking_cohort_id'],
                'tracking_cohort_name': runtime_config['tracking_cohort_name'],
                'market_catalog': snapshot['market_catalog'],
            },
            analysis_mode,
            None,
            snapshot,
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
    _, matches_by_id = load_match_store()
    match_meta = matches_by_id.get(str(match_id), {})
    try:
        status_mode = 'live' if int(match_meta.get('status', 1)) in LIVE_STATUSES else 'prematch'
    except (TypeError, ValueError):
        status_mode = 'prematch'
    
    # 优先检测有无物理缓存生成
    if os.path.exists(ai_cache_file):
        try:
            with open(ai_cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            if _is_reusable_analysis_cache(cache_data, status_mode):
                return jsonify({
                    'success': True, 
                    'status': 'completed', 
                    'reports': cache_data['reports'],
                    'final_ticket': cache_data.get('final_ticket', ''),
                    'status_list': ['completed', 'completed', 'completed']
                })
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
    
    # 缓存和内存都找不到时，回退到 prediction_history.sqlite3 读取历史报告
    detail = None
    try:
        with closing(sqlite3.connect(PREDICTION_DB_FILE)) as conn:
            row = conn.execute(
                'SELECT final_report, prediction_json FROM predictions WHERE match_id = ? ORDER BY id DESC LIMIT 1',
                (match_id,)
            ).fetchone()
        if row:
            detail = {
                'final_report': row[0],
                'prediction': json.loads(row[1]) if row[1] else None,
            }
    except Exception:
        detail = None
    
    if detail:
        report = detail.get('final_report', '') or ''
        return jsonify({
            'success': True,
            'status': 'completed',
            'reports': [report, report, report],
            'final_ticket': report,
            'status_list': ['completed', 'completed', 'completed'],
            'cached': True,
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
        cohorts, active_cohort_id = _tracking_cohort_state(_read_config_file())
        requested_cohort_id = request.args.get('cohort_id', '').strip()
        selected_cohort_id = requested_cohort_id or active_cohort_id
        data = prediction_summary(
            PREDICTION_DB_FILE, cohort_id=selected_cohort_id,
            cohort_definitions=cohorts,
        )
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


@app.route('/api/send_wechat_message', methods=['POST'])
def send_wechat_message():
    """Send a notification to user via configured channel."""
    import requests
    data = request.get_json(force=True, silent=True) or {}
    message = str(data.get('message', '')).strip()
    if not message:
        return jsonify({'success': False, 'error': '消息内容为空'})

    # 通过 Hermes chat API 推送；如果不可用则静默失败
    try:
        api_key = os.environ.get('API_SERVER_KEY', 'my-secret-token-2026')
        # Hermes local chat relay
        resp = requests.post(
            'http://127.0.0.1:9119/api/v1/messages',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'X-Channel': 'wechat',
            },
            json={'text': message},
            timeout=10,
        )
        if resp.status_code < 400:
            return jsonify({'success': True, 'via': 'hermes'})
    except Exception:
        pass

    return jsonify({'success': False, 'error': '微信推送未配置或网关不可达；但不影响核心功能'})


if __name__ == '__main__':
    # Run locally or on server port 5000, listening on all interfaces
    start_refresh_scheduler()
    _start_task_watchdog()
    app.run(host='0.0.0.0', port=5000, use_reloader=False, threaded=True)
