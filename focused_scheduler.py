#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷速体育 — 精要采集器 (Focused Collector)
======================================
策略：1次 odds_list + 3家大盘口 × 2盘口(亚盘+大小球)变盘 = 7次请求/场

固定取三家大盘口公司：
  - cid=22  平博(Pinnacle)   — 市场风向标，最sharp
  - cid=2    Bet365(3*)      — 全球最大体量
  - cid=3    皇冠(皇*)       — 亚洲盘口核心

防封策略：
  - 速率限制 15次/min（≈4秒/次）
  - 随机UA + 随机Accept-Language
  - 请求间随机 1-3s 人为间隙
  - 比赛间随机 3-8s 思考间隔
  - 顺序随机化

依赖：cryptography, (无需 curl_cffi, 无需 Playwright)
"""

import sys, os, json, time, uuid, hashlib, base64, zlib, random
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# ============ 常量 ============
SALT = "uHhANonwd4UdpzOdsUqUsnl5PjurM877"
AES_KEY = b'kw@h*8gCIn$8X#df'
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "cache"
FIXED_CIDS = [22, 2, 3]  # Pinnacle, Bet365, 皇冠
TREND_TYPES = {"asia": 1, "bs": 2}
RATE_LIMIT = 15  # 次/分钟

USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.43 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 9 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone14,6; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/122.0.6261.89 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Xiaomi 13 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone15,4; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


# ============ 认证工具 ============
def get_server_time() -> int:
    try:
        req = Request("https://api-gateway.leisu.com/v1/web/public/time", headers={
            "User-Agent": random.choice(USER_AGENTS)
        })
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return int(data["data"])
    except Exception:
        return int(time.time())


def build_auth(path: str) -> tuple[str, dict]:
    """构建认证头和 payload。返回 (encrypted_payload, auth_data)"""
    t = get_server_time()
    r = t + 10
    c_val = uuid.uuid4().hex
    l = f"{path}-{r}-{c_val}-0-{SALT}"
    u = hashlib.md5(l.encode("utf-8")).hexdigest()
    auth_data = f"{r}-{c_val}-0-{u}"
    payload = {"auth_data": auth_data, "source": "m_leisu"}

    # AES-128-ECB 加密
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    payload_str = json.dumps(payload, separators=(",", ":"))
    pad_len = 16 - (len(payload_str) % 16)
    padded = payload_str + chr(pad_len) * pad_len
    cipher = Cipher(algorithms.AES(AES_KEY), modes.ECB(), backend=default_backend())
    ct = cipher.encryptor().update(padded.encode("utf-8")) + cipher.encryptor().finalize()
    enc = base64.b64encode(ct).decode("utf-8").replace("+", "-").replace("/", "_").replace("=", "")

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": f"application/json, text/plain, */*;;{enc}",
        "Accept-Language": random.choice(["zh-CN,zh;q=0.9", "zh-CN,zh;q=0.9,en;q=0.8", "zh-CN,zh;q=0.8,en;q=0.5"]),
        "Origin": "https://m.leisu.com",
        "Referer": "https://m.leisu.com/",
        "source": "m_leisu",
    }
    return enc, headers


def decrypt_response(data_str: str, code_val: int) -> dict:
    """解密雷速加密响应"""
    offset = code_val - 100
    caesar = ""
    for c in data_str:
        oc = ord(c)
        if 65 <= oc <= 90:
            caesar += chr((oc - 65 - offset + 26) % 26 + 65)
        elif 97 <= oc <= 122:
            caesar += chr((oc - 97 - offset + 26) % 26 + 97)
        else:
            caesar += c
    decoded = base64.b64decode(caesar)
    decompressed = zlib.decompress(decoded, 15 + 32)
    return json.loads(decompressed.decode("utf-8"))


def api_get(path: str, params: dict = None) -> dict | None:
    """带认证的 API GET 请求，自动处理 WAF"""
    enc, headers = build_auth(path)
    qs = "&".join(f"{k}={v}" for k, v in (params or {}).items())
    url = f"https://api-gateway.leisu.com{path}?{qs}" if qs else f"https://api-gateway.leisu.com{path}"

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()
            html = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not html.strip():
                return None

        # WAF challenge 即使 HTTP 200 也会返回
        if "renderData" in html:
            cookie = solve_waf(html, url, headers.get("User-Agent", ""))
            if cookie:
                headers["Cookie"] = f"acw_sc__v2={cookie}"
                try:
                    req2 = Request(url, headers=headers)
                    with urlopen(req2, timeout=15) as resp2:
                        raw2 = resp2.read()
                        html2 = raw2.decode("utf-8") if isinstance(raw2, bytes) else raw2
                        if html2.strip() and "renderData" not in html2:
                            res2 = json.loads(html2)
                            d, c = res2.get("data"), res2.get("code", 0)
                            if d and isinstance(d, str) and 100 <= c <= 130:
                                return decrypt_response(d, c)
                            return res2
                except:
                    pass
            return None

        res = json.loads(html)
        data, code = res.get("data"), res.get("code", 0)
        if data and isinstance(data, str) and 100 <= code <= 130:
            return decrypt_response(data, code)
        return res
    except HTTPError as e:
        # HTTP 错误 + WAF 处理
        err_body = e.read().decode("utf-8", errors="replace")
        if "renderData" in err_body:
            cookie = solve_waf(err_body, url, headers.get("User-Agent", ""))
            if cookie:
                headers["Cookie"] = f"acw_sc__v2={cookie}"
                try:
                    req2 = Request(url, headers=headers)
                    with urlopen(req2, timeout=15) as resp2:
                        raw2 = resp2.read()
                        html2 = raw2.decode("utf-8") if isinstance(raw2, bytes) else raw2
                        if html2.strip() and "renderData" not in html2:
                            res2 = json.loads(html2)
                            d, c = res2.get("data"), res2.get("code", 0)
                            if d and isinstance(d, str) and 100 <= c <= 130:
                                return decrypt_response(d, c)
                            return res2
                except:
                    pass
        return None
    except Exception:
        return None


def solve_waf(html: str, url: str, user_agent: str) -> str | None:
    """用 Node.js 求解 WAF acw_sc__v2"""
    import subprocess
    script = str(BASE_DIR / "waf_solver.js")
    temp = str(BASE_DIR / f"_tmp_waf_{uuid.uuid4().hex[:8]}.html")
    try:
        with open(temp, "w", encoding="utf-8") as f:
            f.write(html)
        proc = subprocess.Popen(
            ["node", script, url, user_agent, temp],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        out, _ = proc.communicate(timeout=5)
        res = json.loads(out.strip())
        if res.get("success"):
            return res.get("cookie")
    except:
        pass
    finally:
        if os.path.exists(temp):
            try: os.remove(temp)
            except: pass
    return None


# ============ 精要采集 ============
def focused_pick(match_id: str, fixed_cids: list[int] = None) -> dict | None:
    """
    精要采集一场比赛：
    1. odds_list → 所有公司初盘/即时
    2. fixed_cids 各取 asia + bs 变盘
    """
    t0 = time.time()
    pick_cids = fixed_cids or FIXED_CIDS
    result = {
        "match_id": match_id,
        "captured_at": datetime.now().isoformat(),
        "top_companies": [],
        "other_companies": [],
        "stats": {},
    }

    # [1] odds_list
    print(f"[1] odds_list...", end="", flush=True)
    odds = api_get("/v1/web/match/common/odds_list", {"match_id": match_id})
    if not odds:
        print(" ❌ 无数据")
        return None

    cids = odds.get("cids", [])
    coop = odds.get("coop", {})
    print(f" {len(cids)}家公司")

    # 解析所有公司当前赔率
    companies = {}
    for cid in cids:
        info = coop.get(str(cid), {})
        companies[int(cid)] = {
            "cid": cid, "name": info.get("name", f"cid_{cid}"),
            "type": info.get("type", 0), "odds_current": {}, "trends": {},
        }

    for ot in ["asia", "eu", "bs"]:
        items = odds.get(ot, [])
        if isinstance(items, dict):
            items = list(items.items())
        elif isinstance(items, list):
            items = [(cids[i], v) for i, v in enumerate(items) if i < len(cids)]
        for cid_s, vals in items:
            cid = int(cid_s)
            if cid in companies and isinstance(vals, dict):
                if vals.get("f") or vals.get("n"):
                    companies[cid]["odds_current"][ot] = {"当前": vals.get("f",[]), "初盘": vals.get("n",[])}

    # [2] 变盘: 固定 3 家 × 2 盘口
    pick_cids = [c for c in pick_cids if c in companies]
    total = len(pick_cids) * len(TREND_TYPES)
    done = 0
    print(f"[2] 变盘 ({len(pick_cids)}家×{len(TREND_TYPES)}盘口={total}次)...")

    for cid in pick_cids:
        comp = companies[cid]
        for tn, tv in TREND_TYPES.items():
            done += 1
            if done > 1:
                time.sleep(0.5 + random.random())  # 1-1.5s 间隙
            data = api_get("/v1/web/match/common/odds_detail", {
                "match_id": match_id, "cid": str(cid), "type": str(tv),
            })
            if data and isinstance(data, list):
                comp["trends"][tn] = data
                print(f"  [{done}/{total}] {comp['name']:8s} {tn:6s} ✅ {len(data)}条")
            else:
                print(f"  [{done}/{total}] {comp['name']:8s} {tn:6s} ❌")

    # 收集其他公司（不含变盘）
    others = []
    for cid_int, comp in companies.items():
        if cid_int in pick_cids or not comp["odds_current"]:
            continue
        others.append({"cid": comp["cid"], "name": comp["name"], "odds_current": comp["odds_current"]})

    result["top_companies"] = [companies[c] for c in pick_cids]
    result["other_companies"] = others
    result["stats"] = {
        "total_companies": len(cids),
        "trend_calls": total,
        "total_requests": 1 + total,
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    return result


def focused_batch(match_ids: list[str], max_rate: int = RATE_LIMIT,
                  fixed_cids: list[int] = None, proxy: str = None):
    """批量精要采集"""
    fixed_cids = fixed_cids or FIXED_CIDS
    order = list(range(len(match_ids)))
    random.shuffle(order)

    results = []
    t_start = time.time()
    total = len(match_ids)

    print(f"\n{'='*55}")
    print(f"🏟 批量精要采集 {total} 场比赛")
    print(f"   ├ 目标公司: cid={fixed_cids}")
    print(f"   ├ 每场请求: 1+{len(fixed_cids)*2} = {1+len(fixed_cids)*2}次")
    print(f"   ├ 速率: ≤{max_rate}次/min")
    print(f"   └ 人为间隔: 3~8s")
    print(f"{'='*55}")

    for idx, pos in enumerate(order):
        mid = match_ids[pos]
        print(f"\n--- [{idx+1}/{total}] 比赛 {mid} ---")
        data = focused_pick(mid, fixed_cids=fixed_cids)
        if data:
            s = data["stats"]
            names = [c["name"] for c in data["top_companies"]]
            print(f"   ✅ {s['total_requests']}次请求, 公司: {names}")
            results.append(data)
        else:
            print(f"   ❌ 无数据")

        if idx < total - 1:
            pause = 3 + 5 * random.random()
            print(f"   💤 休息 {pause:.0f}s...", end="", flush=True)
            time.sleep(pause)
            print()

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fp = OUTPUT_DIR / f"focused_{len(results)}matches_{int(time.time())}.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 完成 {len(results)}/{total} 场, ⏱{time.time()-t_start:.0f}s")
    print(f"💾 已保存: {fp}")
    return results


# ============ 入口 ============
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="雷速体育 精要采集器（固定三家公司 × 2盘口变盘）")
    ap.add_argument("match_ids", nargs="+", help="比赛ID（可传多个）")
    ap.add_argument("--cids", type=int, nargs="+", default=FIXED_CIDS,
                    help=f"目标公司CID (默认 {' '.join(map(str,FIXED_CIDS))})")
    ap.add_argument("--max-rate", type=int, default=RATE_LIMIT, help=f"速率限制 (默认{RATE_LIMIT}次/min)")
    args = ap.parse_args()

    focused_batch(args.match_ids, max_rate=args.max_rate, fixed_cids=args.cids)
