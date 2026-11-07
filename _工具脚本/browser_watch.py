#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""browser_watch.py —— 浏览器层每周补抓(2026-10-21 新增,用户拍板"做,每周一次")

补齐的缺口:curl 拿不到的论坛源(Cloudflare 403 / Discuz 要 auth key),见交接稿 §七.7。
做法:Node + patchright 无头 chromium 抓页面抽帖子链接(browser_fetch.mjs),
本脚本负责去重、按台账 12 列格式入账、打 HOT/聚焦标记(全部复用 scene_monitor 的逻辑)。

和 curl 源的关系:**互补,不重复**:这些站点在源登记表里是 enabled=0 的点名拒用行,
浏览器层只负责"每周把能看到的帖子补进台账",不替换原有登记;实测能稳定出条目的,
再在源登记表补一行 `bw_*`(kind=browser)说明来路。

用法:
  py -3 _工具脚本/browser_watch.py            # 跑全部站点并入账
  py -3 _工具脚本/browser_watch.py --dry-run  # 只抓+显示会入什么,不写台账
  py -3 _工具脚本/browser_watch.py --only psxplace,gtforums
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_monitor as sm  # 复用 key_of/cell/is_hot/focus_of/arrival_of/LEDGER,保证口径一致

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TOOLS = os.path.dirname(os.path.abspath(__file__))
FETCHER = os.path.join(TOOLS, "browser_fetch.mjs")
NODE_BASE = r"f:/rsshub-npm"          # patchright 装在那(浏览器二进制也已下载)

# 站点清单:全部来自源登记表里实测 403/要登录态的点名行,一个都不凭空加。
# proxy=True 的走本机 127.0.0.1:7897(国外站直连被 RST,实测;国内站直连更快)。
# link_pattern 是每站自定义的帖子链接正则(各论坛程序不同:XenForo/Discuz/Discourse/门户站)。
SITES = [
    {"id": "bw_a9vg", "name": "A9VG 电玩部落(中文游戏媒体,Discuz 要 auth key)",
     "url": "https://www.a9vg.com/", "max_links": 30, "wait_ms": 3500, "proxy": False,
     "link_pattern": r"/article/\d+"},
    {"id": "bw_mydigit", "name": "MYDIGIT 数码之家论坛-精华区(Discuz,要 auth key)",
     "url": "https://www.mydigit.cn/forum.php?mod=guide&view=digest", "max_links": 25, "wait_ms": 3000, "proxy": False,
     "link_pattern": r"thread-\d+-\d+-\d+\.html"},
    {"id": "bw_psxplace", "name": "PSX-Place(PS Vita/PS3 自制场景,curl 403)",
     "url": "https://www.psx-place.com/forums/", "max_links": 30, "wait_ms": 4000, "proxy": True,
     "link_pattern": r"/threads/"},
    {"id": "bw_pcsx2forum", "name": "PCSX2 官方论坛(curl 403)",
     "url": "https://forums.pcsx2.net/", "max_links": 25, "wait_ms": 4000, "proxy": True,
     "link_pattern": r"/threads/"},
    {"id": "bw_gtforums", "name": "GTForums(Gran Turismo 论坛,curl 403/直连 RST)",
     "url": "https://gtforums.net/forum/", "max_links": 25, "wait_ms": 4000, "proxy": True,
     "link_pattern": r"/threads/|/topic/"},
    {"id": "bw_linuxdo", "name": "linux.do 中文 Linux 社区(Cloudflare 403)",
     "url": "https://linux.do/latest", "max_links": 30, "wait_ms": 5000, "proxy": True,
     "link_pattern": r"/t/"},
]


def run_fetcher(sites):
    tmp = tempfile.mkdtemp(prefix="bwatch_", dir=TOOLS)
    sj, oj = os.path.join(tmp, "sites.json"), os.path.join(tmp, "out.json")
    with open(sj, "w", encoding="utf-8") as fh:
        json.dump(sites, fh, ensure_ascii=False)
    r = subprocess.run(["node", FETCHER, sj, oj], capture_output=True, cwd=NODE_BASE)
    if r.returncode != 0 or not os.path.exists(oj):
        print("X node 抓取器失败 rc=%s %s" % (r.returncode, r.stderr.decode("utf-8", "replace")[:300]))
        return None
    with open(oj, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    sites = SITES
    if args.only:
        keep = {x.strip() for x in args.only.split(",") if x.strip()}
        sites = [s for s in sites if s["id"] in keep]

    print("浏览器层补抓 %d 个站点(patchright 无头 chromium)..." % len(sites))
    data = run_fetcher(sites)
    if data is None:
        return 1

    seen = sm.load_seen()          # 台账已有 key,复用 scene_monitor 的去重集合
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = []
    print("=" * 74)
    for s in sites:
        r = data.get(s["id"]) or {}
        if not r.get("ok"):
            print("%-14s FAIL %s" % (s["id"], (r.get("error") or "?")[:90]))
            continue
        items = r.get("items") or []
        new = 0
        for it in items:
            k = sm.key_of(it)
            if k in seen:
                continue
            seen.add(k)
            fresh.append((s, it, k))
            new += 1
        print("%-14s OK  抓到 %2d 条,新 %2d 条  | %s" % (s["id"], len(items), new, (r.get("title") or "")[:50]))
    print("=" * 74)

    if args.dry_run:
        for s, it, _ in fresh[:40]:
            print("  [dry] %s | %s" % (s["id"], it["title"][:70]))
        print("dry-run:共 %d 条新条目,未写台账" % len(fresh))
        return 0

    if not fresh:
        print("没有新条目")
        return 0
    lines = []
    for s, it, k in fresh:
        lines.append("\t".join([
            sm.cell(k), sm.cell(now), sm.cell(s["id"]), sm.cell("browser"), sm.cell(s["name"]),
            sm.cell(sm.norm_date(it.get("pub") or it.get("date") or "")),
            sm.cell(it.get("title", "")), sm.cell(it.get("url", "")),
            sm.cell("HOT" if sm.is_hot(it.get("title", ""), it.get("url", ""), s["name"], "", "browser") else ""),
            sm.cell("SUSPECT_PIRACY_WORDING" if sm.SUSPICIOUS.search(it.get("title", "")) else ""),
            sm.arrival_of(it.get("title", ""), it.get("url", "")),
            sm.focus_of(it.get("title", ""), it.get("url", ""), s["name"], s["id"]),
        ]))
    with open(sm.LEDGER, "a", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines) + "\n")
    # 调度日志留痕(和 daily_run 的章节风格一致)
    with open(os.path.join(os.path.dirname(sm.LEDGER), "_schedule.log"), "a", encoding="utf-8") as fh:
        fh.write("\n==== %s browser_watch.py ====\n" % dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        fh.write("浏览器层补抓:%d 站 / 新入账 %d 条\n" % (len(sites), len(fresh)))
        for s in sites:
            r = data.get(s["id"]) or {}
            fh.write("  %-14s %s\n" % (s["id"], "OK %d 条" % len(r.get("items") or []) if r.get("ok") else "FAIL"))
    print("已入账 %d 条(kind=browser,源=%s)" % (len(fresh), ",".join(sorted({s["id"] for s, _, _ in fresh}))))


if __name__ == "__main__":
    sys.exit(main())
