"""Gemini API 通路探针。零依赖，只用标准库。

用法：
    python gemini探针.py                        # 只查通路 + key 有效性 + 模型清单，不消耗生成额度
    python gemini探针.py --ask "你好"            # 真发一次 generateContent
    python gemini探针.py --probe-limit gemini-4-hydrogen --n 40   # 故意撞 429，从错误体里读出该模型的真实上限

key 只从环境变量 GEMINI_API_KEY 读取，本脚本不落盘、不打印明文。
"""

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"


def mask(key: str) -> str:
    return f"{key[:6]}…{key[-4:]}（{len(key)} 字符）" if key else "(未设置)"


def opener(bypass_proxy: bool):
    if bypass_proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def call(path: str, key: str, bypass_proxy: bool, method: str = "GET", body=None, timeout: int = 20):
    url = f"{BASE}{path}"
    headers = {"x-goog-api-key": key, "content-type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener(bypass_proxy).open(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:800]}
    except Exception as e:  # TLS / 连接层失败
        return None, {"error": f"{type(e).__name__}: {e}"}


def step(label: str, ok: bool, detail: str = ""):
    mark = "OK  " if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))


def _call_with_deadline(path, key, bypass, deadline):
    """直连被 DNS 挂住时 urllib 的 timeout 管不到 getaddrinfo，丢线程里限时收尸。"""
    box = {}

    def worker():
        box.update(zip(("code", "payload"), call(path, key, bypass)))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(deadline)
    if t.is_alive():
        return None, {"error": f"超过 {deadline}s 没返回（多半卡在 DNS 或 TCP 握手）"}
    return box.get("code"), box.get("payload")


def probe_reach(key: str):
    """先试环境代理（失败得快），再限时试直连。"""
    print("\n== 1. 通路诊断 ==")
    order = (("走 HTTPS_PROXY 环境变量", False, 25), ("绕过代理直连", True, 15))
    for label, bypass, deadline in order:
        code, payload = _call_with_deadline("/models?pageSize=1", key, bypass, deadline)
        if code is None:
            step(label, False, str(payload.get("error", payload))[:200])
            continue
        step(label, True, f"HTTP {code}")
        if code in (401, 403):
            step(label + " · key 被拒", False, str(payload)[:240])
        return bypass  # 返回可用那条路的 bypass 标志
    return None


def list_models(key: str, bypass: bool):
    print("\n== 2. 模型清单（能调的 id 以此为准，别照抄博客）==")
    code, payload = call("/models?pageSize=200", key, bypass)
    if code != 200:
        step("列出模型", False, f"HTTP {code} {str(payload)[:300]}")
        return []
    names = []
    for m in payload.get("models", []):
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" in methods:
            names.append(m["name"].replace("models/", ""))
    step("列出模型", True, f"{len(names)} 个支持 generateContent")
    for n in names:
        print("   ", n)
    return names


def ask(key: str, bypass: bool, model: str, prompt: str):
    print(f"\n== 3. generateContent @ {model} ==")
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    code, payload = call(f"/models/{model}:generateContent", key, bypass, "POST", body)
    if code == 200:
        cand = payload.get("candidates", [{}])[0]
        text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        step("调用成功", True, f"usageMetadata={payload.get('usageMetadata', {})}")
        print(text[:1200])
    else:
        step("调用失败", False, f"HTTP {code}")
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:2000])
    return code, payload


def probe_limit(key: str, bypass: bool, model: str, n: int):
    """连打 n 发，撞出 429 后从 quotaDetails 里读真实上限。会吃掉当天额度。"""
    print(f"\n== 4. 撞限流读上限 @ {model}（最多 {n} 发，会消耗 RPD）==")
    body = {"contents": [{"parts": [{"text": "回复 ok 两个字"}]}]}
    for i in range(1, n + 1):
        code, payload = call(f"/models/{model}:generateContent", key, bypass, "POST", body)
        if code == 429:
            step(f"第 {i} 发触发 429", True)
            for d in payload.get("error", {}).get("details", []):
                for v in d.get("violations", []):
                    print(f"    quotaId={v.get('quotaId')}  quotaValue={v.get('quotaValue')}  "
                          f"metric={v.get('quotaMetric')}")
                    print(f"      {v.get('description','')}")
            print("    含 PerMinute 的：退避重试即可；含 PerDay 的：等太平洋时间午夜（北京 16:00）重置。")
            return
        if code != 200:
            step(f"第 {i} 发", False, f"HTTP {code} {str(payload)[:200]}")
            return
        print(f"    第 {i} 发 200")
        time.sleep(0.3)
    step("未撞上限", False, f"{n} 发全 200，把 --n 调大再看")


def classify(code: int, payload: dict):
    """把返回码翻译成「免费层能不能用」。

    注意：429 里报哪个计数器 ≠ 你撞了限。第一发就打 429、冷却一分钟再打还是 429，
    说明该型号在你这层的上限就是 0（用 --recheck 验证），别写成「额度耗尽」。
    """
    if code == 200:
        used = payload.get("usageMetadata", {})
        return "可用", f"in={used.get('promptTokenCount','?')} out={used.get('candidatesTokenCount','?')}"
    if code is None:
        return "传输失败", str(payload.get("error", payload))[:120]
    blob = json.dumps(payload, ensure_ascii=False)
    if code == 429:
        counters = []
        for d in payload.get("error", {}).get("details", []):
            for v in d.get("violations", []):
                qid = str(v.get("quotaId", ""))
                val = str(v.get("quotaValue", ""))
                counters.append(f"{qid}={val or '未给出'}")
        return "429（待判：上限0 还是真限流）", "; ".join(counters) or blob[:140]
    if code == 503:
        return "服务端忙", str(payload.get("error", {}).get("message", blob))[:140]
    if code == 404:
        return "型号对新用户已关", str(payload.get("error", {}).get("message", blob))[:140]
    if code == 400:
        return "参数不适用", str(payload.get("error", {}).get("message", blob))[:140]
    if code == 403:
        return "无权限", str(payload.get("error", {}).get("message", blob))[:140]
    return f"HTTP {code}", blob[:140]


def recheck(key: str, bypass: bool, models: list, wait_s: float):
    """撞 429 的型号，等一分钟再打一发：通了=只是限流，还不通=免费层上限 0。"""
    print(f"\n== 冷却 {wait_s:.0f}s 后复打 {len(models)} 个 429 型号 ==")
    body = {"contents": [{"parts": [{"text": "ok"}]}]}
    zero, rate_limited, other = [], [], []
    for m in models:
        code, payload = call(f"/models/{m}:generateContent", key, bypass, "POST", body, timeout=60)
        verdict, detail = classify(code, payload)
        if code == 200:
            rate_limited.append(m)
            print(f"  可恢复了  {m:<40} {detail}")
        elif code == 429:
            zero.append(m)
            print(f"  仍 429    {m:<40} → 免费层上限 0；{detail}")
        else:
            other.append(m)
            print(f"  {verdict:<10} {m:<40} {detail}")
        time.sleep(wait_s)
    print("\n== 复打汇总 ==")
    print(f"  免费层上限 0（{len(zero)}）: " + ", ".join(zero))
    print(f"  只是限流、冷却即可（{len(rate_limited)}）: " + ", ".join(rate_limited))
    if other:
        print(f"  其他（{len(other)}）: " + ", ".join(other))


def sweep(key: str, bypass: bool, models: list, sleep_s: float):
    print(f"\n== 逐个实测 {len(models)} 个型号（每个只花 1 次它自己的日额度）==")
    body = {"contents": [{"parts": [{"text": "ok"}]}]}
    rows = []
    for m in models:
        code, payload = call(f"/models/{m}:generateContent", key, bypass, "POST", body, timeout=60)
        verdict, detail = classify(code, payload)
        rows.append((m, verdict, detail))
        print(f"  {verdict:<12} {m:<40} {detail}")
        time.sleep(sleep_s)
    print("\n== 汇总 ==")
    buckets = ("可用", "429（待判：上限0 还是真限流）", "服务端忙", "型号对新用户已关",
               "参数不适用", "无权限", "传输失败")
    for bucket in buckets:
        hit = [r for r in rows if r[1] == bucket]
        if hit:
            print(f"  {bucket}（{len(hit)}）: " + ", ".join(r[0] for r in hit))
    for r in rows:
        if r[1] not in buckets:
            print(f"  {r[1]}: {r[0]} — {r[2]}")
    pending = [r[0] for r in rows if r[1].startswith("429")]
    if pending:
        print("\n  上面这批 429 还判不了是「上限 0」还是「真限流」，跑：")
        print("      python gemini探针.py --recheck " + ",".join(pending))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", help="发一条真实提示词")
    ap.add_argument("--model", default="gemini-4-hydrogen")
    ap.add_argument("--probe-limit", metavar="MODEL", help="连打撞 429，读该模型真实上限")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--list", action="store_true", help="只列模型")
    ap.add_argument("--sweep", action="store_true", help="逐个实测哪些型号真能调")
    ap.add_argument("--recheck", metavar="MODEL[,MODEL…]", help="冷却后复打这些 429 型号，判「上限0」还是「真限流」")
    ap.add_argument("--wait", type=float, default=65.0, help="--recheck 每发之间等几秒")
    ap.add_argument("--sleep", type=float, default=2.0, help="--sweep 时每发之间等几秒")
    args = ap.parse_args()

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("没有 GEMINI_API_KEY。先 export GEMINI_API_KEY='你的key'（setx 的要重开终端才生效）")
        sys.exit(2)
    print(f"key = {mask(key)}")

    bypass = probe_reach(key)
    if bypass is None:
        print("\n两条出口都不通：浏览器能进 AI Studio ≠ 终端能调 API。"
              "把终端指到浏览器用的同一个出口，或确认节点没把 googleapis 域名单独掐掉。")
        sys.exit(1)

    if args.recheck:
        recheck(key, bypass, [m.strip() for m in args.recheck.split(",") if m.strip()], args.wait)
        return

    models = list_models(key, bypass)
    if args.list:
        return
    if args.sweep:
        sweep(key, bypass, models, args.sleep)
        return
    if args.ask:
        ask(key, bypass, args.model, args.ask)
    if args.probe_limit:
        probe_limit(key, bypass, args.probe_limit, args.n)


if __name__ == "__main__":
    main()
