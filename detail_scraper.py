# -*- coding: utf-8 -*-
import urllib.request
import urllib.error
import http.cookiejar
import time
import subprocess
import json
import os
import re
import shutil
import hashlib
import uuid
import zlib
import base64
from urllib.parse import urlparse
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,image/avif,image/heif,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'sec-ch-ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'none',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1'
}

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
    if process.returncode != 0:
        return None
    try:
        res = json.loads(stdout.strip())
        if res.get('success'):
            return res.get('cookie')
    except Exception:
        pass
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
            
        if '<textarea id="renderData"' in html:
            user_agent = use_headers.get('User-Agent', '')
            cookie_val = solve_waf_via_node(html, real_url, user_agent)
            if not cookie_val:
                raise Exception(f"WAF solution failed for {real_url}")
            
            # Set the WAF bypass cookie for both the specific host and parent domain for maximum compatibility
            waf_cookie_host = http.cookiejar.Cookie(
                version=0, name='acw_sc__v2', value=cookie_val,
                port=None, port_specified=False,
                domain=real_domain, domain_specified=True, domain_initial_dot=real_domain.startswith('.'),
                path='/', path_specified=True,
                secure=False, expires=None, discard=True, comment=None, comment_url=None, rest={}, rfc2109=False
            )
            cj.set_cookie(waf_cookie_host)
            
            try:
                waf_cookie_parent = http.cookiejar.Cookie(
                    version=0, name='acw_sc__v2', value=cookie_val,
                    port=None, port_specified=False,
                    domain='.leisu.com', domain_specified=True, domain_initial_dot=True,
                    path='/', path_specified=True,
                    secure=False, expires=None, discard=True, comment=None, comment_url=None, rest={}, rfc2109=False
                )
                cj.set_cookie(waf_cookie_parent)
            except:
                pass
            
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

def clean_team_name(name):
    name = re.sub(r'[\(（].*?[\)）]', '', name)
    return name.strip()

def parse_match_row(tr, team_name):
    tds = tr.find_all('td')
    if len(tds) < 6:
        return None
    comp = tds[0].text.strip()
    date = tds[1].text.strip()
    home = tds[2].text.strip()
    away = tds[4].text.strip()
    score = tds[5].text.strip()
    
    team_name_clean = clean_team_name(team_name)
    home_clean = clean_team_name(home)
    away_clean = clean_team_name(away)
    
    # Calculate outcome (胜/平/负)
    result = "平"
    if ":" in score:
        try:
            home_goals, away_goals = map(int, score.split(':'))
            if team_name_clean in home_clean or home_clean in team_name_clean:
                if home_goals > away_goals: result = "胜"
                elif home_goals < away_goals: result = "负"
            elif team_name_clean in away_clean or away_clean in team_name_clean:
                if away_goals > home_goals: result = "胜"
                elif away_goals < home_goals: result = "负"
        except Exception:
            pass
            
    return {
        'competition': comp,
        'date': date,
        'home': home,
        'away': away,
        'score': score,
        'result': result
    }

def parse_h2h(soup, home_name):
    h2h_box = None
    for title in soup.find_all('div', class_='box-title'):
        if "历史交锋" in title.text:
            h2h_box = title.parent
            break
            
    if not h2h_box:
        return {'has_history': False, 'matches': []}
        
    table = h2h_box.find('table')
    if not table:
        return {'has_history': False, 'matches': []}
        
    matches = []
    tbody = table.find('tbody')
    target = tbody if tbody else table
    for tr in target.find_all('tr'):
        m = parse_match_row(tr, home_name)
        if m:
            matches.append(m)
            
    return {
        'has_history': len(matches) > 0,
        'matches': matches
    }

def parse_recent_results(soup):
    recent_box = None
    for title in soup.find_all('div', class_='box-title'):
        if "近期战绩" in title.text:
            recent_box = title.parent
            break
            
    res = {'home': [], 'away': []}
    if not recent_box:
        return res
        
    panels = recent_box.find_all('div', class_='box-panel')
    # Panel 0 is home, Panel 1 is away
    for idx, key in enumerate(['home', 'away']):
        if idx < len(panels):
            panel = panels[idx]
            team_el = panel.find('div', class_='name')
            team_name = team_el.text.strip() if team_el else ""
            
            table = panel.find('table')
            if table:
                tbody = table.find('tbody')
                target = tbody if tbody else table
                for tr in target.find_all('tr'):
                    m = parse_match_row(tr, team_name)
                    if m:
                        res[key].append(m)
    return res

def parse_injuries_panel(panel):
    injuries = []
    suspensions = []
    current_type = 'injury'
    
    tbody = panel.find('tbody')
    if not tbody:
        return {'injuries': [], 'suspensions': []}
        
    for tr in tbody.find_all('tr'):
        if 'tr-title' in tr.get('class', []):
            title_text = tr.text.strip()
            if '停赛' in title_text:
                current_type = 'suspension'
            else:
                current_type = 'injury'
            continue
            
        tds = tr.find_all('td')
        if len(tds) < 5:
            continue
            
        # Player name block has a .name div
        player_name_el = tds[0].find('div', class_='name')
        player_name = player_name_el.text.strip() if player_name_el else tds[0].text.strip()
        
        position = tds[1].text.strip()
        reason = tds[2].text.strip()
        start_time = tds[3].text.strip()
        return_time = tds[4].text.strip()
        
        item = {
            'player': player_name,
            'position': position,
            'reason': reason,
            'start_time': start_time,
            'return_time': return_time
        }
        
        if current_type == 'injury':
            injuries.append(item)
        else:
            suspensions.append(item)
            
    return {'injuries': injuries, 'suspensions': suspensions}

def parse_injuries(soup):
    box = None
    for title in soup.find_all('div', class_='box-title'):
        if "伤停情况" in title.text:
            box = title.parent
            break
            
    res = {'home': {'injuries': [], 'suspensions': []}, 'away': {'injuries': [], 'suspensions': []}}
    if not box:
        return res
        
    panels = box.find_all('div', class_='box-panel')
    for idx, key in enumerate(['home', 'away']):
        if idx < len(panels):
            res[key] = parse_injuries_panel(panels[idx])
    return res

def parse_trends_panel(panel):
    tbody = panel.find('tbody')
    if not tbody:
        return []
        
    trends = []
    for tr in tbody.find_all('tr'):
        tds = tr.find_all('td')
        if len(tds) < 10:
            continue
            
        type_str = tds[0].text.strip()
        played = tds[1].text.strip()
        win = tds[2].text.strip()
        draw = tds[3].text.strip()
        loss = tds[4].text.strip()
        win_rate = tds[5].text.strip()
        big = tds[6].text.strip()
        big_rate = tds[7].text.strip()
        small = tds[8].text.strip()
        small_rate = tds[9].text.strip()
        
        trends.append({
            'type': type_str,
            'played': played,
            'win': win,
            'draw': draw,
            'loss': loss,
            'win_rate': win_rate,
            'big': big,
            'big_rate': big_rate,
            'small': small,
            'small_rate': small_rate
        })
    return trends

def parse_trends(soup):
    box = None
    for title in soup.find_all('div', class_='box-title'):
        if "走势" in title.text:
            box = title.parent
            break
            
    res = {'home': [], 'away': []}
    if not box:
        return res
        
    panels = box.find_all('div', class_='box-panel')
    for idx, key in enumerate(['home', 'away']):
        if idx < len(panels):
            res[key] = parse_trends_panel(panels[idx])
    return res

def parse_swot(soup):
    pros_cons = {
        'home': {'pros': [], 'cons': []},
        'away': {'pros': [], 'cons': []}
    }
    
    pros_cons_div = soup.find('div', class_='pros-cons')
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
        return pros_cons

    # Desktop layout parsing fallback
    children_divs = soup.find_all('div', class_=lambda x: x and 'children' in x)
    swot_divs = [d for d in children_divs if len(d.get('class', [])) >= 2]
    
    good_divs = [d for d in swot_divs if 'good' in d.get('class', [])]
    harmful_divs = [d for d in swot_divs if 'harmful' in d.get('class', [])]
    
    if len(good_divs) >= 2:
        ul_home_pro = good_divs[0].find('ul', class_='list')
        if ul_home_pro:
            pros_cons['home']['pros'] = [li.text.strip() for li in ul_home_pro.find_all('li')]
            
        ul_away_pro = good_divs[1].find('ul', class_='list')
        if ul_away_pro:
            pros_cons['away']['pros'] = [li.text.strip() for li in ul_away_pro.find_all('li')]
            
    if len(harmful_divs) >= 2:
        ul_home_con = harmful_divs[0].find('ul', class_='list')
        if ul_home_con:
            pros_cons['home']['cons'] = [li.text.strip() for li in ul_home_con.find_all('li')]
            
        ul_away_con = harmful_divs[1].find('ul', class_='list')
        if ul_away_con:
            pros_cons['away']['cons'] = [li.text.strip() for li in ul_away_con.find_all('li')]
            
    return pros_cons

SALT = "uHhANonwd4UdpzOdsUqUsnl5PjurM877"

def get_analysis_via_playwright(match_id):
    print(f"Playwright: Fetching analysis for match {match_id} from shujufenxi page...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            url = f"https://live.leisu.com/shujufenxi-{match_id}"
            page.goto(url, timeout=20000)
            page.wait_for_selector('div.history.box-area', timeout=15000)
            
            js_expr = """
            () => {
                const h2hEl = document.querySelector('div.history.box-area');
                const recentEl = document.querySelector('div.recent-rank.box-area');
                return {
                    h2h: h2hEl && h2hEl.__vue__ ? h2hEl.__vue__.list : null,
                    recent: recentEl && recentEl.__vue__ ? recentEl.__vue__.table : null
                };
            }
            """
            data = page.evaluate(js_expr)
            browser.close()
            return data
    except Exception as e:
        print(f"Playwright analysis fetch failed for {match_id}: {e}")
        return None

def get_odds_via_playwright(match_id):
    print(f"Playwright Fallback: Fetching odds for finished match {match_id} from PC odds page...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            url = f"https://odds.leisu.com/3in1-{match_id}"
            page.goto(url, timeout=15000)
            page.wait_for_selector('.main-content-vue', timeout=8000)
            
            js_expr = """
            () => {
                const el = document.querySelector('.main-content-vue');
                if (el && el.__vue__) {
                    return el.__vue__.ftb_odds;
                }
                return null;
            }
            """
            data = page.evaluate(js_expr)
            browser.close()
            return data
    except Exception as e:
        print(f"Playwright fallback failed for {match_id}: {e}")
        return None

def parse_odds_json_to_list(decrypted_json):
    if not decrypted_json:
        return []
        
    target_companies = [
        {"name": "36*", "cid": 2},
        {"name": "皇*", "cid": 3},
        {"name": "威***", "cid": 9},
        {"name": "易**", "cid": 10},
        {"name": "澳*", "cid": 7},
        {"name": "立*", "cid": 5},
        {"name": "韦*", "cid": 11},
        {"name": "Inter*", "cid": 13},
        {"name": "12*", "cid": 14},
        {"name": "利*", "cid": 15},
        {"name": "盈*", "cid": 16},
        {"name": "18**", "cid": 17}
    ]
    
    asia_list = decrypted_json.get('asia', [])
    eu_list = decrypted_json.get('eu', [])
    bs_list = decrypted_json.get('bs', [])
    
    if not isinstance(asia_list, list):
        asia_list = []
    if not isinstance(eu_list, list):
        eu_list = []
    if not isinstance(bs_list, list):
        bs_list = []
        
    asia_map = {item['cid']: item for item in asia_list if isinstance(item, dict) and 'cid' in item}
    eu_map = {item['cid']: item for item in eu_list if isinstance(item, dict) and 'cid' in item}
    bs_map = {item['cid']: item for item in bs_list if isinstance(item, dict) and 'cid' in item}
    
    odds_data = []
    for comp in target_companies:
        cid = comp['cid']
        asia_item = asia_map.get(cid)
        eu_item = eu_map.get(cid)
        bs_item = bs_map.get(cid)
        
        if not asia_item and not eu_item and not bs_item:
            continue
            
        handicap_data = {
            "initial_line": "0",
            "instant_line": "0",
            "initial": [1.0, 1.0],
            "instant": [1.0, 1.0],
            "trends": [0, 0]
        }
        if asia_item:
            try:
                is_home_strong = True
                if eu_item and 'f' in eu_item and len(eu_item['f']) >= 3:
                    is_home_strong = float(eu_item['f'][0]) < float(eu_item['f'][2])
                    
                # 初始盘口
                init_raw_line_val = float(asia_item['f'][1])
                if init_raw_line_val == 0.0:
                    init_line_str = "0"
                elif init_raw_line_val < 0.0:
                    init_line_str = f"-{abs(init_raw_line_val)}"
                else:
                    init_line_str = f"+{abs(init_raw_line_val)}"
                    
                # 即时盘口
                inst_raw_line_val = float(asia_item['n'][0][1])
                if inst_raw_line_val == 0.0:
                    inst_line_str = "0"
                elif inst_raw_line_val < 0.0:
                    inst_line_str = f"-{abs(inst_raw_line_val)}"
                else:
                    inst_line_str = f"+{abs(inst_raw_line_val)}"
                    
                handicap_data = {
                    "initial_line": init_line_str,
                    "instant_line": inst_line_str,
                    "initial": [float(asia_item['f'][0]), float(asia_item['f'][2])],
                    "instant": [float(asia_item['n'][0][0]), float(asia_item['n'][0][2])],
                    "trends": [int(asia_item['n'][1][0]), int(asia_item['n'][1][2])]
                }
            except Exception as ex:
                print(f"Error parsing handicap for cid {cid}: {ex}")
                
        europe_data = {
            "initial": [1.0, 1.0, 1.0],
            "instant": [1.0, 1.0, 1.0],
            "trends": [0, 0, 0]
        }
        if eu_item:
            try:
                europe_data = {
                    "initial": [float(eu_item['f'][0]), float(eu_item['f'][1]), float(eu_item['f'][2])],
                    "instant": [float(eu_item['n'][0][0]), float(eu_item['n'][0][1]), float(eu_item['n'][0][2])],
                    "trends": [int(eu_item['n'][1][0]), int(eu_item['n'][1][1]), int(eu_item['n'][1][2])]
                }
            except Exception as ex:
                print(f"Error parsing europe for cid {cid}: {ex}")
                
        over_under_data = {
            "initial_line": "0",
            "instant_line": "0",
            "initial": [1.0, 1.0],
            "instant": [1.0, 1.0],
            "trends": [0, 0]
        }
        if bs_item:
            try:
                # 初始盘口
                raw_init_line = float(bs_item['f'][1])
                init_line_str = str(raw_init_line)
                if init_line_str.endswith(".0"):
                    init_line_str = init_line_str[:-2]
                    
                # 即时盘口
                raw_inst_line = float(bs_item['n'][0][1])
                inst_line_str = str(raw_inst_line)
                if inst_line_str.endswith(".0"):
                    inst_line_str = inst_line_str[:-2]
                    
                over_under_data = {
                    "initial_line": init_line_str,
                    "instant_line": inst_line_str,
                    "initial": [float(bs_item['f'][0]), float(bs_item['f'][2])],
                    "instant": [float(bs_item['n'][0][0]), float(bs_item['n'][0][2])],
                    "trends": [int(bs_item['n'][1][0]), int(bs_item['n'][1][2])]
                }
            except Exception as ex:
                print(f"Error parsing over_under for cid {cid}: {ex}")
                
        odds_data.append({
            "company": comp["name"],
            "cid": comp["cid"],
            "handicap": handicap_data,
            "europe": europe_data,
            "over_under": over_under_data
        })
        
    return odds_data

def get_real_odds(match_id):
    host_name = 'api-gateway.leisu.com'
    source_val = 'm_leisu'
    
    # 1. Fetch server time
    url_time = 'https://api-gateway.leisu.com/v1/web/public/time'
    req_time = urllib.request.Request(url_time, headers=HEADERS)
    try:
        with urllib.request.urlopen(req_time) as resp:
            server_time = json.loads(resp.read().decode('utf-8'))['data']
    except Exception as e:
        print("Failed to get time for odds:", e)
        server_time = None
        
    odds_data = []
    if server_time is not None:
        r = server_time + 10
        c_val = uuid.uuid4().hex
        
        endpoint_path = f"/v1/web/match/common/odds_list?match_id={match_id}"
        auth_path = "/v1/web/match/common/odds_list"
        l = f"{auth_path}-{r}-{c_val}-0-{SALT}"
        u = hashlib.md5(l.encode('utf-8')).hexdigest()
        auth_data = f"{r}-{c_val}-0-{u}"
        
        payload = {"auth_data": auth_data, "source": source_val}
        payload_str = json.dumps(payload, separators=(',', ':'))
        
        # Encrypt payload via Node.js
        node_enc_script = f"""
const crypto = require('crypto');
function encrypt(text) {{
    const key = Buffer.from('kw@h*8gCIn$8X#df', 'utf8');
    const cipher = crypto.createCipheriv('aes-128-ecb', key, null);
    let encrypted = cipher.update(text, 'utf8', 'base64');
    encrypted += cipher.final('base64');
    return encrypted.replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=/g, '');
}}
console.log(encrypt('{payload_str}'));
"""
        enc_script_path = os.path.join(os.path.dirname(__file__), 'temp_enc_payload.js')
        with open(enc_script_path, 'w', encoding='utf-8') as f:
            f.write(node_enc_script)
            
        process = subprocess.Popen([NODE_PATH, enc_script_path], stdout=subprocess.PIPE, text=True)
        stdout, _ = process.communicate()
        encrypted_payload = stdout.strip()
        
        try:
            os.remove(enc_script_path)
        except:
            pass
            
        url_api = f"https://{host_name}{endpoint_path}"
        headers = HEADERS.copy()
        headers['Accept'] = f"application/json, text/plain, */*;;{encrypted_payload}"
        headers['Origin'] = 'https://m.leisu.com'
        headers['source'] = source_val
        
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        
        try:
            html = fetch_html_with_bypass(url_api, host_name, opener, cj, headers=headers)
            res_json = json.loads(html)
            
            if 'data' in res_json and res_json['data']:
                data_val = res_json['data']
                if isinstance(data_val, str):
                    offset = res_json['code'] - 100
                    
                    res_caesar = ""
                    for c in data_val:
                        code = ord(c)
                        if 65 <= code <= 90:
                            res_caesar += chr((code - 65 - offset + 26) % 26 + 65)
                        elif 97 <= code <= 122:
                            res_caesar += chr((code - 97 - offset + 26) % 26 + 97)
                        else:
                            res_caesar += c
                    
                    decoded_bytes = base64.b64decode(res_caesar)
                    decompressed = zlib.decompress(decoded_bytes, 15 + 32)
                    decrypted_json = json.loads(decompressed.decode('utf-8'))
                    
                    odds_data = parse_odds_json_to_list(decrypted_json)
        except Exception as e:
            print("Failed to get real odds from API:", e)

    # 如果 API 未返回赔率数据，则触发 Playwright PC 网页端兜底
    if not odds_data:
        try:
            pc_odds_json = get_odds_via_playwright(match_id)
            if pc_odds_json:
                odds_data = parse_odds_json_to_list(pc_odds_json)
        except Exception as pe:
            print(f"Failed to fallback to Playwright for odds for match {match_id}: {pe}")
            
    return odds_data

def get_complete_match_details(match_id, home_name, away_name):
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    
    home_name_clean = clean_team_name(home_name)
    away_name_clean = clean_team_name(away_name)
    
    url_analysis = f'https://live.leisu.com/shujufenxi-{match_id}'
    url_swot = f'https://www.leisu.com/guide/swot-{match_id}'
    
    h2h_data = None
    recent_data = None
    injury_data = {'home': {'injuries': [], 'suspensions': []}, 'away': {'injuries': [], 'suspensions': []}}
    trend_data = {'home': [], 'away': []}
    
    # 1. 尝试使用 Playwright 提取 Vue 底层高精度数据
    playwright_analysis = None
    try:
        playwright_analysis = get_analysis_via_playwright(match_id)
    except Exception as pe:
        print(f"Failed to fetch analysis via Playwright for match {match_id}: {pe}")
        
    if playwright_analysis:
        if playwright_analysis.get('h2h') is not None:
            try:
                h2h_raw = playwright_analysis['h2h']
                matches = []
                for item in h2h_raw:
                    first = item.get('first_team', {})
                    second = item.get('second_team', {})
                    matches.append({
                        "competition": item.get('comp', {}).get('name_zh', '未知'),
                        "date": time.strftime("%Y-%m-%d", time.localtime(item.get('match_time', 0))) if item.get('match_time') else '未知',
                        "home": first.get('name_zh', ''),
                        "away": second.get('name_zh', ''),
                        "score": f"{first.get('score', 0)}:{second.get('score', 0)}",
                        "result": item.get('win_loss', {}).get('result', '')
                    })
                h2h_data = {
                    "has_history": len(matches) > 0,
                    "matches": matches
                }
                print(f"Playwright: Extracted {len(matches)} H2H matches successfully.")
            except Exception as he:
                print("Failed to parse Playwright H2H data:", he)
                
        if playwright_analysis.get('recent') is not None:
            try:
                recent_raw = playwright_analysis['recent']
                home_matches = []
                if 'home' in recent_raw and 'list' in recent_raw['home']:
                    for item in recent_raw['home']['list']:
                        first = item.get('first_team', {})
                        second = item.get('second_team', {})
                        home_matches.append({
                            "competition": item.get('comp', {}).get('name_zh', '未知'),
                            "date": time.strftime("%Y-%m-%d", time.localtime(item.get('match_time', 0))) if item.get('match_time') else '未知',
                            "home": first.get('name_zh', ''),
                            "away": second.get('name_zh', ''),
                            "score": f"{first.get('score', 0)}:{second.get('score', 0)}",
                            "result": item.get('win_loss', {}).get('result', '')
                        })
                away_matches = []
                if 'away' in recent_raw and 'list' in recent_raw['away']:
                    for item in recent_raw['away']['list']:
                        first = item.get('first_team', {})
                        second = item.get('second_team', {})
                        away_matches.append({
                            "competition": item.get('comp', {}).get('name_zh', '未知'),
                            "date": time.strftime("%Y-%m-%d", time.localtime(item.get('match_time', 0))) if item.get('match_time') else '未知',
                            "home": first.get('name_zh', ''),
                            "away": second.get('name_zh', ''),
                            "score": f"{first.get('score', 0)}:{second.get('score', 0)}",
                            "result": item.get('win_loss', {}).get('result', '')
                        })
                recent_data = {
                    "home": home_matches,
                    "away": away_matches
                }
                print(f"Playwright: Extracted {len(home_matches)} home and {len(away_matches)} away recent matches successfully.")
            except Exception as re_ex:
                print("Failed to parse Playwright recent data:", re_ex)

    # 2. 爬取静态 HTML 页面 (用作伤停/走势抓取，以及 H2H/战绩的兜底)
    print(f"Scraping analysis page (HTML): {url_analysis}")
    try:
        html_analysis = fetch_html_with_bypass(url_analysis, 'live.leisu.com', opener, cj)
        soup_analysis = BeautifulSoup(html_analysis, 'html.parser')
        
        # 伤停与走势依然在 HTML 里抓取，很稳定
        injury_data = parse_injuries(soup_analysis)
        trend_data = parse_trends(soup_analysis)
        
        # 如果 Playwright 获取到的数据为空，我们再 fallback 到 BeautifulSoup 提取作为兜底
        if h2h_data is None:
            print("Fallback: parse H2H via BeautifulSoup")
            h2h_data = parse_h2h(soup_analysis, home_name_clean)
        if recent_data is None:
            print("Fallback: parse recent results via BeautifulSoup")
            recent_data = parse_recent_results(soup_analysis)
            
    except Exception as e:
        print(f"Failed to scrape analysis HTML page {match_id}: {e}")
        if h2h_data is None:
            h2h_data = {'has_history': False, 'matches': []}
        if recent_data is None:
            recent_data = {'home': [], 'away': []}
        
    print(f"Scraping SWOT page: {url_swot}")
    try:
        html_swot = fetch_html_with_bypass(url_swot, 'www.leisu.com', opener, cj)
        print(f"SWOT page loaded. Length: {len(html_swot)}")
        if "textarea id=\"renderData\"" in html_swot:
            print("WARNING: SWOT page is WAF challenge!")
            
        soup_swot = BeautifulSoup(html_swot, 'html.parser')
        swot_data = parse_swot(soup_swot)
    except Exception as e:
        print(f"Failed to scrape SWOT page {match_id}: {e}")
        swot_data = {'home': {'pros': [], 'cons': []}, 'away': {'pros': [], 'cons': []}}
        
    # 后处理替换今天这场比赛在 H2H 和近期战绩里的滞后比分
    current_score = None
    data_file_path = os.path.join(os.path.dirname(__file__), 'parsed_matches.json')
    if os.path.exists(data_file_path):
        try:
            with open(data_file_path, 'r', encoding='utf-8') as f:
                all_m = json.load(f)
            for am in all_m:
                if str(am.get('id')) == str(match_id):
                    raw_score = am.get('score', '')
                    if '-' in raw_score:
                        current_score = raw_score.replace('-', ':')
                    break
        except Exception:
            pass
            
    if current_score:
        # 替换 H2H 中的今天比分
        if h2h_data and 'matches' in h2h_data:
            for m in h2h_data['matches']:
                if (clean_team_name(m.get('home')) == home_name_clean and 
                    clean_team_name(m.get('away')) == away_name_clean) or \
                   (clean_team_name(m.get('home')) == away_name_clean and 
                    clean_team_name(m.get('away')) == home_name_clean):
                    m['score'] = current_score
                    
        # 替换近期战绩中的今天比分
        if recent_data:
            for key in ['home', 'away']:
                if key in recent_data:
                    for m in recent_data[key]:
                        if (clean_team_name(m.get('home')) == home_name_clean and 
                            clean_team_name(m.get('away')) == away_name_clean) or \
                           (clean_team_name(m.get('home')) == away_name_clean and 
                            clean_team_name(m.get('away')) == home_name_clean):
                            m['score'] = current_score

    odds_index = get_real_odds(match_id)
    
    return {
        'h2h': h2h_data,
        'recent_results': recent_data,
        'injuries': injury_data,
        'trends': trend_data,
        'pros_cons': swot_data,
        'odds_index': odds_index
    }

def get_odds_detail_via_api(match_id, cid, type_val):
    """
    <summary>
    通过纯 API 方式请求 odds.leisu.com，绕过 WAF 并配合 Accept 签名拉取指定公司在指定玩法下的详细变盘历史。
    采用 Caesar 反移位及 Gzip 解压缩还原明文。
    </summary>
    """
    print(f"Direct API Fetcher: Fetching odds detail for match {match_id}, cid {cid}, type {type_val} ...")
    host_name = 'odds.leisu.com'
    source_val = 'pc_leisu'
    
    # 1. 获取服务器时间
    url_time = 'https://api-gateway.leisu.com/v1/web/public/time'
    req_time = urllib.request.Request(url_time, headers=HEADERS)
    server_time = None
    try:
        with urllib.request.urlopen(req_time, timeout=5) as resp:
            server_time = json.loads(resp.read().decode('utf-8'))['data']
    except Exception as e:
        print(f"Failed to get time for odds detail: {e}")
        server_time = int(time.time())
        
    r = server_time + 10
    c_val = uuid.uuid4().hex
    
    auth_path = "/v1/web/match/common/odds_detail"
    l = f"{auth_path}-{r}-{c_val}-0-{SALT}"
    u = hashlib.md5(l.encode('utf-8')).hexdigest()
    auth_data = f"{r}-{c_val}-0-{u}"
    
    payload = {"auth_data": auth_data, "source": source_val}
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    # 2. 对 payload 进行 AES-128-ECB 加密
    encrypted_payload = None
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        key = b'kw@h*8gCIn$8X#df'
        pad_len = 16 - (len(payload_str) % 16)
        padded = payload_str + chr(pad_len) * pad_len
        
        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        encryptor = cipher.encryptor()
        ct = encryptor.update(padded.encode('utf-8')) + encryptor.finalize()
        res_b64 = base64.b64encode(ct).decode('utf-8')
        encrypted_payload = res_b64.replace('+', '-').replace('/', '_').replace('=', '')
    except Exception as e_crypto:
        print(f"cryptography encrypt failed or not installed: {e_crypto}, fallback to Node.js subprocess")
        node_enc_script = f"""
const crypto = require('crypto');
function encrypt(text) {{
    const key = Buffer.from('kw@h*8gCIn$8X#df', 'utf8');
    const cipher = crypto.createCipheriv('aes-128-ecb', key, null);
    let encrypted = cipher.update(text, 'utf8', 'base64');
    encrypted += cipher.final('base64');
    return encrypted.replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=/g, '');
}}
console.log(encrypt('{payload_str}'));
"""
        enc_script_path = os.path.join(os.path.dirname(__file__), f"temp_enc_detail_{uuid.uuid4().hex[:8]}.js")
        try:
            with open(enc_script_path, 'w', encoding='utf-8') as f:
                f.write(node_enc_script)
            process = subprocess.Popen([NODE_PATH, enc_script_path], stdout=subprocess.PIPE, text=True)
            stdout, _ = process.communicate(timeout=5)
            encrypted_payload = stdout.strip()
        except Exception as e_node:
            print("Node.js encryption fallback failed:", e_node)
        finally:
            if os.path.exists(enc_script_path):
                try:
                    os.remove(enc_script_path)
                except:
                    pass
                    
    if not encrypted_payload:
        return {"error": "Failed to encrypt auth payload"}
        
    # 3. 构造请求与发送，并在需要时处理 WAF 验证挑战
    url_api = f"https://odds.leisu.com/v1/web/match/common/odds_detail?id={match_id}&cid={cid}&type={type_val}"
    headers = HEADERS.copy()
    headers['Accept'] = f"application/json, text/plain, */*;;{encrypted_payload}"
    headers['Origin'] = 'https://odds.leisu.com'
    headers['source'] = source_val
    
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    
    try:
        html = fetch_html_with_bypass(url_api, host_name, opener, cj, headers=headers)
        res_json = json.loads(html)
        
        if 'data' in res_json and res_json['data']:
            data_val = res_json['data']
            if isinstance(data_val, str):
                offset = res_json['code'] - 100
                res_caesar = ""
                for c in data_val:
                    code = ord(c)
                    if 65 <= code <= 90:
                        res_caesar += chr((code - 65 - offset + 26) % 26 + 65)
                    elif 97 <= code <= 122:
                        res_caesar += chr((code - 97 - offset + 26) % 26 + 97)
                    else:
                        res_caesar += c
                
                decoded_bytes = base64.b64decode(res_caesar)
                decompressed = zlib.decompress(decoded_bytes, 15 + 32)
                decrypted_json = json.loads(decompressed.decode('utf-8'))
                return decrypted_json
            else:
                return data_val
        else:
            return {"error": f"API business error code {res_json.get('code')}: {res_json}"}
    except Exception as e:
        print(f"Failed to fetch odds detail from API directly: {e}")
        return {"error": f"Fetch failed: {str(e)}"}

def get_odds_detail_via_playwright(match_id, cid, type_val):
    """
    <summary>
    获取赔率走势明细。优先通过高效率纯 API 方式请求；
    若 API 请求失败，再回退调用外部 auth_generator.py 启动 Playwright 进程作为兜底机制。
    </summary>
    """
    # 1. 优先尝试直接用纯 API 获取（免无头浏览器开销，秒级加载且稳定）
    try:
        api_data = get_odds_detail_via_api(match_id, cid, type_val)
        if isinstance(api_data, list):
            print("Successfully fetched odds details via high performance API!")
            return api_data
        elif isinstance(api_data, dict) and 'error' not in api_data:
            print("Successfully fetched odds details via high performance API (dict)!")
            return api_data
        else:
            print(f"API approach reported error or empty: {api_data}. Falling back to Playwright Subprocess...")
    except Exception as e_api:
        print(f"API approach exception: {e_api}. Falling back to Playwright Subprocess...")

    # 2. 降级兜底方案：调用 Playwright 子进程运行 auth_generator.py
    print(f"Fallback Subprocess Crawler: Fetching odds detail for match {match_id}, cid {cid}, type {type_val} ...")
    import sys
    cache_path = os.path.join(os.path.dirname(__file__), f"odds_detail_{match_id}_{cid}_{type_val}.json")
    
    # 若已有现成缓存，直接读取返回
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except Exception as e_read:
            print("Failed to read existing local cache:", e_read)
            
    process = None
    try:
        script_path = os.path.join(os.path.dirname(__file__), 'auth_generator.py')
        process = subprocess.Popen(
            [sys.executable, script_path, str(match_id), str(cid), str(type_val), "--headless-only"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        
        # 缩短超时时间到 12 秒（结合 JS 侧的 5秒 超时，12秒保证子进程能优雅退出，绝不挂起死锁 Flask）
        stdout, stderr = process.communicate(timeout=12)
        print("Crawler subprocess output:", stdout)
        
        # Double check: if cache path not immediately found, sleep 0.2s and try again
        if not os.path.exists(cache_path):
            time.sleep(0.2)
            
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                try:
                    os.remove(cache_path)
                except:
                    pass
                return data
            except Exception as e_read:
                return {"error": f"Failed to read sub-crawler cache: {e_read}"}
        else:
            try:
                lines = stdout.strip().split('\n')
                for line in reversed(lines):
                    if line.strip().startswith('{') and line.strip().endswith('}'):
                        res_json = json.loads(line.strip())
                        if not res_json.get('success'):
                            return {"error": res_json.get('error', 'Unknown crawler error')}
                        else:
                            alt_cache = res_json.get('cache_path')
                            if alt_cache and os.path.exists(alt_cache):
                                try:
                                    with open(alt_cache, 'r', encoding='utf-8') as f:
                                        data = json.load(f)
                                    try:
                                        os.remove(alt_cache)
                                    except:
                                        pass
                                    return data
                                except:
                                    pass
            except:
                pass
            return {"error": f"Crawler failed to generate cache. Stderr: {stderr.strip()}"}
            
    except subprocess.TimeoutExpired as e_timeout:
        print(f"Subprocess crawler timed out after 8s. Force-killing to release resources...")
        if process:
            try:
                process.kill()
                process.communicate() # wait to clean zombie
            except:
                pass
        return {"error": f"Crawler subprocess timed out: {e_timeout}"}
    except Exception as e:
        print("Failed to run crawler subprocess:", e)
        if process:
            try:
                process.kill()
                process.communicate()
            except:
                pass
        return {"error": f"Crawler execution exception: {str(e)}"}

if __name__ == '__main__':
    details = get_complete_match_details('4459724', '英格兰', '民主刚果')
    print("Test scrape complete!")
    print(json.dumps(details, ensure_ascii=False, indent=2)[:1000])
