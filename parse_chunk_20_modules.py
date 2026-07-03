import urllib.request

URL = 'https://m.leisu.com/_nuxt/0299bd5.js'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
}

def test():
    req = urllib.request.Request(URL, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as resp:
            js = resp.read().decode('utf-8')
    except Exception as e:
        print(f"Error: {e}")
        return
        
    print(f"File length: {len(js)}")
    
    # Find modules array start in chunk 20
    pos_push = js.find('.push(')
    pos_open1 = js.find('[', pos_push) 
    pos_open2 = js.find('[', pos_open1 + 1) 
    pos_comma = js.find(',', js.find(']', pos_open2))
    pos_open3 = js.find('[', pos_comma) 
    
    start_pos = pos_open3 + 1
    print(f"Push array start position: {start_pos}")
    
    # Parser loop
    i = start_pos
    n = len(js)
    
    idx = 0
    brackets = 0
    braces = 0
    parens = 0
    
    element_start = start_pos
    elements = {}
    
    while i < n:
        c = js[i]
        
        # Comments and strings
        if c == '/' and i + 1 < n and js[i+1] == '*':
            i += 2
            while i < n and not (js[i] == '*' and i + 1 < n and js[i+1] == '/'):
                i += 1
            i += 2
            continue
        if c == '/' and i + 1 < n and js[i+1] == '/':
            i += 2
            while i < n and js[i] != '\n':
                i += 1
            i += 1
            continue
        if c in ["'", '"', '`']:
            quote = c
            i += 1
            escape = False
            while i < n:
                if escape:
                    escape = False
                    i += 1
                    continue
                if js[i] == '\\':
                    escape = True
                    i += 1
                    continue
                if js[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == '/':
            is_div = False
            j = i - 1
            while j > start_pos and js[j].isspace():
                j -= 1
            prev_char = js[j]
            if prev_char.isalnum() or prev_char in [')', ']', '}']:
                is_div = True
            if not is_div:
                i += 1
                escape = False
                while i < n:
                    if escape:
                        escape = False
                        i += 1
                        continue
                    if js[i] == '\\':
                        escape = True
                        i += 1
                        continue
                    if js[i] == '/':
                        i += 1
                        while i < n and js[i] in ['g', 'i', 'm', 'y', 'u', 's']:
                            i += 1
                        break
                    if js[i] == '\n':
                        break
                    i += 1
                continue
            else:
                i += 1
                continue
                
        # Main structure
        if c == '[':
            brackets += 1
        elif c == ']':
            brackets -= 1
            if brackets < 0:
                content = js[element_start:i].strip()
                if content:
                    elements[idx] = content
                break
        elif c == '{':
            braces += 1
        elif c == '}':
            braces -= 1
        elif c == '(':
            parens += 1
        elif c == ')':
            parens -= 1
            
        # Comma splitter
        if c == ',' and brackets == 0 and braces == 0 and parens == 0:
            content = js[element_start:i].strip()
            if content:
                elements[idx] = content
            element_start = i + 1
            idx += 1
            i += 1
            continue
            
        i += 1
        
    print(f"Successfully parsed {len(elements)} non-empty modules!")
    
    # Check if 164 is in elements!
    for test_idx in [164, 201]:
        if test_idx in elements:
            el = elements[test_idx]
            print(f"\n--- Module {test_idx} (length={len(el)}) ---")
            print(el[:1500])
            print("=" * 60)
        else:
            print(f"Module {test_idx} is EMPTY (not in chunk)!")

if __name__ == '__main__':
    test()
