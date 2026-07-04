# -*- coding: utf-8 -*-
import urllib.request
import urllib.error
import http.cookiejar
import subprocess
import json
import os
import re
import shutil
import zlib
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import datetime
import time

URL_GUIDE = 'https://www.leisu.com/guide'
URL_LIVE = 'https://live.leisu.com/'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

MAJOR_COMPETITIONS = [
    "英超", "西甲", "意甲", "德甲", "法甲", "中超", "足协杯",
    "欧冠", "欧联", "欧协", "欧国联", "欧洲杯", "世预赛", "欧预赛",
    "美洲杯", "金杯赛", "亚洲杯", "非洲杯", "世界杯", "联合会杯",
    "日职", "日联杯", "韩职", "韩足总", "澳超", "美职",
    "荷甲", "荷杯", "葡超", "葡联杯", "巴甲", "阿甲", "俄超",
    "英冠", "德乙", "意乙", "法乙", "日乙", "韩乙",
    "沙特超", "土超", "苏超", "比甲", "瑞士超", "墨超",
    "解放者杯", "南美杯", "亚冠", "亚协杯", "世俱杯", "奥运会",
    "国际友谊", "国家队", "足总杯", "国王杯", "意大利杯", "德国杯",
    "法国杯", "英联杯", "意超杯", "西超杯", "社区盾"
]

def get_weekday_cn(date_obj):
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return weekdays[date_obj.weekday()]

def find_node_executable():
    path = shutil.which("node")
    if path:
        return path
    if os.path.exists(r"D:\WorkApp\nodejs\node.exe"):
        return r"D:\WorkApp\nodejs\node.exe"
    if os.path.exists(r"C:\Program Files\nodejs\node.exe"):
        return r"C:\Program Files\nodejs\node.exe"
    return "node"

NODE_PATH = find_node_executable()

def solve_waf_via_node(html, url, user_agent):
    script_path = os.path.join(os.path.dirname(__file__), 'waf_solver.js')
    
    process = subprocess.Popen(
        [NODE_PATH, script_path, url, user_agent],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8'
    )
    stdout, stderr = process.communicate(input=html)
    if stderr.strip():
        print(f"[Node Stderr] {stderr.strip()}")
    if process.returncode != 0:
        print(f"[Node Error] {stderr}")
        return None
    try:
        res = json.loads(stdout.strip())
        if res.get('success'):
            return res.get('cookie')
    except Exception as e:
        print(f"[JSON Parse Error] {e}. Output was: {stdout}")
    return None

def fetch_html_with_bypass(url, domain, opener, cj, headers=None):
    use_headers = headers if headers is not None else HEADERS
    req = urllib.request.Request(url, headers=use_headers)
    try:
        with opener.open(req, timeout=10) as response:
            content_bytes = response.read()
            if response.info().get('Content-Encoding') == 'gzip':
                content_bytes = zlib.decompress(content_bytes, 15 + 32)
            html = content_bytes.decode('utf-8')
            real_url = response.geturl()
            real_domain = urlparse(real_url).netloc
            
        print(f"fetch_html_with_bypass fetched URL {url}. Length: {len(html)}")
        
        is_waf = False
        if 'aliyunwaf' in html:
            is_waf = True
        elif '<textarea id="renderData"' in html:
            if 'l1' in html and 'l2' in html:
                is_waf = True
                
        if is_waf:
            print(f"WAF detected on {url}, solving...")
            user_agent = use_headers.get('User-Agent', '')
            cookie_val = solve_waf_via_node(html, real_url, user_agent)
            print(f"WAF solve output cookie: {cookie_val}")
            if not cookie_val:
                raise Exception(f"Failed to solve WAF challenge for {real_url}")
                
            # Set the WAF bypass cookie for the domain
            waf_cookie = http.cookiejar.Cookie(
                version=0, name='acw_sc__v2', value=cookie_val,
                port=None, port_specified=False,
                domain=real_domain, domain_specified=True, domain_initial_dot=real_domain.startswith('.'),
                path='/', path_specified=True,
                secure=False, expires=None, discard=True, comment=None, comment_url=None, rest={}, rfc2109=False
            )
            cj.set_cookie(waf_cookie)
            
            # Request again
            req2 = urllib.request.Request(real_url, headers=use_headers)
            with opener.open(req2, timeout=10) as response2:
                content_bytes2 = response2.read()
                if response2.info().get('Content-Encoding') == 'gzip':
                    content_bytes2 = zlib.decompress(content_bytes2, 15 + 32)
                html = content_bytes2.decode('utf-8')
                
        return html
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        raise e

def scrape_matches():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    
    # 1. Parse Featured Recommended Matches from www.leisu.com/guide
    print("Fetching featured recommended matches from www.leisu.com/guide...")
    guide_matches = {}
    try:
        html_guide = fetch_html_with_bypass(URL_GUIDE, 'www.leisu.com', opener, cj)
        soup_guide = BeautifulSoup(html_guide, 'html.parser')
        
        date_groups = soup_guide.find_all('div', class_='guide-match-date')
        for date_group in date_groups:
            date_el = date_group.find('div', class_='match-date')
            if not date_el:
                continue
            date_str = date_el.text.strip()
            
            match_lists = date_group.find_all('div', class_='guide-match-list')
            for ml in match_lists:
                match_card = ml.find('div', class_='match-list')
                if not match_card:
                    continue
                    
                # Extract ID
                match_id = ""
                live_news_div = match_card.find('div', class_='match-live-news')
                if live_news_div:
                    first_link = live_news_div.find('a')
                    if first_link:
                        href = first_link.get('href', '')
                        id_match = re.search(r'\d+', href)
                        if id_match:
                            match_id = id_match.group()
                if not match_id:
                    continue
                    
                time_el = match_card.find('p', class_='time')
                time_str = time_el.text.strip() if time_el else ""
                
                comp_el = match_card.find('a', class_='comp-name')
                comp_str = comp_el.text.strip() if comp_el else ""
                
                home_card = match_card.find('div', class_='match-home')
                home_name, home_rank = "", ""
                if home_card:
                    home_name_el = home_card.find('a', class_='name')
                    home_name = home_name_el.text.strip() if home_name_el else ""
                    home_rank_el = home_card.find('p', class_='ranking')
                    home_rank = home_rank_el.text.strip() if home_rank_el else ""
                    
                away_card = match_card.find('div', class_='match-away')
                away_name, away_rank = "", ""
                if away_card:
                    away_name_el = away_card.find('a', class_='name')
                    away_name = away_name_el.text.strip() if away_name_el else ""
                    away_rank_el = away_card.find('p', class_='ranking')
                    away_rank = away_rank_el.text.strip() if away_rank_el else ""
                    
                # Parse Details
                detail = ml.find('div', class_='match-detail-data')
                win_prob = {}
                similar_trend = {}
                pros_cons = {
                    'home': {'pros': [], 'cons': []},
                    'away': {'pros': [], 'cons': []}
                }
                
                if detail:
                    speed_boxes = detail.find_all('div', class_='speed-box')
                    titles = detail.find_all('p', class_='home-away-title')
                    for i, title_el in enumerate(titles):
                        title = title_el.text.strip()
                        if i < len(speed_boxes):
                            sb = speed_boxes[i]
                            val_right = sb.find('p', class_='align-right')
                            val_left = sb.find('p', class_='align-left')
                            val_r_str = val_right.text.strip() if val_right else ""
                            val_l_str = val_left.text.strip() if val_left else ""
                            
                            if "获胜" in title:
                                win_prob = {'home': val_r_str, 'away': val_l_str}
                    
                    history_t_el = detail.find('p', class_='history-t')
                    similar_trend_desc = history_t_el.text.strip() if history_t_el else ""
                    similar_trend_items = []
                    history_ul = detail.find('div', class_='match-history')
                    if history_ul:
                        for li in history_ul.find_all('li'):
                            item_t = li.find('p', class_='li-t')
                            item_v = li.find('p', class_='li-v')
                            if item_t and item_v:
                                similar_trend_items.append({
                                    'outcome': item_t.text.strip(),
                                    'percentage': item_v.text.strip()
                                })
                    similar_trend = {
                        'description': similar_trend_desc,
                        'stats': similar_trend_items
                    }
                    
                    pros_cons_div = detail.find('div', class_='pros-cons')
                    if pros_cons_div:
                        home_pc = pros_cons_div.find('div', class_='home-p-c')
                        if home_pc:
                            boxes = home_pc.find_all('div', class_=re.compile(r'(pros-box|cons-box)'))
                            for box in boxes:
                                title_span = box.find('p', class_='report-t')
                                is_pros = title_span and "有利" in title_span.text
                                lists = [li.text.strip() for li in box.find_all('p', class_='report-list')]
                                if is_pros:
                                    pros_cons['home']['pros'].extend(lists)
                                else:
                                    pros_cons['home']['cons'].extend(lists)
                                    
                        away_pc = pros_cons_div.find('div', class_='away-p-c')
                        if away_pc:
                            boxes = away_pc.find_all('div', class_=re.compile(r'(pros-box|cons-box)'))
                            for box in boxes:
                                title_span = box.find('p', class_='report-t')
                                is_pros = title_span and "有利" in title_span.text
                                lists = [li.text.strip() for li in box.find_all('p', class_='report-list')]
                                if is_pros:
                                    pros_cons['away']['pros'].extend(lists)
                                else:
                                    pros_cons['away']['cons'].extend(lists)
                
                guide_matches[match_id] = {
                    'id': match_id,
                    'date': date_str,
                    'time': time_str,
                    'competition': comp_str,
                    'home_team': home_name,
                    'home_rank': home_rank,
                    'away_team': away_name,
                    'away_rank': away_rank,
                    'win_probability': win_prob,
                    'similar_trend': similar_trend,
                    'pros_cons': pros_cons,
                    'score': ''
                }
        print(f"Successfully loaded {len(guide_matches)} recommended matches.")
    except Exception as e:
        print(f"Failed to load guide recommendations: {e}. Proceeding to full dates crawl.")
        
    # 2. Initialize WAF session cookie on live.leisu.com
    try:
        html_live_init = fetch_html_with_bypass(URL_LIVE, 'live.leisu.com', opener, cj)
    except Exception as e:
        print(f"Failed to initialize live.leisu.com WAF: {e}")
        
    # 3. Crawl dates: 10 days before and 10 days after today
    today = datetime.date.today()
    dates = [today + datetime.timedelta(days=i) for i in range(-10, 11)]
    
    merged_matches = []
    seen_ids = set()
    
    # Process guide matches first, grouping them by date as they are processed
    # We will loop through the crawled dates to ensure they fit chronological categories
    for idx, d in enumerate(dates):
        date_str = f"{d.strftime('%m-%d')} {get_weekday_cn(d)}"
        
        # Select URL path for this date
        if d < today:
            url = f"https://live.leisu.com/wanchang-{d.strftime('%Y%m%d')}"
        elif d > today:
            url = f"https://live.leisu.com/saicheng-{d.strftime('%Y%m%d')}"
        else:
            url = "https://live.leisu.com/"
            
        print(f"[{idx+1}/21] Crawling live list for {date_str} from {url}...")
        
        try:
            html_d = fetch_html_with_bypass(url, 'live.leisu.com', opener, cj)
            soup = BeautifulSoup(html_d, 'html.parser')
            items = soup.find_all('div', class_=re.compile(r'dd-item'))
            print(f"  Parsed {len(items)} match rows.")
            
            for item in items:
                match_id = ""
                score_el = item.find('div', class_='lier-score')
                if score_el:
                    a_score = score_el.find('a')
                    if a_score:
                        href = a_score.get('href', '')
                        match_id_match = re.search(r'\d+', href)
                        if match_id_match:
                            match_id = match_id_match.group()
                if not match_id:
                    data_el = item.find('div', class_='lier-data')
                    if data_el:
                        a_data = data_el.find('a')
                        if a_data:
                            href = a_data.get('href', '')
                            match_id_match = re.search(r'\d+', href)
                            if match_id_match:
                                match_id = match_id_match.group()
                                
                if not match_id:
                    continue
                    
                if match_id in seen_ids:
                    continue
                seen_ids.add(match_id)
                
                # Fetch text details
                comp_el = item.find('div', class_='lier-event-name')
                comp_str = comp_el.text.strip() if comp_el else ""
                
                time_el = item.find('div', class_='lier-time')
                time_str = time_el.text.strip() if time_el else ""
                
                home_el = item.find('div', class_='lier-team-home')
                home_name = home_el.text.strip() if home_el else ""
                home_name = re.sub(r'\s+', '', home_name)
                # 清洗开赛进行中分钟数被 BS4 粘连到队名的污染（如 "00'金川人力" → "金川人力"）
                home_name = re.sub(r"^\d+\'?", '', home_name).strip()
                home_name = re.sub(r"\d+\'?$", '', home_name).strip()
                
                away_el = item.find('div', class_='lier-team-away')
                away_name = away_el.text.strip() if away_el else ""
                away_name = re.sub(r'\s+', '', away_name)
                # 清洗开赛进行中分钟数被 BS4 粘连到队名的污染（如 "始兴市民00'" → "始兴市民"）
                away_name = re.sub(r"^\d+\'?", '', away_name).strip()
                away_name = re.sub(r"\d+\'?$", '', away_name).strip()
                
                score_str = score_el.text.strip() if score_el else ""
                if score_str == "-":
                    score_str = ""
                    
                # 不再过滤小联赛：保留所有联赛赛事（包含韩国杯、挪甲等），以匹配雷速 942 场全量数据

                match_date = date_str
                if time_str and time_str.startswith("00:"):
                    next_day = d + datetime.timedelta(days=1)
                    match_date = f"{next_day.strftime('%m-%d')} {get_weekday_cn(next_day)}"

                # Merge logic
                if match_id in guide_matches:
                    match_data = guide_matches[match_id]
                    # Update date, time, score from the actual live schedule
                    match_data['date'] = match_date
                    if time_str:
                        match_data['time'] = time_str
                    if score_str:
                        match_data['score'] = score_str
                    merged_matches.append(match_data)
                else:
                    merged_matches.append({
                        'id': match_id,
                        'date': match_date,
                        'time': time_str,
                        'competition': comp_str,
                        'home_team': home_name,
                        'home_rank': '',
                        'away_team': away_name,
                        'away_rank': '',
                        'win_probability': {},
                        'similar_trend': {},
                        'pros_cons': {'home': {'pros': [], 'cons': []}, 'away': {'pros': [], 'cons': []}},
                        'score': score_str
                    })
            time.sleep(0.05)
        except Exception as e:
            print(f"Error scraping date {date_str}: {e}")
            
    # Also append any remaining guide matches that we didn't match in the crawl
    for gid, gmatch in guide_matches.items():
        if gid not in seen_ids:
            merged_matches.append(gmatch)
            seen_ids.add(gid)
            
    return merged_matches

def scrape_desktop_matches(date_str):
    """
    使用极速解密方案（今日实时）或 Playwright 优化闪电滚动方案（历史完场/未来赛程）抓取雷速 PC 端全量赛事。
    
    对于今日（实时）赛事：雷速将全量 900+ 场数据加密打包存放在 static.leisu.com/public/mod_live/alifInfo.js 中。
    我们直接使用 urllib 发起单个 HTTP 请求下载该 JS，并通过 rot13 -> base64 -> zlib 一键解密并还原全量 JSON，
    实现 1 秒内完成同步（相比之前 Playwright 滚动快了 30 倍，且极其省 CPU 资源和内存）。
    
    对于历史/未来赛事：使用 Playwright 访问主页，通过优化步长的闪电滚动提取并累积数据。
    """
    import datetime
    import codecs
    import base64
    import urllib.parse
    
    d = datetime.datetime.strptime(date_str, "%Y%m%d").date()
    today = datetime.date.today()
    
    date_formatted = f"{d.strftime('%m-%d')} {get_weekday_cn(d)}"
    
    def rot13(s):
        return codecs.encode(s, 'rot_13')

    def unescape_unicode(s):
        def replace_unicode(match):
            return chr(int(match.group(1), 16))
        return re.sub(r'%u([0-9a-fA-F]{4})', replace_unicode, s)
        
    # 方案 1：如果是今日实时页面，尝试【极速解密】
    if d == today:
        print(f"检测到抓取今日({date_str})赛事，启动【极速解密方案】...")
        try:
            url_js = 'https://static.leisu.com/public/mod_live/alifInfo.js'
            js_content = ""
            try:
                req = urllib.request.Request(url_js, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    js_content = resp.read().decode('utf-8')
            except Exception as e_direct:
                print(f"【极速解密】第一志愿静态链接失败: {e_direct}，启动灾备方案：从 live 首页动态定位数据源...")
                try:
                    url_live = 'https://live.leisu.com/'
                    req_live = urllib.request.Request(url_live, headers=HEADERS)
                    with urllib.request.urlopen(req_live, timeout=10) as resp_live:
                        live_html = resp_live.read().decode('utf-8', errors='ignore')
                    
                    js_src_match = re.search(r'src=["\']([^"\']*/alifInfo[^"\']*)["\']', live_html)
                    if js_src_match:
                        found_path = js_src_match.group(1)
                        if found_path.startswith('//'):
                            url_js = 'https:' + found_path
                        elif found_path.startswith('/'):
                            url_js = 'https://static.leisu.com' + found_path
                        else:
                            url_js = found_path
                        print(f"【极速解密】灾备成功！自动找回数据源地址: {url_js}")
                        
                        req = urllib.request.Request(url_js, headers=HEADERS)
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            js_content = resp.read().decode('utf-8')
                except Exception as e_backup:
                    print(f"【极速解密】灾备方案也失败了: {e_backup}")
                    
            if not js_content:
                raise Exception("无法加载 alifInfo 数据源 JS")
                
            # 匹配 window[_t19798[2]] = '...' 或者是 window.base64_ = '...' 或普通大加密串
            match = re.search(r"window\[_t\d+\[\d+\]\]\s*=\s*'([^']+)'", js_content)
            if not match:
                match = re.search(r"base64_\s*=\s*'([^']+)'", js_content)
            if not match:
                match = re.search(r"'([A-Za-z0-9+/=]{10000,})'", js_content)
                
            if match:
                obfuscated_str = match.group(1)
                rotated = rot13(obfuscated_str)
                decoded = base64.b64decode(rotated)
                decompressed = zlib.decompress(decoded)
                
                # 必须先用 unquote 解码普通的 URL 编码字符（如 %22 -> "），再把 %uXXXX 转换成真正的中文字符
                url_decoded_str = urllib.parse.unquote(decompressed.decode('utf-8'))
                unescaped_str = unescape_unicode(url_decoded_str)
                
                data = json.loads(unescaped_str)
                events = data.get('events', {})
                matches = data.get('matches', [])
                
                print(f"【极速解密】成功解析出 {len(matches)} 场赛事数据！")
                
                matches_list = []
                for m in matches:
                    match_id = str(m.get('id', ''))
                    if not match_id:
                        continue
                        
                    comp_id = str(m.get('comp_id', ''))
                    comp_str = events.get(comp_id, {}).get('name', '') if comp_id else ''
                    
                    match_time_val = m.get('match_time', 0)
                    time_str = ""
                    match_date = date_formatted
                    if match_time_val:
                        dt = datetime.datetime.fromtimestamp(match_time_val)
                        time_str = dt.strftime('%H:%M')
                        match_date = f"{dt.strftime('%m-%d')} {get_weekday_cn(dt)}"
                            
                    home_data = m.get('home', {})
                    away_data = m.get('away', {})
                    home_name = home_data.get('name', '') if isinstance(home_data, dict) else ''
                    away_name = away_data.get('name', '') if isinstance(away_data, dict) else ''
                    
                    # 清洗队名
                    home_name = re.sub(r'\s+', '', home_name)
                    away_name = re.sub(r'\s+', '', away_name)
                    
                    # 状态转换
                    # 原始 status 定义: 1未开, 8完场, 3中场, 2/4进行中
                    raw_status = m.get('status', 1)
                    status = 1
                    if raw_status == 8:
                        status = 8
                    elif raw_status == 1:
                        status = 1
                    else:
                        # 进行中
                        status = 4
                        if raw_status == 3: # 中场
                            status = 3
                            
                    # 比分提取
                    score_str = ""
                    half_score_str = ""
                    home_scores = home_data.get('scores', []) if isinstance(home_data, dict) else []
                    away_scores = away_data.get('scores', []) if isinstance(away_data, dict) else []
                    if status != 1:
                        if home_scores and away_scores and len(home_scores) >= 2 and len(away_scores) >= 2:
                            score_str = f"{home_scores[0]}-{away_scores[0]}"
                            half_score_str = f"{home_scores[1]}-{away_scores[1]}"
                        
                    matches_list.append({
                        'id': match_id,
                        'date': match_date,
                        'time': time_str,
                        'competition': comp_str,
                        'home_team': home_name,
                        'home_rank': '',
                        'away_team': away_name,
                        'away_rank': '',
                        'win_probability': {},
                        'similar_trend': {},
                        'pros_cons': {'home': {'pros': [], 'cons': []}, 'away': {'pros': [], 'cons': []}},
                        'score': score_str,
                        'half_score': half_score_str,
                        'penalty_score': '',
                        'status': status
                    })
                return matches_list
            else:
                print("【极速解密】未找到混淆解密特征，将降级到 Playwright 抓取...")
        except Exception as e:
            print(f"【极速解密】出错: {e}，将降级到 Playwright 抓取...")
            
    # 方案 2：历史、未来或降级处理，使用【Playwright 优化滚动提取】
    if d < today:
        url = f"https://live.leisu.com/wanchang-{date_str}"
    elif d > today:
        url = f"https://live.leisu.com/saicheng-{date_str}"
    else:
        url = "https://live.leisu.com/"
        
    print(f"Playwright Scraper: 启动优化滚动抓取 {date_str}，URL: {url}")
    matches_map = {}  # match_id -> 赛事数据，用于去重
    
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto(url, timeout=30000)
            
            # 等待首批赛事渲染
            try:
                page.wait_for_selector('.dd-item', timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            
            # 获取页面总高度，用于计算滚动步数
            total_height = page.evaluate("document.body.scrollHeight")
            print(f"Playwright Scraper: 页面高度={total_height}px，开始优化后的滚动收集...")
            
            # JS 提取当前视口内所有 .dd-item 的数据
            extract_js = """
                () => {
                    const results = [];
                    document.querySelectorAll('.dd-item').forEach(item => {
                        let matchId = '';
                        item.querySelectorAll('a[href*="detail-"]').forEach(l => {
                            const m = l.href.match(/detail-(\d+)/);
                            if (m) matchId = m[1];
                        });
                        if (!matchId) return;
                        
                        const compEl = item.querySelector('.lier-event-name');
                        const timeEl = item.querySelector('.lier-time');
                        const homeEl = item.querySelector('.lier-team-home');
                        const awayEl = item.querySelector('.lier-team-away');
                        const scoreEl = item.querySelector('.lier-score');
                        const statusEl = item.querySelector('.lier-status');
                        
                        let home = homeEl ? homeEl.textContent.replace(/\s+/g,'').replace(/^\d+\'?/,'').replace(/\d+\'?$/,'') : '';
                        let away = awayEl ? awayEl.textContent.replace(/\s+/g,'').replace(/^\d+\'?/,'').replace(/\d+\'?$/,'') : '';
                        let score = scoreEl ? scoreEl.textContent.trim() : '';
                        if (score === '-') score = '';
                        
                        const stText = statusEl ? statusEl.textContent.trim() : '';
                        let status = 1;
                        if (stText.includes('完') || stText.includes('结') || stText.includes('已')) {
                            status = 8;
                        } else if (stText.includes('中场') || stText.includes('半')) {
                            status = 3;
                        } else if (/\d+[\'\+]/.test(stText)) {
                            const min = parseInt(stText);
                            status = min <= 45 ? 2 : 4;
                        } else if (score) {
                            status = 4;
                        }
                        
                        let halfScore = '';
                        const hm = item.textContent.match(/\((\d+-\d+)\)/);
                        if (hm) halfScore = hm[1];
                        
                        results.push({
                            id: matchId,
                            competition: compEl ? compEl.textContent.trim() : '',
                            time: timeEl ? timeEl.textContent.trim() : '',
                            home_team: home, away_team: away,
                            score: score, status: status, half_score: halfScore
                        });
                    });
                    return results;
                }
            """
            
            # 优化滚动：步长从 600px 增大到 1500px，以大幅减少滚动次数，缩短页面等待
            scroll_y = 0
            step = 1500
            max_steps = int(total_height / step) + 5
            no_new_count = 0
            
            for i in range(max_steps):
                # 提取当前视口数据
                items = page.evaluate(extract_js)
                new_items = 0
                for item in items:
                    mid = item.get('id', '')
                    if mid and mid not in matches_map:
                        matches_map[mid] = item
                        new_items += 1
                
                if i % 10 == 0 or new_items > 0:
                    print(f"  步骤 {i+1}/{max_steps}: 累积 {len(matches_map)} 场 (+{new_items})")
                
                # 判断是否到底
                if new_items == 0:
                    no_new_count += 1
                    if no_new_count >= 5:  # 连续 5 步无新数据，判定滚动到底
                        print(f"Playwright Scraper: 连续 5 步无新数据，收集完毕")
                        break
                else:
                    no_new_count = 0
                
                # 滚动并等待短暂停顿以更新 DOM
                scroll_y += step
                page.evaluate(f"window.scrollTo(0, {scroll_y})")
                page.wait_for_timeout(100)  # 从 200ms 减少到 100ms
            
            browser.close()
            print(f"Playwright Scraper: 收集完成，共 {len(matches_map)} 场赛事")
            
    except Exception as e:
        print(f"Playwright scrape_desktop_matches 出错: {e}")
        import traceback
        traceback.print_exc()
        
    # 转换为列表格式
    matches_list = []
    for match_id, item_data in matches_map.items():
        time_str = item_data.get('time', '')
        match_date = date_formatted
        if time_str and time_str.startswith("00:"):
            next_day = d + datetime.timedelta(days=1)
            match_date = f"{next_day.strftime('%m-%d')} {get_weekday_cn(next_day)}"
        
        matches_list.append({
            'id': match_id,
            'date': match_date,
            'time': time_str,
            'competition': item_data.get('competition', ''),
            'home_team': item_data.get('home_team', ''),
            'home_rank': '',
            'away_team': item_data.get('away_team', ''),
            'away_rank': '',
            'win_probability': {},
            'similar_trend': {},
            'pros_cons': {'home': {'pros': [], 'cons': []}, 'away': {'pros': [], 'cons': []}},
            'score': item_data.get('score', ''),
            'half_score': item_data.get('half_score', ''),
            'penalty_score': '',
            'status': item_data.get('status', 1)
        })
        
    return matches_list
