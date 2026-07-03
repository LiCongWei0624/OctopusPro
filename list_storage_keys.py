import urllib.request
import re

URL_JS = 'https://m.leisu.com/_nuxt/de74dcb.js'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
}

def test():
    req = urllib.request.Request(URL_JS, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as resp:
            js = resp.read().decode('utf-8')
    except Exception as e:
        print(f"Error: {e}")
        return
        
    print("--- Searching for localStorage / sessionStorage keys ---")
    keys = set(re.findall(r'Storage\.getItem\s*\(\s*["\']([^"\']+)["\']\s*\)', js, re.IGNORECASE))
    print("Keys accessed via getItem:")
    for k in sorted(keys):
        print("  ", k)
        
    print("\n--- Searching for token-related sessionStorage accesses ---")
    matches = re.finditer(r'sessionStorage\.getItem\s*\(', js)
    for m in matches:
        pos = m.start()
        print("sessionStorage:", js[max(0, pos-100):min(len(js), pos+200)])
        print("-" * 50)

if __name__ == '__main__':
    test()
