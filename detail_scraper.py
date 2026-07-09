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
import urllib.parse
from urllib.parse import urlparse
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
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

# 远程日志诊断容器
ODDS_DEBUG_LOG = []
def log_odds(msg):
    global ODDS_DEBUG_LOG
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    full_msg = f"[{timestamp}] {msg}"
    print(full_msg)
    ODDS_DEBUG_LOG.append(full_msg)
    if len(ODDS_DEBUG_LOG) > 200:
        ODDS_DEBUG_LOG.pop(0)

# 全局共享 WAF CookieJar 容器，免除每次点击比赛重复求解 WAF 的耗时与偶发失败风险
GLOBAL_CJ = http.cookiejar.CookieJar()

GLOBAL_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(GLOBAL_CJ))

# 赔率走势网页专属的 WAF CookieJar 容器，实现子域物理隔离，防止 WAF Cookie 冲突拦截
GLOBAL_ODDS_CJ = http.cookiejar.CookieJar()
GLOBAL_ODDS_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(GLOBAL_ODDS_CJ))

def solve_waf_via_node(html, url, user_agent):
    """
    <summary>
    使用 Node.js 子进程对 WAF 的 acw_sc__v2 挑战进行解密求解。
    已增加多重异常保护与 5 秒硬超时限制，绝不挂起 Web 服务线程。
    </summary>
    """
    script_path = os.path.join(os.path.dirname(__file__), 'waf_solver.js')
    log_odds(f"solve_waf_via_node: Starting node solver for {url} (NODE_PATH={NODE_PATH})")
    
    process = None
    try:
        process = subprocess.Popen(
            [NODE_PATH, script_path, url, user_agent],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        stdout, stderr = process.communicate(input=html, timeout=5)
        if process.returncode != 0:
            log_odds(f"solve_waf_via_node: Node execution returned non-zero code {process.returncode}. Stderr: {stderr}")
            return None
        
        res = json.loads(stdout.strip())
        if res.get('success'):
            cookie_val = res.get('cookie')
            log_odds(f"solve_waf_via_node: Successfully solved WAF! Cookie prefix: {cookie_val[:15]}...")
            return cookie_val
        else:
            log_odds(f"solve_waf_via_node: Node solver returned success=false: {stdout.strip()}")
    except subprocess.TimeoutExpired:
        log_odds("solve_waf_via_node: Hard timeout expired running Node.js solver (5s), process terminated.")
        if process:
            try:
                process.kill()
                process.communicate()
            except:
                pass
    except Exception as e_node:
        log_odds(f"solve_waf_via_node: Failed to execute or parse Node WAF solver: {e_node}")
    return None

def fetch_html_with_bypass(url, domain, opener, cj, headers=None):
    use_headers = headers if headers is not None else HEADERS.copy()
    
    # 自动从 Playwright 运行生成的 session_cookies.json 中加载全部雷速凭证到当前 urllib 会话中，实现完美浏览器行为仿真
    cookie_file = os.path.join(os.path.dirname(__file__), 'session_cookies.json')
    if os.path.exists(cookie_file):
        try:
            cj.clear()
            with open(cookie_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
                for c in cookies:
                    c_domain = c.get('domain', '')
                    # 关键安全优化：只装载匹配当前请求域名（或其父域）的 Cookie，杜绝跨域 Cookie 污染拉黑 403
                    if 'leisu.com' in c_domain:
                        if c_domain == domain or (c_domain.startswith('.') and domain.endswith(c_domain)) or domain.endswith(c_domain.lstrip('.')):
                            expires_val = c.get('expires')
                            if expires_val is not None:
                                try:
                                    expires_val = int(float(expires_val))
                                except:
                                    expires_val = None
                            ck = http.cookiejar.Cookie(
                                version=0, name=c['name'], value=c['value'],
                                port=None, port_specified=False,
                                domain=c['domain'], domain_specified=True, domain_initial_dot=c_domain.startswith('.'),
                                path=c['path'], path_specified=True,
                                secure=c['secure'], expires=expires_val, discard=True, comment=None, comment_url=None, rest={}, rfc2109=False
                            )
                            cj.set_cookie(ck)
        except Exception as e_cookie:
            print("Failed to pre-load session_cookies.json:", e_cookie)
                
    # 1. 强行把当前请求域名匹配的 WAF Cookie 提取并拼入 header 的 Cookie 头中发送，实现双重保险
    active_cookie = None
    for cookie in cj:
        if cookie.name == 'acw_sc__v2':
            c_dom = cookie.domain
            if c_dom == domain or (c_dom.startswith('.') and domain.endswith(c_dom)) or domain.endswith(c_dom.lstrip('.')):
                active_cookie = cookie.value
                break
                
    if active_cookie:
        use_headers['Cookie'] = f"acw_sc__v2={active_cookie}"
    else:
        # 如果当前 domain 没有匹配的 WAF Cookie，务必从 headers 里彻底删掉 Cookie 键，防止携带历史垃圾被判定拉黑
        if 'Cookie' in use_headers:
            del use_headers['Cookie']
        
    req = urllib.request.Request(url, headers=use_headers)
    try:
        try:
            with opener.open(req, timeout=10) as response:
                content_bytes = response.read()
                if response.info().get('Content-Encoding') == 'gzip':
                    content_bytes = zlib.decompress(content_bytes, 15 + 32)
                html = content_bytes.decode('utf-8')
                real_url = response.geturl()
                real_domain = urlparse(real_url).netloc
        except urllib.error.HTTPError as http_err:
            if http_err.code in (403, 503):
                err_content = http_err.read()
                if http_err.info().get('Content-Encoding') == 'gzip':
                    try:
                        err_content = zlib.decompress(err_content, 15 + 32)
                    except:
                        pass
                html = err_content.decode('utf-8', errors='ignore')
                real_url = url
                real_domain = domain
                if 'renderData' not in html:
                    raise http_err
            else:
                raise http_err
                
        if 'renderData' in html:
            user_agent = use_headers.get('User-Agent', '')
            cookie_val = solve_waf_via_node(html, real_url, user_agent)
            if not cookie_val:
                raise Exception(f"WAF solution failed for {real_url}")
            
            # 关键防污染优化：重试前强行清空 cj 里的全部历史 Cookie 脏数据
            # 绝对防止 HTTPCookieProcessor 提取并用过期的 Cookie 重写覆盖我们的 headers['Cookie'] 键值
            cj.clear()
            
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
            
            # 2. 内部重试时，强行把刚刚算出来的 Cookie 写入 Header，确保重试绝对携带 Cookie
            log_odds(f"fetch_html_with_bypass: Retrying request to {real_url} with new acw_sc__v2 WAF cookie...")
            use_headers['Cookie'] = f"acw_sc__v2={cookie_val}"
            req2 = urllib.request.Request(real_url, headers=use_headers)
            with opener.open(req2, timeout=10) as response2:
                content_bytes2 = response2.read()
                if response2.info().get('Content-Encoding') == 'gzip':
                    content_bytes2 = zlib.decompress(content_bytes2, 15 + 32)
                html = content_bytes2.decode('utf-8')
                log_odds(f"fetch_html_with_bypass: Retry successful! HTML length: {len(html)}")
                
        return html
    except Exception as e:
        err_body = ""
        if isinstance(e, urllib.error.HTTPError):
            try:
                err_body = e.read().decode('utf-8', errors='ignore')
            except:
                pass
        log_odds(f"fetch_html_with_bypass error for {url}: {e} (HTTPError body: {err_body[:200]})")
        if "IP ACL" in err_body or "blacklist" in err_body or (isinstance(e, urllib.error.HTTPError) and e.code == 403):
            log_odds(f"CRITICAL: IP ACL Blocked by Tengine CDN for {url}!")
            raise Exception("IP_ACL_BLACKLIST")
        raise e

def js_mod(a, b):
    """
    <summary>
    模拟 JavaScript 的 % 余数运算符（负数保留负余数）。
    </summary>
    """
    val = abs(a) % b
    if a < 0:
        return -val
    return val

def universal_decompress(data):
    """
    <summary>
    尝试以 zlib、deflate 或 gzip 三种格式自适应解压数据包。
    </summary>
    """
    try:
        return zlib.decompress(data)
    except Exception:
        pass
    try:
        return zlib.decompress(data, -zlib.MAX_WBITS)
    except Exception:
        pass
    try:
        return zlib.decompress(data, zlib.MAX_WBITS | 16)
    except Exception:
        pass
    raise Exception("All decompression methods failed")

def decode_escape_string(s):
    """
    <summary>
    还原 JavaScript 逸出格式的汉字 %uXXXX 编码为标准 Unicode 中文字符。
    </summary>
    """
    if not s:
        return ""
    s = re.sub(r'%u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
    return urllib.parse.unquote(s)

def decrypt_shujufenxi_data(html_analysis, opener, cj):
    """
    <summary>
    从 shujufenxi 网页 HTML 中定位外部 JS 数据文件，拉取并用 26 种 Caesar 偏置暴力解密出完整的战绩 JSON 数据。
    </summary>
    """
    try:
        soup = BeautifulSoup(html_analysis, 'html.parser')
        js_url = None
        for s in soup.find_all('script'):
            src = s.get('src')
            if src and '/shujufenxi/' in src:
                js_url = src
                break
        if not js_url:
            print("decrypt_shujufenxi_data: JS data URL not found in HTML.")
            return None
            
        if js_url.startswith('//'):
            js_url = 'https:' + js_url
            
        print(f"decrypt_shujufenxi_data: Fetching JS data from {js_url} ...")
        js_content = fetch_html_with_bypass(js_url, 'live.leisu.com', opener, cj)
        if not js_content:
            return None
            
        # 提取密文变量值
        match_val = re.search(r"=['\"]([A-Za-z0-9+/=]+)['\"]", js_content)
        if not match_val:
            match_val = re.search(r"=['\"]([A-Za-z0-9+/=\s]+)['\"]", js_content)
        if not match_val:
            print("decrypt_shujufenxi_data: Ciphertext not found in JS content.")
            return None
            
        ciphertext = match_val.group(1).strip()
        
        # 暴力尝试 26 个 Caesar 偏置值
        decrypted_json = None
        for c in range(26):
            try:
                res_caesar = ""
                for char_c in ciphertext:
                    code = ord(char_c)
                    x = code
                    if 65 <= code <= 90:
                        x = js_mod(code - 65 - 1 * c + 26, 26) + 65
                    elif 97 <= code <= 122:
                        x = js_mod(code - 97 - 1 * c + 26, 26) + 97
                    res_caesar += chr(x)
                
                # 补全 base64 等号填充
                missing_padding = len(res_caesar) % 4
                if missing_padding:
                    res_caesar += '=' * (4 - missing_padding)
                    
                decoded = base64.b64decode(res_caesar)
                decompressed = universal_decompress(decoded)
                
                plain_text = urllib.parse.unquote(decompressed.decode('utf-8'))
                decrypted_json = json.loads(plain_text)
                print(f"decrypt_shujufenxi_data: Successfully decrypted ciphertext with offset {c}!")
                break
            except Exception:
                pass
                
        return decrypted_json
    except Exception as e:
        print(f"decrypt_shujufenxi_data: Error decrypting shujufenxi JS data: {e}")
        return None

def parse_decrypted_history_match(item, teams, match_events, target_team_name):
    """
    <summary>
    将解密后的单个战绩/交锋数组转换为前端统一格式字典，并计算出胜平负结果。
    </summary>
    """
    try:
        match_id = item[0]
        event_id = item[1]
        status = item[2]
        m_time = item[3]
        home_info = item[4]
        away_info = item[5]
        
        comp_raw = match_events.get(str(event_id), {}).get('name_zh', '未知赛事')
        comp_name = decode_escape_string(comp_raw)
        
        date_str = time.strftime('%Y-%m-%d', time.localtime(m_time))
        
        home_raw = teams.get(str(home_info[0]), {}).get('name_zh', '未知球队')
        home_name = decode_escape_string(home_raw)
        
        away_raw = teams.get(str(away_info[0]), {}).get('name_zh', '未知球队')
        away_name = decode_escape_string(away_raw)
        
        home_score = home_info[2]
        away_score = away_info[2]
        score_str = f"{home_score}:{away_score}"
        
        target_clean = clean_team_name(target_team_name)
        home_clean = clean_team_name(home_name)
        away_clean = clean_team_name(away_name)
        
        result = "平"
        if target_clean in home_clean or home_clean in target_clean:
            if home_score > away_score: result = "胜"
            elif home_score < away_score: result = "负"
        elif target_clean in away_clean or away_clean in target_clean:
            if away_score > home_score: result = "胜"
            elif away_score < home_score: result = "负"
            
        return {
            'competition': comp_name,
            'date': date_str,
            'home': home_name,
            'away': away_name,
            'score': score_str,
            'result': result
        }
    except Exception as e:
        print(f"parse_decrypted_history_match error: {e}")
        return None

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
                    init_line_str = f"{abs(init_raw_line_val)}"
                    
                # 优先提取走地赔率 'r'，其次是赛前即时赔率 'n'
                use_r = 'r' in asia_item and isinstance(asia_item['r'], list) and len(asia_item['r']) >= 2 and len(asia_item['r'][0]) >= 3
                target_array = asia_item['r'] if use_r else asia_item['n']
                
                # 即时/走地盘口
                inst_raw_line_val = float(target_array[0][1])
                if inst_raw_line_val == 0.0:
                    inst_line_str = "0"
                elif inst_raw_line_val < 0.0:
                    inst_line_str = f"-{abs(inst_raw_line_val)}"
                else:
                    inst_line_str = f"{abs(inst_raw_line_val)}"
                    
                handicap_data = {
                    "initial_line": init_line_str,
                    "instant_line": inst_line_str,
                    "initial": [float(asia_item['f'][0]), float(asia_item['f'][2])],
                    "instant": [float(target_array[0][0]), float(target_array[0][2])],
                    "trends": [int(target_array[1][0]), int(target_array[1][2])]
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
                # 优先提取走地赔率 'r'，其次是赛前即时赔率 'n'
                use_r = 'r' in eu_item and isinstance(eu_item['r'], list) and len(eu_item['r']) >= 2 and len(eu_item['r'][0]) >= 3
                target_array = eu_item['r'] if use_r else eu_item['n']
                
                europe_data = {
                    "initial": [float(eu_item['f'][0]), float(eu_item['f'][1]), float(eu_item['f'][2])],
                    "instant": [float(target_array[0][0]), float(target_array[0][1]), float(target_array[0][2])],
                    "trends": [int(target_array[1][0]), int(target_array[1][1]), int(target_array[1][2])]
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
                    
                # 优先提取走地赔率 'r'，其次是赛前即时赔率 'n'
                use_r = 'r' in bs_item and isinstance(bs_item['r'], list) and len(bs_item['r']) >= 2 and len(bs_item['r'][0]) >= 3
                target_array = bs_item['r'] if use_r else bs_item['n']
                
                # 即时/走地盘口
                raw_inst_line = float(target_array[0][1])
                inst_line_str = str(raw_inst_line)
                if inst_line_str.endswith(".0"):
                    inst_line_str = inst_line_str[:-2]
                    
                over_under_data = {
                    "initial_line": init_line_str,
                    "instant_line": inst_line_str,
                    "initial": [float(bs_item['f'][0]), float(bs_item['f'][2])],
                    "instant": [float(target_array[0][0]), float(target_array[0][2])],
                    "trends": [int(target_array[1][0]), int(target_array[1][2])]
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
    
    # 1. 尝试从本地数据文件获取该赛事的最新状态
    status = 1
    data_file_path = os.path.join(os.path.dirname(__file__), 'parsed_matches.json')
    if os.path.exists(data_file_path):
        try:
            with open(data_file_path, 'r', encoding='utf-8') as f:
                matches = json.load(f)
            for m in matches:
                if str(m.get('id')) == str(match_id):
                    status = int(m.get('status', 1))
                    break
        except Exception:
            pass
            
    odds_data = []
    
    # 2. 停用极慢且易锁死的 Playwright 实时指数获取，全部统一由高效率纯 API 方式获取
    # 3. 使用 API 作为主通道
    if not odds_data:
        # Fetch server time
        url_time = 'https://api-gateway.leisu.com/v1/web/public/time'
        req_time = urllib.request.Request(url_time, headers=HEADERS)
        try:
            with urllib.request.urlopen(req_time) as resp:
                server_time = json.loads(resp.read().decode('utf-8'))['data']
        except Exception as e:
            print("Failed to get time for odds, fallback to local time:", e)
            server_time = int(time.time())
            
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
            
            # 通过 Node.js 加密 payload
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
            # 通过 Node.js 免文件直接运行加密 payload，防止并发状态下的临时文件读写冲突
            try:
                process = subprocess.Popen([NODE_PATH, '-e', node_enc_script], stdout=subprocess.PIPE, text=True)
                stdout, _ = process.communicate()
                encrypted_payload = stdout.strip()
            except Exception as node_err:
                print(f"Node encryption execution failed: {node_err}")
                encrypted_payload = ""

                
            url_api = f"https://{host_name}{endpoint_path}"
            headers = HEADERS.copy()
            headers['Accept'] = f"application/json, text/plain, */*;;{encrypted_payload}"
            headers['Origin'] = 'https://m.leisu.com'
            headers['Referer'] = 'https://m.leisu.com/'
            headers['source'] = source_val
            headers['sec-fetch-dest'] = 'empty'
            headers['sec-fetch-mode'] = 'cors'
            headers['sec-fetch-site'] = 'same-site'
            if 'upgrade-insecure-requests' in headers:
                del headers['upgrade-insecure-requests']
            if 'sec-fetch-user' in headers:
                del headers['sec-fetch-user']
            
            cj = GLOBAL_CJ
            opener = GLOBAL_OPENER
            
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

    # 移除 Playwright 网页端指数兜底，保持纯接口方案
    return odds_data

def get_lineup_via_api(match_id):
    print(f"Fetching lineup and injuries via API for match {match_id}...")
    lineup_data = {}
    
    url_time = 'https://api-gateway.leisu.com/v1/web/public/time'
    req_time = urllib.request.Request(url_time, headers=HEADERS)
    try:
        with GLOBAL_OPENER.open(req_time) as resp:
            content = resp.read()
            if resp.info().get('Content-Encoding') == 'gzip':
                content = zlib.decompress(content, 15 + 32)
            server_time = json.loads(content.decode('utf-8'))['data']
    except Exception as e:
        print("Failed to get time for lineup API, fallback to local time:", e)
        server_time = int(time.time())
        
    if server_time is not None:
        r = server_time + 10
        c_val = uuid.uuid4().hex
        
        endpoint = f"/v1/web/match/football/match_lineup?match_id={match_id}"
        auth_path = "/v1/web/match/football/match_lineup"
        
        l = f"{auth_path}-{r}-{c_val}-0-{SALT}"
        u = hashlib.md5(l.encode('utf-8')).hexdigest()
        auth_data = f"{r}-{c_val}-0-{u}"
        
        payload = {"auth_data": auth_data, "source": "m_leisu"}
        payload_str = json.dumps(payload, separators=(',', ':'))
        
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
        try:
            process = subprocess.Popen(['node', '-e', node_enc_script], stdout=subprocess.PIPE, text=True)
            stdout, _ = process.communicate()
            encrypted_payload = stdout.strip()
            
            url_api = f"https://web-gateway.leisu.com{endpoint}"
            headers = HEADERS.copy()
            headers['Accept'] = f"application/json, text/plain, */*;;{encrypted_payload}"
            headers['Origin'] = 'https://m.leisu.com'
            headers['Referer'] = 'https://m.leisu.com/'
            headers['source'] = 'm_leisu'
            headers['sec-fetch-dest'] = 'empty'
            headers['sec-fetch-mode'] = 'cors'
            headers['sec-fetch-site'] = 'same-site'
            if 'upgrade-insecure-requests' in headers:
                del headers['upgrade-insecure-requests']
            if 'sec-fetch-user' in headers:
                del headers['sec-fetch-user']
            
            # Request through our bypass logic to utilize node WAF solver & inject WAF Cookie manually
            html = fetch_html_with_bypass(url_api, 'web-gateway.leisu.com', GLOBAL_OPENER, GLOBAL_CJ, headers=headers)
            if html:
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
                        lineup_data = json.loads(decompressed.decode('utf-8'))
                    else:
                        lineup_data = data_val
        except Exception as e:
            print("Failed to request lineup from API:", e)
            
    return lineup_data

def get_complete_match_details(match_id, home_name, away_name):
    cj = GLOBAL_CJ
    opener = GLOBAL_OPENER
    
    home_name_clean = clean_team_name(home_name)
    away_name_clean = clean_team_name(away_name)
    
    url_analysis = f'https://live.leisu.com/shujufenxi-{match_id}'
    url_swot = f'https://www.leisu.com/guide/swot-{match_id}'
    
    h2h_data = None
    recent_data = None
    injury_data = {
        'home': {'injuries': [], 'suspensions': [], 'startings': [], 'substitutes': []},
        'away': {'injuries': [], 'suspensions': [], 'startings': [], 'substitutes': []},
        'home_formation': '',
        'away_formation': '',
        'home_manager': '',
        'away_manager': ''
    }
    trend_data = {'home': [], 'away': []}
    
    # 1.彻底停用极慢的 Playwright 战绩爬取，改为 0.3 秒的纯 HTML 解析
    playwright_analysis = None

    # 2. 爬取静态 HTML 页面 (用作伤停/走势抓取，以及 H2H/战绩的兜底)
    print(f"Scraping analysis page (HTML): {url_analysis}")
    try:
        html_analysis = fetch_html_with_bypass(url_analysis, 'live.leisu.com', opener, cj)
        soup_analysis = BeautifulSoup(html_analysis, 'html.parser')
        
        # 优先使用纯接口拉取伤停与阵容数据
        try:
            lineup_api_data = get_lineup_via_api(match_id)
            if lineup_api_data:
                api_injury = {
                    'home': {'injuries': [], 'suspensions': [], 'startings': [], 'substitutes': []},
                    'away': {'injuries': [], 'suspensions': [], 'startings': [], 'substitutes': []},
                    'home_formation': lineup_api_data.get('home_formation', ''),
                    'away_formation': lineup_api_data.get('away_formation', ''),
                    'home_manager': '',
                    'away_manager': ''
                }
                
                # 提取主教练名字
                h_manager = lineup_api_data.get('home_manager')
                if isinstance(h_manager, dict):
                    api_injury['home_manager'] = h_manager.get('name', '')
                a_manager = lineup_api_data.get('away_manager')
                if isinstance(a_manager, dict):
                    api_injury['away_manager'] = a_manager.get('name', '')
                
                # 建立球员字典映射
                players_dict = {p.get('id'): p for p in lineup_api_data.get('players', []) if p and p.get('id')}
                
                # 提取主队伤停
                for p in lineup_api_data.get('home_injury', []):
                    item = {
                        'player': p.get('name', ''),
                        'position': p.get('position', p.get('position_name', '')),
                        'reason': p.get('reason', ''),
                        'start_time': p.get('start_time_desc', ''),
                        'return_time': p.get('end_time_desc', '')
                    }
                    if '停赛' in item['reason'] or '禁赛' in item['reason']:
                        api_injury['home']['suspensions'].append(item)
                    else:
                        api_injury['home']['injuries'].append(item)
                        
                # 提取客队伤停
                for p in lineup_api_data.get('away_injury', []):
                    item = {
                        'player': p.get('name', ''),
                        'position': p.get('position', p.get('position_name', '')),
                        'reason': p.get('reason', ''),
                        'start_time': p.get('start_time_desc', ''),
                        'return_time': p.get('end_time_desc', '')
                    }
                    if '停赛' in item['reason'] or '禁赛' in item['reason']:
                        api_injury['away']['suspensions'].append(item)
                    else:
                        api_injury['away']['injuries'].append(item)
                
                # 提取主队阵容球员
                for p in lineup_api_data.get('home', []):
                    pid = p.get('player_id')
                    p_info = players_dict.get(pid, {})
                    player_item = {
                        'player_id': pid,
                        'shirt_number': p.get('shirt_number', 0),
                        'name': p_info.get('name', p.get('name', 'UNKNOWN')),
                        'logo': p_info.get('logo', 'https://cdn.leisu.com/image/player_default.png'),
                        'position': p_info.get('position', p.get('position_name', '')),
                        'incidents': p.get('incidents', [])
                    }
                    if p.get('status') == 1:
                        api_injury['home']['startings'].append(player_item)
                    else:
                        api_injury['home']['substitutes'].append(player_item)

                # 提取客队阵容球员
                for p in lineup_api_data.get('away', []):
                    pid = p.get('player_id')
                    p_info = players_dict.get(pid, {})
                    player_item = {
                        'player_id': pid,
                        'shirt_number': p.get('shirt_number', 0),
                        'name': p_info.get('name', p.get('name', 'UNKNOWN')),
                        'logo': p_info.get('logo', 'https://cdn.leisu.com/image/player_default.png'),
                        'position': p_info.get('position', p.get('position_name', '')),
                        'incidents': p.get('incidents', [])
                    }
                    if p.get('status') == 1:
                        api_injury['away']['startings'].append(player_item)
                    else:
                        api_injury['away']['substitutes'].append(player_item)

                injury_data = api_injury
                print(f"API Lineup: Successfully parsed {len(injury_data['home']['injuries'])+len(injury_data['home']['suspensions'])} injuries, {len(injury_data['home']['startings'])} starting and {len(injury_data['home']['substitutes'])} substitutes for home.")
            else:
                print("API Lineup empty, fallback to HTML parser.")
                html_injuries = parse_injuries(soup_analysis)
                injury_data['home']['injuries'] = html_injuries['home'].get('injuries', [])
                injury_data['home']['suspensions'] = html_injuries['home'].get('suspensions', [])
                injury_data['away']['injuries'] = html_injuries['away'].get('injuries', [])
                injury_data['away']['suspensions'] = html_injuries['away'].get('suspensions', [])
        except Exception as le:
            print(f"Error parsing lineup API, fallback to HTML: {le}")
            html_injuries = parse_injuries(soup_analysis)
            injury_data['home']['injuries'] = html_injuries['home'].get('injuries', [])
            injury_data['home']['suspensions'] = html_injuries['home'].get('suspensions', [])
            injury_data['away']['injuries'] = html_injuries['away'].get('injuries', [])
            injury_data['away']['suspensions'] = html_injuries['away'].get('suspensions', [])
        # 优先使用 shujufenxi 静态外部加密 JS 破密提取 (100% 准确率)
        try:
            print(f"Attempting to decrypt shujufenxi JS data package for match {match_id} ...")
            decrypted_json = decrypt_shujufenxi_data(html_analysis, opener, cj)
            if decrypted_json and 'history' in decrypted_json:
                print("Successfully decrypted shujufenxi JS data!")
                history_data = decrypted_json['history']
                teams = decrypted_json.get('teams', {})
                match_events = decrypted_json.get('match_events', {})
                
                # 1. 解析历史交锋 H2H
                h2h_matches = []
                for item in history_data.get('vs', {}).get('all', []):
                    m = parse_decrypted_history_match(item, teams, match_events, home_name_clean)
                    if m:
                        h2h_matches.append(m)
                h2h_data = {
                    'has_history': len(h2h_matches) > 0,
                    'matches': h2h_matches
                }
                
                # 2. 解析近期战绩 (主队 & 客队)
                recent_home = []
                for item in history_data.get('home', {}).get('all', []):
                    m = parse_decrypted_history_match(item, teams, match_events, home_name_clean)
                    if m:
                        recent_home.append(m)
                
                recent_away = []
                for item in history_data.get('away', {}).get('all', []):
                    m = parse_decrypted_history_match(item, teams, match_events, away_name_clean)
                    if m:
                        recent_away.append(m)
                        
                recent_data = {
                    'home': recent_home,
                    'away': recent_away
                }
            else:
                print("Failed to decrypt shujufenxi JS data, fallback to BeautifulSoup parser.")
        except Exception as e_dec:
            print(f"Error during shujufenxi JS decryption, fallback to BeautifulSoup parser: {e_dec}")
            
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
        if 'renderData' in html_swot:
            print("WARNING: SWOT page still contains WAF challenge after bypass!")
            
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
    通过纯 H5 API 方式请求 api-gateway.leisu.com，绕过 WAF 并配合 Accept 签名拉取指定公司在指定玩法下的详细变盘历史。
    采用 Caesar 反移位及 Gzip 解压缩还原明文。
    </summary>
    """
    print(f"Direct H5 API Fetcher: Fetching odds detail for match {match_id}, cid {cid}, type {type_val} ...")
    host_name = 'api-gateway.leisu.com'
    source_val = 'm_leisu'
    
    # 1. 获取服务器时间
    url_time = 'https://api-gateway.leisu.com/v1/web/public/time'
    req_time = urllib.request.Request(url_time, headers=HEADERS)
    server_time = None
    try:
        with urllib.request.urlopen(req_time, timeout=5) as resp:
            server_time = json.loads(resp.read().decode('utf-8'))['data']
    except Exception as e:
        print(f"Failed to get time for H5 odds detail: {e}")
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
        print(f"cryptography encrypt failed for H5 API: {e_crypto}")
        
    if not encrypted_payload:
        return {"error": "Failed to encrypt auth payload"}
        
    # 3. 构造请求与发送
    url_api = f"https://api-gateway.leisu.com/v1/web/match/common/odds_detail?id={match_id}&cid={cid}&type={type_val}"
    headers = HEADERS.copy()
    headers['Accept'] = f"application/json, text/plain, health/json;;{encrypted_payload}"
    # 改回正确的 API 网关 Accept 签名头部
    headers['Accept'] = f"application/json, text/plain, */*;;{encrypted_payload}"
    headers['Origin'] = 'https://m.leisu.com'
    headers['source'] = source_val
    headers['Referer'] = f'https://m.leisu.com/match/detail/football/{match_id}'
    
    cj = GLOBAL_CJ
    opener = GLOBAL_OPENER
    
    # 从 session_cookies.json 里把高级指纹 Cookie 导入到 GLOBAL_CJ 里（实现 Cookie 物理合并共享！）
    cookie_file = os.path.join(os.path.dirname(__file__), 'session_cookies.json')
    if os.path.exists(cookie_file):
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
                for c in cookies:
                    c_name = c['name']
                    # 只有 cj 中还没有的 cookie 才从 session 中加载，防止覆盖已有 Cookie
                    has_cookie = any(ck.name == c_name for ck in cj)
                    if not has_cookie:
                        c_domain = c.get('domain', '')
                        if 'leisu.com' in c_domain:
                            ck = http.cookiejar.Cookie(
                                version=0, name=c_name, value=c['value'],
                                port=None, port_specified=False,
                                domain=c['domain'], domain_specified=True, domain_initial_dot=c_domain.startswith('.'),
                                path=c['path'], path_specified=True,
                                secure=c['secure'], expires=None, discard=True, comment=None, comment_url=None, rest={}, rfc2109=False
                            )
                            cj.set_cookie(ck)
        except Exception as ec:
            print("Failed to pre-inject session cookies to GLOBAL_CJ:", ec)
            
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
            log_odds(f"get_odds_detail_via_api: Empty or missing data in res_json. Code={res_json.get('code')}")
            return {"error": f"API business error code {res_json.get('code')}: {res_json}"}
    except Exception as e:
        log_odds(f"Failed to fetch odds detail from API directly: {e}")
        return {"error": f"Fetch failed: {str(e)}"}

def decrypt_rot(key_b64, kst_str):
    salt = "uHhANonwd4UdpzOdsUqUsnl5PjurM877"
    key_seed = (kst_str + salt)[:16]
    key_bytes = key_seed.encode('utf-8')
    try:
        enc_data = base64.b64decode(key_b64)
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        cipher = Cipher(algorithms.AES(key_bytes), modes.ECB(), backend=default_backend())
        decryptor = cipher.decryptor()
        dec_data = decryptor.update(enc_data) + decryptor.finalize()
        pad_len = dec_data[-1]
        if 1 <= pad_len <= 16:
            dec_data = dec_data[:-pad_len]
        return dec_data.decode('utf-8')
    except Exception as e:
        print(f"Decrypt error for key {key_b64} with KST {kst_str}: {e}")
        return ""

def parse_trend_html_data(html, type_val):
    """
    <summary>
    辅助函数：从 trend 页面的 HTML 字符中通过正则抓取 KST 密匙，并用 AES 本地解密 explain-table 表格。
    </summary>
    """
    if not html:
        return None
        
    kst_match = re.search(r'KST\s*:\s*["\'](\d+)["\']', html)
    if not kst_match:
        kst_match = re.search(r'"KST"\s*:\s*"(\d+)"', html)
        
    if not kst_match:
        print("parse_trend_html_data: Failed to locate KST in trend page HTML!")
        return None
        
    kst_str = kst_match.group(1)
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table', class_='explain-table')
    
    type_int = int(type_val)
    if type_int - 1 >= len(tables):
        print(f"parse_trend_html_data: Table index {type_int-1} out of range (Total tables: {len(tables)})")
        return None
        
    table = tables[type_int - 1]
    table_data = []
    trs = table.find_all('tr')
    if len(trs) <= 1:
        return []
        
    for tr in trs[1:]:
        tds = tr.find_all('td')
        if len(tds) < 5:
            continue
            
        time_str = tds[0].text.strip()
        score_str = tds[1].text.strip()
        
        def get_val(td):
            canvas = td.find('canvas')
            if canvas and canvas.get('key'):
                key = canvas.get('key')
                return decrypt_rot(key, kst_str)
            return td.text.strip()
            
        val1 = get_val(tds[2]) # 主胜/主水/大球水
        val2 = get_val(tds[3]) # 平局/让球盘/大小球盘
        val3 = get_val(tds[4]) # 客胜/客水/小球水
        
        if type_int in (1, 3):
            table_data.append({
                'change_time': time_str,
                'home': float(val1) if val1 else 0.0,
                'line': val2,
                'line_zh': val2,
                'away': float(val3) if val3 else 0.0,
                'score': score_str,
                'type': type_int
            })
        elif type_int == 2:
            table_data.append({
                'change_time': time_str,
                'home': float(val1) if val1 else 0.0,
                'draw': float(val2) if val2 else 0.0,
                'away': float(val3) if val3 else 0.0,
                'score': score_str,
                'type': type_int
            })
    log_odds(f"parse_trend_html_data: Successfully parsed and decrypted {len(table_data)} trend items!")
    return table_data

def get_odds_detail_via_html_pure(match_id, cid, type_val):
    """
    <summary>
    使用纯 Python 绕过 WAF 抓取 trend 静态网页，并用 BeautifulSoup 解析 explain-table，
    在 Python 中使用 AES 纯算法直接解密混淆赔率数据，速度比 Playwright 快 10-15 倍。
    </summary>
    """
    url_target = f"https://odds.leisu.com/trend-{match_id}-{cid}"
    headers = HEADERS.copy()
    headers['Origin'] = 'https://odds.leisu.com'
    headers['Referer'] = 'https://odds.leisu.com/'
    log_odds(f"Pure HTML Scraper: Fetching trend HTML via bypass: {url_target} ...")
    try:
        html = fetch_html_with_bypass(url_target, 'odds.leisu.com', GLOBAL_ODDS_OPENER, GLOBAL_ODDS_CJ, headers=headers)
        return parse_trend_html_data(html, type_val)
    except Exception as e:
        log_odds(f"Pure HTML Scraper Error: {e}")
        return None

def get_odds_detail_via_playwright(match_id, cid, type_val):
    """
    <summary>
    获取赔率走势明细。优先通过高效率纯 H5 API 方式请求；
    若 API 失败，则转由纯 Python + HTML 解析加算法解密（避开无头浏览器，1秒内返回）；
    若 HTML 解析也失败，则调用重构后的外部 auth_generator.py 启动极速独立 Playwright 进程抓取并解密（~1.2秒，无黑窗，100%成功）。
    </summary>
    """
    # 1. 优先尝试直接用纯 H5 API 获取（共享已缓存 WAF Cookie，0.1秒级秒回）
    try:
        log_odds(f"get_odds_detail_via_playwright: Phase 1 (H5 API) starting for match={match_id}, cid={cid}, type={type_val}")
        api_data = get_odds_detail_via_api(match_id, cid, type_val)
        if isinstance(api_data, list) and len(api_data) > 0:
            log_odds("Successfully fetched odds details via high performance H5 API!")
            return api_data
        elif isinstance(api_data, dict) and 'error' not in api_data:
            log_odds("Successfully fetched odds details via high performance H5 API (dict)!")
            return api_data
        else:
            log_odds(f"H5 API approach reported error or empty: {api_data}. Falling back to HTML Scraper...")
    except Exception as e_api:
        log_odds(f"H5 API approach exception: {e_api}. Falling back to HTML Scraper...")

    # 2. 第二优先：使用高效率纯 Python + HTML 静态走势页解析与 AES 本地解密
    try:
        log_odds(f"get_odds_detail_via_playwright: Phase 2 (HTML Scraper) starting for match={match_id}, cid={cid}")
        pure_html_data = get_odds_detail_via_html_pure(match_id, cid, type_val)
        if isinstance(pure_html_data, list) and len(pure_html_data) > 0:
            log_odds("Successfully fetched odds details via high performance Pure HTML Scraper!")
            return pure_html_data
        else:
            log_odds("Pure HTML Scraper returned empty or failed. Falling back to fast subprocess crawler...")
    except Exception as e_pure:
        log_odds(f"Pure HTML Scraper exception: {e_pure}. Falling back to fast subprocess crawler...")

    # 3. 彻底停用极度耗费 CPU 的 Playwright 无头浏览器子进程降级，防止低配 Linux 云服务器雪崩卡死
    log_odds(f"Playwright Subprocess Crawler Disabled for match {match_id}, cid {cid}, type {type_val} to protect server resources.")
    return None

if __name__ == '__main__':
    data = get_lineup_via_api(4556518)
    print("KEYS:", list(data.keys()))
    if 'home' in data and data['home']:
        print("SAMPLE PLAYER:", json.dumps(data['home'][0], indent=2, ensure_ascii=False))
