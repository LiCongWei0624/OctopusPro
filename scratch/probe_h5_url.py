import urllib.request
import urllib.error

match_id = "4467734"  # 利恩 vs 阿萨纳 (完赛挪甲)
user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
headers = {'User-Agent': user_agent}

urls = [
    f"https://m.leisu.com/match/detail?id={match_id}",
    f"https://m.leisu.com/match/details?id={match_id}",
    f"https://m.leisu.com/match/index?id={match_id}",
    f"https://m.leisu.com/live?id={match_id}",
    f"https://m.leisu.com/live/detail?id={match_id}",
    f"https://m.leisu.com/odds?id={match_id}",
    f"https://m.leisu.com/odds/detail?id={match_id}",
    f"https://m.leisu.com/data?id={match_id}",
    f"https://m.leisu.com/data/detail?id={match_id}"
]

print("开始探测雷速手机版 H5 单场详情页的真实 URL 格式...")

for url in urls:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode('utf-8')
            # 检查返回的内容中是否包含 404 或者“抱歉”字样
            if "页面不存在" in content or "404" in content:
                print(f"[-] {url} -> 404 (页面不存在内容)")
            else:
                print(f"[+] {url} -> 200 SUCCESS (内容长度: {len(content)})")
                print("   预览内容:", content[:150].strip().replace('\n', ' '))
    except urllib.error.HTTPError as e:
        # 很多时候 521 也算连通（WAF 盾），但 404 说明路径错
        if e.code == 521:
            print(f"[?] {url} -> 521 WAF CHALLENGE (路径正确但需要破解)")
        else:
            print(f"[-] {url} -> HTTP {e.code}")
    except Exception as e:
        print(f"[x] {url} -> 异常: {e}")
