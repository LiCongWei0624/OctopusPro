import urllib.request
import urllib.error
import http.cookiejar
import subprocess
import json
import os

URL = 'https://www.leisu.com/guide'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

def solve_waf_via_node(html):
    script_path = os.path.join(os.path.dirname(__file__), 'waf_solver.js')
    
    # Run node waf_solver.js
    node_path = r"C:\Program Files\nodejs\node.exe"
    process = subprocess.Popen(
        [node_path, script_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8'
    )
    
    stdout, stderr = process.communicate(input=html)
    if process.returncode != 0:
        print(f"[Node Error] {stderr}")
        return None
        
    try:
        res = json.loads(stdout.strip())
        if res.get('success'):
            return res.get('cookie')
        else:
            print(f"[Solver Error] {res.get('error')}")
    except Exception as e:
        print(f"[JSON Parse Error] {e}. Output was: {stdout}")
    
    return None

def fetch_page():
    print(f"Step 1: Making request to {URL}...")
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    
    req = urllib.request.Request(URL, headers=HEADERS)
    
    try:
        with opener.open(req, timeout=10) as response:
            html = response.read().decode('utf-8')
            
            # Print received cookies
            print("Received cookies from first response:")
            for cookie in cj:
                print(f"  {cookie.name}={cookie.value}")
                
            # Check if we hit WAF challenge page
            if '<textarea id="renderData"' in html:
                print("WAF challenge page detected!")
                cookie_val = solve_waf_via_node(html)
                if not cookie_val:
                    print("Failed to solve WAF challenge.")
                    return
                
                print(f"Successfully solved WAF. Cookie: acw_sc__v2={cookie_val}")
                
                # Add WAF bypass cookie to CookieJar
                waf_cookie = http.cookiejar.Cookie(
                    version=0, name='acw_sc__v2', value=cookie_val,
                    port=None, port_specified=False,
                    domain='www.leisu.com', domain_specified=True, domain_initial_dot=False,
                    path='/', path_specified=True,
                    secure=False, expires=None, discard=True, comment=None, comment_url=None, rest={}, rfc2109=False
                )
                cj.set_cookie(waf_cookie)
                
                # Step 2: Make request with cookie using the same opener
                print("\nStep 2: Making request with bypass cookie...")
                bypass_req = urllib.request.Request(URL, headers=HEADERS)
                
                with opener.open(bypass_req, timeout=10) as final_resp:
                    final_html = final_resp.read().decode('utf-8')
                    print(f"Final Status Code: {final_resp.status}")
                    print(f"Final Content Length: {len(final_html)}")
                    
                    # Print final cookies
                    print("Final cookies:")
                    for cookie in cj:
                        print(f"  {cookie.name}={cookie.value}")
                    
                    # Save final html to a file to verify
                    with open('final_page.html', 'w', encoding='utf-8') as f:
                        f.write(final_html)
                    print("Successfully saved final page to final_page.html")
                    
                    # Print preview of the content
                    if "英格兰" in final_html:
                        print("Success! Match data detected in response!")
                    else:
                        print("Match data not detected. Let's inspect final_page.html.")
            else:
                print("Direct response succeeded (no WAF page).")
                with open('final_page.html', 'w', encoding='utf-8') as f:
                    f.write(html)
                print("Successfully saved page to final_page.html")
                
    except urllib.error.HTTPError as e:
        print(f"HTTPError: {e.code} - {e.reason}")
    except Exception as e:
        print(f"Error: {e}")
if __name__ == '__main__':
    fetch_page()
