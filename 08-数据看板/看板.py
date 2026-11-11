#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看板.py —— 把本库已爬到的资讯/游戏/仓库数据做成一个本地网页台(2026-11-04 新增)

读侧:数据一律现读现切(按文件 mtime 缓存),不写任何台账,不生成副本。
事实源就是各条线的 .tsv / .json / .md,前端只是它们的一个视图。
唯一的写路径(2026-11-05 起):「网盘」页签填 cookie / 探测 / 切活跃 / 删账号,
POST /api/netdisk/action → 转交 _工具脚本\网盘账号台.py 的 do_action();看板自己
不解密凭据、不打印凭据,而且 --lan(绑 0.0.0.0)时这一路直接拒收。

用法:
  py -3 08-数据看板/看板.py                      # 127.0.0.1:8090(只本机能看,网盘页可写)
  py -3 08-数据看板/看板.py --lan                # 绑 0.0.0.0,局域网设备可读(网盘页只读)
  py -3 08-数据看板/看板.py --lan --port 8098 --open
"""
import json
import os
import re
import sys
import time
import socket
import argparse
import datetime as dt
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

P = lambda *a: os.path.join(ROOT, *(a))  # noqa: E731

_cache = {}


def _read_text(rel):
    """按 mtime+size 缓存读文本;文件不存在返回 None。"""
    path = P(rel)
    if not os.path.isfile(path):
        return None
    st = os.stat(path)
    sig = (st.st_mtime_ns, st.st_size)
    key = ("txt", rel)
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    _cache[key] = (sig, text)
    return text


def tsv_rows(rel):
    """TSV -> [{列名: 值}],保留原始表头顺序于 _cols。"""
    path = P(rel)
    if not os.path.isfile(path):
        return [], rel
    st = os.stat(path)
    key = ("tsv", rel)
    hit = _cache.get(key)
    if hit and hit[0] == (st.st_mtime_ns, st.st_size):
        return hit[1], rel
    lines = _read_text(rel).splitlines()
    if not lines:
        return [], rel
    cols = lines[0].split("\t")
    rows = []
    for ln in lines[1:]:
        if not ln.strip():
            continue
        parts = ln.split("\t")
        row = {}
        for i, c in enumerate(cols):
            row[c] = parts[i] if i < len(parts) else ""
        row["_cols"] = cols
        rows.append(row)
    _cache[key] = ((st.st_mtime_ns, st.st_size), rows)
    return rows, rel


def json_load(rel):
    text = _read_text(rel)
    if text is None:
        return None
    key = ("json", rel)
    st = os.stat(P(rel))
    sig = (st.st_mtime_ns, st.st_size)
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        obj = json.loads(text)
    except Exception:
        obj = None
    _cache[key] = (sig, obj)
    return obj


def human_bytes(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if n >= 100 else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return ""


def to_bytes(val):
    """把 '83788' / '3.9' / '1.2GB' 这类混合写法归一成字节(未知 0)。"""
    if val is None:
        return 0
    s = str(val).strip().replace(",", "").replace("≈", "")
    if not s:
        return 0
    m = re.match(r"^([\d.]+)\s*(KB|MB|GB|TB|M|G|K|B)?$", s, re.I)
    if not m:
        return 0
    try:
        n = float(m.group(1))
    except ValueError:
        return 0
    unit = (m.group(2) or "").upper()
    mult = {"B": 1, "K": 1024, "KB": 1024, "M": 1024 ** 2, "MB": 1024 ** 2,
            "G": 1024 ** 3, "GB": 1024 ** 3, "T": 1024 ** 4, "TB": 1024 ** 4}.get(unit)
    if mult is None:
        # 纯数字:位数 <=3 当作 MB 的写法(PortMaster 清单里的 mb 列),否则当字节
        return int(n * 1024 * 1024) if n < 10000 else int(n)
    return int(n * mult)


def day_of(s):
    if not s:
        return ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", str(s))
    return m.group(1) if m else ""


def base_row(ds, name, title="", platform="", lic="", size="", needs="", status="",
             date="", url="", local="", note="", x=None, expect=0):
    return {"ds": ds, "name": name, "title": title or name, "platform": platform,
            "license": lic, "size": size, "bytes": to_bytes(size) or to_bytes(x.get("bytes") if x else 0),
            "needs": needs, "status": status, "date": date, "url": url, "local": local,
            "note": note, "expect": expect, "x": x or {}}


def file_index(rel_dir):
    """目录 -> {文件名: 相对路径}(按目录 mtime 缓存)。用来把台账里的包名落到真实分层目录。"""
    base = P(rel_dir)
    if not os.path.isdir(base):
        return {}
    sig = (rel_dir, os.stat(base).st_mtime_ns, len(os.listdir(base)))
    key = ("idx", rel_dir)
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    idx = {}
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for fn in filenames:
            idx.setdefault(fn.lower(), os.path.relpath(os.path.join(dirpath, fn), ROOT).replace("\\", "/"))
    _cache[key] = (sig, idx)
    return idx


# ---------------------------------------------------------------- 资讯

def load_news():
    rows, _ = tsv_rows("06-资讯监控/台账.tsv")
    out = []
    for r in rows:
        seen = day_of(r.get("first_seen_utc"))
        pub = day_of(r.get("pub"))
        out.append({
            "key": r.get("key", ""),
            "date": pub or seen,
            "seen": seen,
            "pub": pub,
            "source_id": r.get("source_id", ""),
            "source": r.get("source", ""),
            "kind": r.get("kind", ""),
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "hot": r.get("flag_hot", ""),
            "note": r.get("flag_note", ""),
            "arrival": r.get("flag_arrival", ""),
            "focus": r.get("flag_focus", ""),
        })
    out.sort(key=lambda d: (d["date"], d["seen"]), reverse=True)
    return out


def news_facets():
    hit = _cache.get("news_facets_sig")
    news = load_news()
    sig = len(news)
    if hit and hit[0] == sig:
        return hit[1]
    by_src, by_kind, by_day = {}, {}, {}
    hot = arr = foc = 0
    for n in news:
        s = n["source_id"] or "-"
        rec = by_src.setdefault(s, {"source_id": s, "source": n["source"], "count": 0,
                                    "hot": 0, "last": "", "kind": n["kind"], "url": ""})
        rec["count"] += 1
        if n["hot"]:
            rec["hot"] += 1
        if not rec["last"] or n["date"] > rec["last"]:
            rec["last"] = n["date"]
        if n["source"]:
            rec["source"] = n["source"]
        by_kind[n["kind"] or "-"] = by_kind.get(n["kind"] or "-", 0) + 1
        if n["seen"]:
            by_day[n["seen"]] = by_day.get(n["seen"], 0) + 1
        hot += 1 if n["hot"] else 0
        arr += 1 if n["arrival"] else 0
        foc += 1 if n["focus"] else 0
    facets = {
        "total": len(news),
        "hot": hot, "arrival": arr, "focus": foc,
        "sources": sorted(by_src.values(), key=lambda d: -d["count"]),
        "kinds": sorted(({"kind": k, "count": v} for k, v in by_kind.items()), key=lambda d: -d["count"]),
        "days": sorted(({"day": k, "count": v} for k, v in by_day.items()), key=lambda d: d["day"]),
        "date_min": min((n["date"] for n in news if n["date"]), default=""),
        "date_max": max((n["date"] for n in news if n["date"]), default=""),
    }
    _cache["news_facets_sig"] = (sig, facets)
    return facets


def api_news(q):
    news = load_news()
    term = (q.get("q", [""])[0] or "").strip().lower()
    src = q.get("source", [""])[0]
    kind = q.get("kind", [""])[0]
    flag = q.get("flag", [""])[0]
    since = q.get("since", [""])[0]
    until = q.get("until", [""])[0]
    order = q.get("order", ["date"])[0]

    rows = news
    if flag == "hot":
        rows = [n for n in rows if n["hot"]]
    elif flag == "arrival":
        rows = [n for n in rows if n["arrival"]]
    elif flag == "focus":
        rows = [n for n in rows if n["focus"]]
    elif flag == "plain":
        rows = [n for n in rows if not n["hot"] and not n["arrival"]]
    if src:
        rows = [n for n in rows if n["source_id"] == src]
    if kind:
        rows = [n for n in rows if n["kind"] == kind]
    if since:
        rows = [n for n in rows if n["date"] >= since]
    if until:
        rows = [n for n in rows if n["date"] <= until]
    if term:
        rows = [n for n in rows if term in (n["title"] + " " + n["url"] + " " + n["note"] + " " + n["focus"]).lower()]
    if order == "seen":
        rows = sorted(rows, key=lambda d: (d["seen"], d["date"]), reverse=True)
    elif order == "date_asc":
        rows = sorted(rows, key=lambda d: (d["date"], d["seen"]))

    limit, offset = _paging(q, 200, 1000)
    return {"total": len(rows), "offset": offset, "limit": limit,
            "rows": rows[offset:offset + limit]}


def _paging(q, default, cap):
    try:
        limit = int(q.get("limit", [default])[0])
    except ValueError:
        limit = default
    try:
        offset = int(q.get("offset", ["0"])[0])
    except ValueError:
        offset = 0
    limit = max(1, min(limit, cap))
    return limit, max(0, offset)


# ---------------------------------------------------------------- 游戏

def games_datasets():
    """每个数据集 -> (标签, 生成函数)。加新表只动这里。"""
    return [
        ("pm_r36s", "PortMaster R36S 全清单", "04-游戏资源库/公版与开源游戏/portmaster_r36s_全清单.tsv", games_pm_r36s),
        ("pm_pool", "ports 全量合法池(本地包)", "04-游戏资源库/公版与开源游戏/ports全量合法池/_manifest.tsv", games_pm_pool),
        ("pm_watch", "PortMaster 端口快照(监控)", "06-资讯监控/PortMaster端口快照.tsv", games_pm_watch),
        ("hot", "爆款收录(本地成品包)", "04-游戏资源库/爆款收录/收录台账.tsv", games_hot),
        ("rescue", "下架抢救(快照存档)", "04-游戏资源库/下架抢救/收录台账.tsv", games_rescue),
        ("assets", "免费素材", "04-游戏资源库/公版与开源游戏/免费素材/免费素材台账.tsv", games_assets),
        ("ps5", "PS5 移植商店(RecompStore 目录)", "06-资讯监控/PS5移植商店/catalog.json", games_ps5),
        ("major", "移植大作(端口项目)", "06-资讯监控/移植大作/移植大作台账.tsv", games_major),
    ]


def games_pm_r36s():
    rows, rel = tsv_rows("04-游戏资源库/公版与开源游戏/portmaster_r36s_全清单.tsv")
    out = []
    for r in rows:
        if r.get("name", "").startswith("#"):
            continue
        out.append(base_row("pm_r36s", r.get("name", ""), r.get("title", ""),
                            platform=r.get("arch", ""), lic=r.get("license", ""),
                            size=(r.get("mb", "") + " MB") if r.get("mb") else "",
                            needs="要自备数据" if r.get("game_data") == "needs_data" else "公版/自带",
                            status=r.get("cfw_only", ""),
                            url=r.get("url", ""), note=r.get("desc", ""),
                            x={"genres": r.get("genres", ""), "downloads": r.get("downloads", ""),
                              "porter": r.get("porter", ""), "rtr": r.get("rtr", ""),
                              "install": r.get("inst", ""), "md5": r.get("md5", "")}))
    return out


def games_pm_pool():
    rows, rel = tsv_rows("04-游戏资源库/公版与开源游戏/ports全量合法池/_manifest.tsv")
    d = "04-游戏资源库/公版与开源游戏/ports全量合法池"
    out = []
    for r in rows:
        pkg = r.get("package", "")
        ok = r.get("md5_want", "") and r.get("md5_want", "") == r.get("md5_got", "")
        out.append(base_row("pm_pool", pkg, platform="PortMaster",
                            status=r.get("status", ""),
                            size=human_bytes(r.get("bytes", "")),
                            needs="要自备数据" if _pool_needs(pkg) else "",
                            date=day_of(r.get("url", "")), url=r.get("url", ""),
                            local="%s/%s" % (d, pkg), expect=1,
                            x={"md5_want": r.get("md5_want", ""), "md5_got": r.get("md5_got", ""),
                               "校验": "OK" if ok else "不一致"}))
    return out


def _pool_needs(pkg):
    """全清单里同名包是否要求自备游戏数据。"""
    cache = _cache.get("pool_needs")
    if not cache:
        table = {}
        for r in games_pm_r36s():
            table[r["name"].lower() + ".zip"] = r["needs"] == "要自备数据"
        _cache["pool_needs"] = table
        cache = table
    return cache.get(pkg.lower(), False)


def games_pm_watch():
    rows, _ = tsv_rows("06-资讯监控/PortMaster端口快照.tsv")
    out = []
    for r in rows:
        out.append(base_row("pm_watch", r.get("path", ""), platform="PortMaster",
                            size=human_bytes(r.get("size", "")),
                            date=r.get("last_change", ""),
                            note="首次见 %s / 末次见 %s" % (r.get("first_seen", ""), r.get("last_seen", "")),
                            x={"sha": r.get("sha", ""), "first_seen": r.get("first_seen", ""),
                               "last_seen": r.get("last_seen", "")}))
    return out


def games_hot():
    rows, _ = tsv_rows("04-游戏资源库/爆款收录/收录台账.tsv")
    out = []
    for r in rows:
        out.append(base_row("hot", r.get("asset", ""), r.get("title", ""),
                            platform=r.get("kind", ""), lic="",
                            size=human_bytes(r.get("bytes", "")),
                            needs="要自备数据" if r.get("needs_data") in ("是", "1", "yes") else "",
                            status=r.get("verify", ""), date=day_of(r.get("fetched_utc", "")),
                            url=r.get("url", ""), local=r.get("dest", ""), expect=1,
                            x={"repo": r.get("repo", ""), "tag": r.get("tag", ""),
                               "id": r.get("id", ""), "sha256_local": (r.get("sha256_local", "") or "")[:16] + "…",
                               "sha256_upstream": (r.get("sha256_upstream", "") or "")[:16] + "…"}))
    return out


def games_rescue():
    rows, _ = tsv_rows("04-游戏资源库/下架抢救/收录台账.tsv")
    out = []
    for r in rows:
        out.append(base_row("rescue", r.get("name") or r.get("id", ""),
                            platform=r.get("category", ""),
                            size=human_bytes(r.get("bytes", "")),
                            status=r.get("status", ""), date=day_of(r.get("first_seen_utc", "")),
                            url=r.get("url", ""), local=r.get("local_path", ""), expect=1,
                            note=r.get("priority", ""),
                            x={"kind": r.get("kind", ""), "slug": r.get("slug", ""),
                               "commit": r.get("commit", ""), "verify": r.get("verify", ""),
                               "source_id": r.get("source_id", ""), "id": r.get("id", "")}))
    return out


def games_assets():
    rows, _ = tsv_rows("04-游戏资源库/公版与开源游戏/免费素材/免费素材台账.tsv")
    idx = file_index("04-游戏资源库/公版与开源游戏/免费素材")
    out = []
    for r in rows:
        fn = r.get("file", "")
        out.append(base_row("assets", r.get("port", ""), r.get("file", ""),
                            size=human_bytes(r.get("bytes", "")), date=day_of(r.get("fetched_utc", "")),
                            url=r.get("url", ""), note=r.get("install_hint", ""),
                            local=idx.get(fn.lower(), ""), expect=1,
                            x={"file": fn, "sha256": (r.get("sha256", "") or "")[:16] + "…"}))
    return out


def games_ps5():
    cat = json_load("06-资讯监控/PS5移植商店/catalog.json")
    if not cat:
        return []
    out = []
    for bucket in ("apps", "newerStoreApps", "v2Apps", "comingSoon", "comingSoonV2"):
        for a in cat.get(bucket, []) or []:
            if not isinstance(a, dict):
                continue
            src = a.get("source") or {}
            repo = src.get("repo", "")
            out.append(base_row("ps5", a.get("name", ""), a.get("name", ""),
                                platform=a.get("kind", ""), lic=a.get("license", ""),
                                size=a.get("size", ""),
                                needs=a.get("needs", ""),
                                status="上架" if bucket != "comingSoon" else "预告",
                                date=day_of(a.get("released", "")),
                                url="https://github.com/" + repo if repo else (a.get("url") or ""),
                                note=a.get("blurb", ""),
                                x={"id": a.get("id", ""), "author": a.get("author", ""),
                                   "bucket": bucket, "version": a.get("version", ""),
                                   "repo": repo, "asset": src.get("asset", ""),
                                   "description": (a.get("description") or "")[:400]}))
    return out


def games_major():
    rows, _ = tsv_rows("06-资讯监控/移植大作/移植大作台账.tsv")
    out = []
    for r in rows:
        out.append(base_row("major", r.get("game", ""), r.get("game", ""),
                            platform="%s → %s" % (r.get("source_platform", ""), r.get("targets", "")),
                            size="", status=r.get("layer", ""),
                            date=r.get("last_activity", ""), url=r.get("url", ""),
                            needs="要自备本体" if r.get("needs_own_copy") == "1" else "",
                            note=r.get("note", ""),
                            x={"repo": r.get("repo", ""), "stars": r.get("stars", ""),
                               "version": r.get("version", ""), "origin": r.get("origin", ""),
                               "thread": r.get("thread", "")}))
    return out


def load_games():
    key = "games_all"
    sig = _sig([d[2] for d in games_datasets()])
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    out = []
    for _, _, _, fn in games_datasets():
        try:
            out.extend(fn())
        except Exception as e:  # 单表坏了不拖垮整台
            out.append(base_row("error", "读取失败", note="%s: %s" % (_, e)))
    _cache[key] = (sig, out)
    return out


# ---------------------------------------------------------------- 库(仓库/源线)

def repos_datasets():
    return [
        ("clone", "已 clone 到本地仓库", "02-模拟器库/已clone仓库/README_inventory.md", repos_clone),
        ("legal", "合法收录登记表", "06-资讯监控/合法收录登记表.tsv", repos_legal),
        ("s2repo", "Switch2 模拟器仓库登记", "06-资讯监控/Switch2模拟器/仓库登记表.tsv", repos_switch2),
        ("s2fetch", "Switch2 抓取台账", "06-资讯监控/Switch2模拟器/抓取台账.tsv", repos_s2fetch),
        ("s2bundle", "Switch2 bundle 台账", "06-资讯监控/Switch2模拟器/bundle台账.tsv", repos_s2bundle),
        ("ps5repo", "PS5 移植商店仓库底账", "06-资讯监控/PS5移植商店/仓库底账.tsv", repos_ps5),
        ("ps5asset", "PS5 成品包获取台账", "06-资讯监控/PS5移植商店/获取台账.tsv", repos_ps5asset),
        ("rescue_reg", "下架抢救登记表", "06-资讯监控/下架抢救登记表.tsv", repos_rescue),
    ]


def repos_clone():
    text = _read_text("02-模拟器库/已clone仓库/README_inventory.md")
    if not text:
        return []
    out = []
    cat = ""
    for ln in text.splitlines():
        if ln.startswith("## "):
            cat = ln[3:].strip()
            if cat == "汇总":
                break
            continue
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 5 or set(cells[0]) <= set("-: ") or cells[0] == "分类":
            continue
        category, name, size, commit, up = [c.strip("` ").strip() for c in cells[:5]]
        local = "02-模拟器库/已clone仓库/%s/%s" % (category, name)
        out.append(base_row("clone", name, platform=cat, size=size, date=commit,
                            url=up if up.startswith("http") else ("https://" + up if up not in ("-", "") else ""),
                            local=local, expect=1,
                            note="" if os.path.isdir(P(local)) else "本地目录缺失",
                            x={"分类": category, "体积": size, "最近提交": commit, "上游": up}))
    return out


def repos_legal():
    rows, _ = tsv_rows("06-资讯监控/合法收录登记表.tsv")
    out = []
    for r in rows:
        out.append(base_row("legal", r.get("name", ""), r.get("name", ""),
                            platform=r.get("kind", ""), status="启用" if r.get("enabled") == "1" else "停用",
                            needs="要自备数据" if r.get("needs_data") == "是" else "",
                            url="https://github.com/" + r.get("repo", "") if r.get("repo") else "",
                            note=r.get("note", ""),
                            x={"id": r.get("id", ""), "repo": r.get("repo", ""), "filter": r.get("filter", ""),
                               "max_mb": r.get("max_mb", ""), "tag": r.get("tag", "")}))
    return out


def repos_switch2():
    rows, _ = tsv_rows("06-资讯监控/Switch2模拟器/仓库登记表.tsv")
    out = []
    for r in rows:
        out.append(base_row("s2repo", r.get("repo", ""), r.get("repo", ""),
                            platform=r.get("tier", ""), status="启用" if r.get("enable") == "1" else "停用",
                            url="https://github.com/" + r.get("repo", ""),
                            note=r.get("note", ""),
                            x={"tier": r.get("tier", ""), "enable": r.get("enable", ""), "note": r.get("note", "")}))
    return out


def repos_s2fetch():
    rows, _ = tsv_rows("06-资讯监控/Switch2模拟器/抓取台账.tsv")
    out = []
    for r in rows:
        out.append(base_row("s2fetch", r.get("repo", ""), r.get("repo", ""),
                            platform=r.get("tier", ""), size=human_bytes(r.get("worktree_bytes", "")),
                            date=r.get("commit_at", ""), url=r.get("url", ""),
                            local="06-资讯监控/Switch2模拟器/源码/" + r.get("repo", "").replace("/", "__"),
                            expect=1, note=r.get("note", ""),
                            x={"branch": r.get("branch", ""), "commit": (r.get("commit", "") or "")[:10],
                               "stars": r.get("stars", ""), "license": r.get("license", ""),
                               "worktree_files": r.get("worktree_files", ""),
                               "gitdir_bytes": human_bytes(r.get("gitdir_bytes", "")),
                               "suspect_files": r.get("suspect_files", ""),
                               "largest_file": r.get("largest_file", ""),
                               "fetched_at": r.get("fetched_at", "")}))
    return out


def repos_s2bundle():
    rows, _ = tsv_rows("06-资讯监控/Switch2模拟器/bundle台账.tsv")
    out = []
    for r in rows:
        out.append(base_row("s2bundle", r.get("file", ""), r.get("repo", ""),
                            size=human_bytes(r.get("bytes", "")), status=r.get("verify", ""),
                            date=day_of(r.get("made_at", "")),
                            local="06-资讯监控/Switch2模拟器/整仓bundle/%s" % r.get("file", ""), expect=1,
                            note=r.get("head", ""),
                            x={"repo": r.get("repo", ""), "head": (r.get("head", "") or "")[:10],
                               "sha256": (r.get("sha256", "") or "")[:16] + "…", "made_at": r.get("made_at", "")}))
    return out


def repos_ps5():
    rows, _ = tsv_rows("06-资讯监控/PS5移植商店/仓库底账.tsv")
    out = []
    for r in rows:
        out.append(base_row("ps5repo", r.get("repo", ""), r.get("repo", ""),
                            size="", date=day_of(r.get("pushed", "")),
                            url="https://github.com/" + r.get("repo", ""),
                            lic=r.get("license", ""), note=r.get("desc", ""),
                            x={"star": r.get("star", ""), "pushed": r.get("pushed", ""),
                               "license": r.get("license", ""), "desc": r.get("desc", "")}))
    return out


def repos_ps5asset():
    rows, _ = tsv_rows("06-资讯监控/PS5移植商店/获取台账.tsv")
    idx = file_index("06-资讯监控/PS5移植商店/成品包")
    out = []
    for r in rows:
        asset = r.get("asset", "")
        # 台账没有独立 verify 列,校验结论写在 note 里(如 "... verify=MISMATCH"),拆出来给详情面板
        verify = (r.get("verify") or "").strip()
        if not verify:
            for tok in (r.get("note") or "").split():
                if tok.startswith("verify="):
                    verify = tok.split("=", 1)[1]
        out.append(base_row("ps5asset", asset or r.get("name", ""), r.get("name", ""),
                            platform=r.get("category", ""),
                            size=human_bytes(r.get("bytes", "")),
                            status=r.get("audit", ""),
                            needs="要自备数据" if r.get("needs_own_copy") == "1" else "",
                            url="https://github.com/" + r.get("repo", "") if r.get("repo") else "",
                            local=idx.get(asset.lower(), ""), expect=1,
                            note=r.get("needs", ""),
                            x={"repo": r.get("repo", ""), "digest": (r.get("digest", "") or "")[:16] + "…",
                               "verify": verify, "category": r.get("category", "")}))
    return out


def repos_rescue():
    rows, _ = tsv_rows("06-资讯监控/下架抢救登记表.tsv")
    out = []
    for r in rows:
        out.append(base_row("rescue_reg", r.get("name", ""), r.get("name", ""),
                            platform=r.get("category", ""), status=r.get("priority", ""),
                            url=r.get("watch_url", ""), note=r.get("note", ""),
                            x={"id": r.get("id", ""), "action": r.get("action", ""),
                               "category": r.get("category", ""), "priority": r.get("priority", "")}))
    return out


def load_repos():
    key = "repos_all"
    sig = _sig([d[2] for d in repos_datasets()])
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    out = []
    for _, _, _, fn in repos_datasets():
        try:
            out.extend(fn())
        except Exception as e:
            out.append(base_row("error", "读取失败", note="%s: %s" % (_, e)))
    _cache[key] = (sig, out)
    return out


def _sig(rels):
    s = []
    for rel in rels:
        p = P(rel)
        if os.path.isfile(p):
            st = os.stat(p)
            s.append((rel, st.st_mtime_ns, st.st_size))
        else:
            s.append((rel, 0, 0))
    return tuple(s)


# ---------------------------------------------------------------- 移植工厂(SQLite 状态库)

FACTORY_DB = "07-移植工厂/state/factory.db"


def _factory_conn():
    """只读打开移植工厂的 SQLite;文件缺失或打不开返回 None(看板不建库、不写库、不建 -wal)。"""
    ap = P(FACTORY_DB)
    if not os.path.isfile(ap):
        return None
    try:
        import sqlite3
        con = sqlite3.connect("file:" + ap.replace("\\", "/") + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


def _j(v):
    """detail/fingerprint 这类列是 JSON 文本;解析失败原样带出来,不吞。"""
    if not v:
        return {}
    try:
        d = json.loads(v)
    except Exception:
        return {"raw": str(v)[:300]}
    return d if isinstance(d, dict) else {"value": d}


def _ts(v):
    """SQLite 里存的是 UTC ISO;截到秒,换成 'YYYY-MM-DD HH:MM:SS' 好读。"""
    return str(v or "").replace("T", " ")[:19]


def _short(v, n=160):
    s = " ".join(str(v or "").split())
    return s[:n] + ("…" if len(s) > n else "")


def factory_datasets():
    """(代号, 标签, SQL 取数函数)。加新表只动这里。"""
    return [
        ("pf_jobs", "接单(移植任务)", f_pf_jobs),
        ("pf_games", "收件登记(输入二进制)", f_pf_games),
        ("pf_runs", "静态分析运行", f_pf_runs),
        ("pf_modules", "函数级判定", f_pf_modules),
        ("pf_attempts", "AI 请求尝试", f_pf_attempts),
        ("pf_gates", "闸门结果", f_pf_gates),
        ("pf_stages", "流水线阶段", f_pf_stages),
        ("pf_artifacts", "制品(成品包)", f_pf_artifacts),
        ("pf_devices", "设备", f_pf_devices),
        ("pf_events", "动作流水", f_pf_events),
    ]


def f_pf_jobs(con):
    gname = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM games")}
    dname = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM devices")}
    out = []
    for r in con.execute("SELECT * FROM jobs ORDER BY updated_at DESC"):
        out.append(base_row("pf_jobs", r["id"], gname.get(r["game_id"], r["game_id"]),
                            platform=dname.get(r["device_id"], r["device_id"] or "-"),
                            status=r["status"], date=_ts(r["updated_at"]),
                            local=r["workdir"], expect=1,
                            note="配方 " + str(r["recipe_id"]),
                            x={"game_id": r["game_id"], "device_id": r["device_id"],
                               "recipe_id": r["recipe_id"], "input_path": r["input_path"],
                               "接单": _ts(r["created_at"])}))
    return out


def f_pf_games(con):
    out = []
    for r in con.execute("SELECT * FROM games ORDER BY created_at DESC"):
        fp = _j(r["fingerprint"])
        det = fp.get("detail") if isinstance(fp.get("detail"), dict) else {}
        out.append(base_row("pf_games", r["id"], r["name"], platform=fp.get("format", ""),
                            date=_ts(r["created_at"]), local=r["root_path"], expect=1,
                            note="%s / %s / %s B" % (fp.get("format", "?"), fp.get("arch", "?"),
                                                     fp.get("size", "?")),
                            x={"kind": r["kind"], "hash_policy": fp.get("hash_policy", ""),
                               "sha256": _short(fp.get("sha256", ""), 24),
                               "指纹": _short(det, 200)}))
    return out


def f_pf_runs(con):
    gname = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM games")}
    out = []
    for r in con.execute("SELECT * FROM research_runs ORDER BY updated_at DESC"):
        det = _j(r["detail"])
        out.append(base_row("pf_runs", r["id"], gname.get(r["game_id"], r["game_id"]),
                            platform=r["target"], status=r["status"],
                            date=_ts(r["updated_at"]), local=r["workdir"], expect=1,
                            note="挖 %s 个函数 / 可选 %s / 已选 %s" %
                                 (det.get("discovered", "?"), det.get("eligible", "?"),
                                  det.get("selected", "?")),
                            x={"source_path": r["source_path"],
                               "source_sha256": _short(r["source_sha256"], 24),
                               "analysis_sha256": _short(r["analysis_sha256"], 24),
                               "整款游戏已验收": "是" if det.get("full_game_verified") else "否",
                               "原因": _short(det.get("reason", ""), 200),
                               "预算": "请求 %s / 上下文 %s B / 活跃 %s s / 模块 %s" %
                                     (r["max_requests"], r["max_context_bytes"],
                                      r["max_active_seconds"], r["max_modules"]),
                               "已用活跃秒": r["active_seconds"]}))
    return out


def f_pf_modules(con):
    out = []
    for r in con.execute("SELECT * FROM research_modules ORDER BY run_id, address"):
        det = _j(r["detail"])
        reason = det.get("reason") or (det.get("artifacts") and
                                       "有产物 %d 个" % len(det["artifacts"])) or ""
        out.append(base_row("pf_modules", r["id"], "%s @ %s" % (r["run_id"], hex(r["address"] or 0)),
                            platform=hex(r["address"] or 0), status=r["status"],
                            local=r["module_path"], expect=1,
                            note=_short(reason, 120),
                            x={"run_id": r["run_id"], "可用": "是" if det.get("eligible") else "否",
                               "原因": _short(reason, 200), "尝试次数": r["attempts"],
                               "module_sha256": _short(r["module_sha256"], 24),
                               "接受的 IR": _short(r["accepted_ir_sha256"], 24)}))
    return out


def f_pf_attempts(con):
    out = []
    for r in con.execute("SELECT * FROM research_attempts ORDER BY created_at"):
        det = _j(r["detail"])
        out.append(base_row("pf_attempts", r["id"], r["module_id"], platform=r["run_id"],
                            status=r["status"], date=_ts(r["updated_at"]),
                            local=r["request_path"], expect=1,
                            note="第 %s 次 / 计费 %s B" % (r["attempt_no"], r["context_charge"]),
                            x={"response_path": r["response_path"],
                               "request_sha256": _short(r["request_sha256"], 24),
                               "ir_sha256": _short(r["ir_sha256"], 24),
                               "响应上限": r["response_limit"],
                               "detail": _short(det, 240)}))
    return out


def f_pf_gates(con):
    out = []
    for r in con.execute("SELECT * FROM gate_results ORDER BY id"):
        det = _j(r["detail"])
        out.append(base_row("pf_gates", r["gate_id"], r["stage_id"], platform=r["job_id"],
                            status=r["status"], date=_ts(r["created_at"]),
                            needs="必过" if r["required"] else "可跳",
                            note=_short(det, 120),
                            x={"required": r["required"], "evidence_path": r["evidence_path"],
                               "detail": _short(det, 300)}))
    return out


def f_pf_stages(con):
    out = []
    for r in con.execute("SELECT * FROM stages ORDER BY job_id, order_no"):
        det = _j(r["detail"])
        out.append(base_row("pf_stages", r["stage_id"], r["job_id"], platform="第 %s 步" % r["order_no"],
                            status=r["status"], date=_ts(r["finished_at"] or r["started_at"]),
                            note=_short((det.get("counts") or {}), 140),
                            x={"started": _ts(r["started_at"]), "finished": _ts(r["finished_at"]),
                               "counts": _short(det.get("counts", ""), 200)}))
    return out


def f_pf_artifacts(con):
    out = []
    for r in con.execute("SELECT * FROM artifacts ORDER BY created_at DESC"):
        path = str(r["path"] or "")
        out.append(base_row("pf_artifacts", os.path.basename(path) or r["id"], r["job_id"],
                            platform=r["kind"], size=str(r["size"] or ""),
                            date=_ts(r["created_at"]), local=path, expect=1,
                            note="sha256 " + _short(r["sha256"], 24),
                            x={"sha256": r["sha256"], "kind": r["kind"], "bytes": r["size"]}))
    return out


def f_pf_devices(con):
    out = []
    for r in con.execute("SELECT * FROM devices ORDER BY id"):
        caps = _j(r["capabilities"])
        out.append(base_row("pf_devices", r["id"], r["name"],
                            platform="%s / %s %s" % (r["family"], r["os"], r["arch"]),
                            status="已真机验收" if r["verified"] else "未接真机",
                            date=_ts(r["created_at"]), note=_short(r["notes"], 140),
                            x={"capabilities": _short(caps if caps else r["capabilities"], 200),
                               "verified": r["verified"]}))
    return out


def f_pf_events(con):
    out = []
    for r in con.execute("SELECT * FROM events ORDER BY id DESC"):
        out.append(base_row("pf_events", r["kind"], _short(r["message"], 120),
                            platform=r["job_id"] or "-", date=_ts(r["ts"]),
                            local=r["evidence_path"] or "", expect=0,
                            x={"evidence_path": r["evidence_path"], "id": r["id"]}))
    return out


def load_factory():
    key = "factory_all"
    sig = _sig([FACTORY_DB])
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    out = []
    con = _factory_conn()
    if con is None:
        out.append(base_row("error", "移植工厂状态库读不到",
                            note="%s 不存在或打不开(工厂没跑过就是空的,不是看板坏了)" % FACTORY_DB))
    else:
        try:
            for _, _, fn in factory_datasets():
                try:
                    out.extend(fn(con))
                except Exception as e:
                    out.append(base_row("error", "读取失败", note="%s: %s" % (_, e)))
        finally:
            con.close()
    _cache[key] = (sig, out)
    return out


# ---------------------------------------------------------------- 通用表格查询

SORTS = {"name": lambda d: d["name"].lower(), "date": lambda d: d["date"],
         "size": lambda d: d["bytes"], "ds": lambda d: d["ds"]}


def _attach_has(rows):
    """逐行判定本地文件/目录是否真在(路径来自台账,不猜)。"""
    for r in rows:
        r["has"] = 1 if (r["local"] and os.path.exists(P(r["local"]))) else 0
    return rows


def api_table(rows, q):
    rows = _attach_has(list(rows))
    term = (q.get("q", [""])[0] or "").strip().lower()
    ds = q.get("ds", [""])[0]
    flag = q.get("flag", [""])[0]
    status = q.get("status", [""])[0]
    sort = q.get("sort", ["name"])[0]
    desc = q.get("desc", ["0"])[0] == "1"
    if ds:
        rows = [r for r in rows if r["ds"] == ds]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if flag == "needs":
        rows = [r for r in rows if r["needs"]]
    elif flag == "local":
        rows = [r for r in rows if r["has"]]
    elif flag == "missing":
        rows = [r for r in rows if r["expect"] and not r["has"]]
    elif flag == "broken":
        rows = [r for r in rows if r["status"] in ("MISMATCH", "FAIL", "不一致")
                or "校验不一致" in str(r.get("x", {}).get("校验", ""))]
    if term:
        def hit(r):
            hay = " ".join([r["name"], r["title"], r["note"], r["platform"], r["license"], r["url"], r["local"]])
            hay += " " + " ".join(str(v) for v in r["x"].values())
            return term in hay.lower()
        rows = [r for r in rows if hit(r)]
    keyf = SORTS.get(sort, SORTS["name"])
    rows = sorted(rows, key=lambda d: (keyf(d), d["ds"]), reverse=desc)
    limit, offset = _paging(q, 300, 2000)
    return {"total": len(rows), "offset": offset, "limit": limit, "rows": rows[offset:offset + limit]}


def api_table_facets(rows):
    rows = _attach_has(list(rows))
    ds, flags = {}, {"needs": 0, "local": 0, "missing": 0, "broken": 0}
    statuses = {}
    for r in rows:
        d = ds.setdefault(r["ds"], {"ds": r["ds"], "count": 0, "local": 0, "missing": 0, "bytes": 0})
        d["count"] += 1
        if r["status"]:
            statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        if r["needs"]:
            flags["needs"] += 1
        if r["has"]:
            d["local"] += 1
            flags["local"] += 1
        elif r["expect"]:
            d["missing"] += 1
            flags["missing"] += 1
        if r["status"] in ("MISMATCH", "FAIL", "不一致") or "校验不一致" in str(r.get("x", {}).get("校验", "")):
            flags["broken"] += 1
        d["bytes"] += r["bytes"] or 0
    return {"ds": sorted(ds.values(), key=lambda d: -d["count"]), "flags": flags,
            "statuses": sorted(({"status": k, "count": v} for k, v in statuses.items()),
                               key=lambda d: -d["count"]),
            "total": len(rows)}


# ---------------------------------------------------------------- 源 / 报告 / 概览

def api_sources(q):
    rows, _ = tsv_rows("06-资讯监控/源登记表.tsv")
    run = json_load("06-资讯监控/_last_run.json") or {}
    stat = {}
    for s in (run.get("sources") or []) + (run.get("failures") or []):
        stat[s.get("name", "")] = s
    fac = news_facets()
    by_id = {s["source_id"]: s for s in fac["sources"]}
    out = []
    for r in rows:
        sid = r.get("id", "")
        ledger = by_id.get(sid, {})
        last = stat.get(r.get("name", ""), {})
        out.append({
            "id": sid, "name": r.get("name", ""), "url": r.get("url", ""),
            "enabled": r.get("enabled", ""), "note": r.get("note", ""),
            "count": ledger.get("count", 0), "hot": ledger.get("hot", 0),
            "last": ledger.get("last", ""),
            "kind": ledger.get("kind", ""),
            "http": last.get("http", ""), "status": last.get("status", ""),
            "parsed": last.get("parsed", ""), "new": last.get("new", ""),
        })
    term = (q.get("q", [""])[0] or "").strip().lower()
    if term:
        out = [s for s in out if term in (s["name"] + " " + s["url"] + " " + s["note"] + " " + s["id"]).lower()]
    if q.get("only", [""])[0] == "dead":
        out = [s for s in out if s["enabled"] != "1" or (s["http"] and s["http"] not in ("200", "304"))]
    elif q.get("only", [""])[0] == "empty":
        out = [s for s in out if s["count"] == 0]
    out.sort(key=lambda s: (-s["count"], s["name"]))
    return {"total": len(out), "rows": out, "run_utc": run.get("run_utc", ""),
            "run_new": run.get("new", ""), "ledger_total": run.get("ledger_total", ""),
            "failures": run.get("failures", [])}


DOC_GROUPS = [
    ("资讯报告", ["06-资讯监控/日报", "06-资讯监控/周报"], True),
    ("资讯专题", ["06-资讯监控"], False),
    ("移植线报告", ["06-资讯监控/移植大作", "06-资讯监控/PS5移植商店",
                    "06-资讯监控/Switch2模拟器", "06-资讯监控/网盘上传"], False),
    ("教程", ["01-教程库"], True),
    ("移植工厂", ["07-移植工厂"], True),
    ("硬件与机型", ["05-硬件与机型资料"], True),
    ("资源库说明", ["02-模拟器库", "03-BIOS库", "04-游戏资源库"], True),
    ("看板说明", ["08-数据看板"], False),
    ("根目录文档", ["."], False),
]
# 上游仓库/镜像/二进制目录:里面的 README 是别人写的,不算本库的报告
PRUNE_DIRS = {".git", "__pycache__", "上游wiki", "_sites", "_git", "已clone仓库",
              "成品包", "源码", "整仓bundle", ".venv", "venv", "_归档", "系统镜像", "node_modules"}
# 文档扫描再多剪两层:教程/工厂目录里夹带的上游打包树(package/、licenses/)全是别人的 LICENSE 与 readme
DOC_PRUNE_DIRS = PRUNE_DIRS | {"package", "licenses"}


def _doc_meta(ap, rel):
    st = os.stat(ap)
    return {"path": rel, "name": os.path.basename(rel), "bytes": st.st_size,
            "mtime": dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")}


def api_reports():
    out, scanned = [], set()
    for group, roots, recursive in DOC_GROUPS:
        for root in roots:
            base = ROOT if root == "." else P(root)
            if not os.path.isdir(base):
                continue
            if recursive:
                for dirpath, dirnames, filenames in os.walk(base):
                    dirnames[:] = [d for d in dirnames if d not in DOC_PRUNE_DIRS]
                    for fn in sorted(filenames):
                        if not fn.lower().endswith((".md", ".txt")):
                            continue
                        ap = os.path.join(dirpath, fn)
                        rel = os.path.relpath(ap, ROOT).replace("\\", "/")
                        if rel in scanned:
                            continue
                        scanned.add(rel)
                        rec = _doc_meta(ap, rel)
                        rec["group"] = group
                        rec["sub"] = "周报" if group == "资讯报告" and "/周报/" in rel else \
                                     "日报" if group == "资讯报告" else group
                        out.append(rec)
            else:
                for fn in sorted(os.listdir(base)):
                    ap = os.path.join(base, fn)
                    if not os.path.isfile(ap) or not fn.lower().endswith((".md", ".txt")):
                        continue
                    rel = os.path.relpath(ap, ROOT).replace("\\", "/")
                    if rel in scanned:
                        continue
                    scanned.add(rel)
                    rec = _doc_meta(ap, rel)
                    rec["group"] = group
                    rec["sub"] = group
                    out.append(rec)
    order = {"资讯专题": 0, "资讯报告": 1, "移植线报告": 2, "根目录文档": 3, "教程": 4,
             "移植工厂": 5, "硬件与机型": 6, "资源库说明": 7}
    out.sort(key=lambda d: (order.get(d["group"], 9), d["path"]))
    return out


def api_doc(q):
    rel = unquote(q.get("path", [""])[0]).replace("\\", "/").lstrip("/")
    ap = os.path.normpath(P(rel))
    rp = os.path.realpath(ap)
    if not rp.startswith(os.path.realpath(ROOT) + os.sep) or not os.path.isfile(rp):
        return {"error": "路径不在库内或不存在", "path": rel}, 404
    text = open(rp, "r", encoding="utf-8", errors="replace").read(4_000_000)
    return {"path": rel, "name": os.path.basename(rel), "content": text,
            "bytes": os.path.getsize(rp),
            "mtime": dt.datetime.fromtimestamp(os.path.getmtime(rp)).strftime("%Y-%m-%d %H:%M:%S")}, 200


def api_overview():
    fac = news_facets()
    games = _attach_has(load_games())
    repos = _attach_has(load_repos())
    factory = _attach_has(load_factory())
    gds = {d[0]: d[1] for d in games_datasets()}
    rds = {d[0]: d[1] for d in repos_datasets()}
    fds = {d[0]: d[1] for d in factory_datasets()}

    def bucket(rows, labels):
        agg = {}
        for r in rows:
            d = agg.setdefault(r["ds"], {"ds": r["ds"], "label": labels.get(r["ds"], r["ds"]),
                                         "count": 0, "local": 0, "missing": 0, "bytes": 0})
            d["count"] += 1
            d["bytes"] += r["bytes"] or 0
            if r["has"]:
                d["local"] += 1
            elif r["expect"]:
                d["missing"] += 1
        return sorted(agg.values(), key=lambda d: -d["count"])

    news = load_news()
    hot = [n for n in news if n["hot"]][:12]
    arr = [n for n in news if n["arrival"]][:12]
    src_rows = tsv_rows("06-资讯监控/源登记表.tsv")[0]
    return {
        "news": {"total": fac["total"], "hot": fac["hot"], "arrival": fac["arrival"],
                 "focus": fac["focus"], "sources": len(fac["sources"]),
                 "date_min": fac["date_min"], "date_max": fac["date_max"],
                 "days": fac["days"][-30:]},
        "sources": {"total": len(src_rows),
                    "enabled": len([r for r in src_rows if r.get("enabled") == "1"])},
        "games": {"total": len(games), "by_ds": bucket(games, gds),
                  "local": len([r for r in games if r["has"]]),
                  "missing": len([r for r in games if r["expect"] and not r["has"]]),
                  "bytes": sum(r["bytes"] or 0 for r in games)},
        "repos": {"total": len(repos), "by_ds": bucket(repos, rds),
                  "local": len([r for r in repos if r["has"]]),
                  "missing": len([r for r in repos if r["expect"] and not r["has"]]),
                  "bytes": sum(r["bytes"] or 0 for r in repos)},
        "factory": {"total": len(factory), "by_ds": bucket(factory, fds),
                    "local": len([r for r in factory if r["has"]]),
                    "missing": len([r for r in factory if r["expect"] and not r["has"]]),
                    "jobs": len([r for r in factory if r["ds"] == "pf_jobs"]),
                    "verified_modules": len([r for r in factory
                                             if r["ds"] == "pf_modules" and r["status"] == "verified"]),
                    "db_exists": os.path.isfile(P(FACTORY_DB))},
        "recent_hot": hot, "recent_arrival": arr,
        "datasets_files": {
            "games": [{"ds": k, "label": lbl, "file": rel,
                       "exists": os.path.isfile(P(rel))} for k, lbl, rel, _ in games_datasets()],
            "repos": [{"ds": k, "label": lbl, "file": rel,
                       "exists": os.path.isfile(P(rel))} for k, lbl, rel, _ in repos_datasets()],
            "factory": [{"ds": k, "label": lbl, "file": FACTORY_DB,
                         "exists": os.path.isfile(P(FACTORY_DB))} for k, lbl, _ in factory_datasets()],
        },
        "reports": {"total": len(api_reports())},
    }


# ---------------------------------------------------------------- 网盘(读 + 少量写)
#
# 这一段是本看板唯一读"库外"文件、也是唯一**会写**的地方(11-05 起):
# 原先填 cookie 的表单是 `_工具脚本\网盘账号台.py` 自己起的一张 127.0.0.1:5320 页面,
# 和看板两张皮、两套渲染、两份会漂的判据,用户明确说要并进 UI,所以那张页面拆掉了——
# 账号台现在只是逻辑模块,看板用 importlib 把它读进来,直接调它的 form_schema()/do_action()/list_safe()。
# 四条硬规矩:
#   1) 不自己碰 OpenList 的管理接口 —— 登录/挂载/探测全走账号台那一份代码,免得两边各写一套;
#   2) 不解密、不输出、不落盘任何凭据值 —— 值只从 POST body 穿到 do_action() 的手上,
#      看板既不打印它也不写进任何文件;回给浏览器的只有密文长度;
#   3) **只有绑回环才准写** —— --lan(0.0.0.0) 时 POST 一律拒绝:cookie 走 HTTP 明文,
#      同网段任何人都能嗅到;OpenList 自己的 data.db 还把挂载凭据明文放在 addition 字段里;
#   4) 端口探测只 connect 127.0.0.1,一个字节都不往外网发。

OL_DIR = os.environ.get("OPENLIST_DIR", r"F:\OpenList")
OL_EXE = os.path.join(OL_DIR, "openlist.exe")
OL_PORT = 5244
ACCT_SCRIPT = P("_工具脚本", "网盘账号台.py")
ACCOUNT_DB = os.path.join(OL_DIR, "账号库.json")
ND_SCOPES = "_工具脚本/网盘上传清单.tsv"
ND_LEDGER = "06-资讯监控/网盘上传/网盘上传台账.tsv"
DISK_LABELS = {"Quark": "夸克网盘", "BaiduNetdisk": "百度网盘", "Thunder": "迅雷云盘"}
ND_FORM_MAX = 256 * 1024               # POST body 上限:cookie 再长也长不到 256 KB
BIND = "127.0.0.1"                     # main() 里按 --lan 覆盖;写侧的门只看这个值


_acct_mod = None
_acct_err = ""


def acct_mod():
    """按路径把账号台读进来(文件名是中文,不能直接 import)。读不进来就回 (None, 原因),
    界面据此把「填 cookie」这块关掉并点名原因,而不是静默显示一张空表。"""
    global _acct_mod, _acct_err
    if _acct_mod is not None:
        return _acct_mod, ""
    if not os.path.isfile(ACCT_SCRIPT):
        return None, "账号台脚本不存在:%s" % ACCT_SCRIPT
    if _acct_err:
        return None, _acct_err
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("netdisk_accounts", ACCT_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)                       # 它 import 时只读 DPAPI/常量,不起服务
    except Exception as e:
        _acct_err = "账号台读不进来:%s: %s" % (type(e).__name__, str(e)[:200])
        return None, _acct_err
    _acct_mod = mod
    return mod, ""



def _port_open(port, timeout=0.35):
    """本机回环口有没有人在听。不是联网,也不是扫描:只连 127.0.0.1 的一个固定端口。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def _read_abs(path):
    """读库外的固定绝对路径(只有账号库用得上),按 mtime+size 缓存;不存在返回 None。"""
    if not os.path.isfile(path):
        return None
    st = os.stat(path)
    sig = (st.st_mtime_ns, st.st_size)
    key = ("abs", path)
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    _cache[key] = (sig, text)
    return text


def _abs_meta(path):
    rec = {"path": path, "exists": os.path.isfile(path)}
    if rec["exists"]:
        st = os.stat(path)
        rec["bytes"] = st.st_size
        rec["mtime"] = dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
    return rec


def api_netdisk():
    ol = _abs_meta(OL_EXE)
    ol["listening"] = _port_open(OL_PORT)
    ol["url"] = "http://127.0.0.1:%d/" % OL_PORT
    ol["port"] = OL_PORT

    mod, why = acct_mod()
    acct = _abs_meta(ACCT_SCRIPT)
    acct["loadable"] = mod is not None
    acct["load_error"] = why
    acct["has_api"] = bool(mod and hasattr(mod, "do_action") and hasattr(mod, "form_schema")
                           and hasattr(mod, "list_safe"))
    acct["needs_admin_pw"] = bool(os.environ.get("OPENLIST_ADMIN_PASSWORD"))  # 只报有没有设,不取值
    acct["qr_ready"] = bool(mod and getattr(mod, "qr", None))
    acct["qr_err"] = (getattr(mod, "QR_ERR", "") if mod else "")[:200]
    acct["watch"] = watch_state()      # 服务端看守:网页没开着也会自己把扫上的号收下(见 qr_watch_loop)
    # 写侧的门:绑 0.0.0.0(--lan)就关掉。cookie 是 HTTP 明文出去的,同网段谁能嗅谁就能拿走。
    acct["writable"] = bool(acct["has_api"] and BIND in ("127.0.0.1", "::1"))
    acct["write_blocked"] = "" if acct["writable"] else (
        "看板现在绑的是 %s(局域网可读),填 cookie 的表单已锁死 —— cookie 走的是 HTTP 明文,"
        "只在 127.0.0.1 上才准发出去。用不带 --lan 的方式重开看板。" % BIND)

    accounts = mod.list_safe() if acct["has_api"] else []
    db = None
    text = _read_abs(ACCOUNT_DB)
    if text is not None:
        try:
            db = json.loads(text)
        except Exception:
            db = None
    store = _abs_meta(ACCOUNT_DB)
    store["readable"] = db is not None
    store["total"] = len(accounts)
    store["raw_total"] = len((db or {}).get("accounts") or [])   # 模块读不进来时靠这个数点名
    store["active"] = len([a for a in accounts if a.get("active")])
    store["ok"] = len([a for a in accounts if a.get("last_ok")])
    store["unprobed"] = len([a for a in accounts if not a.get("last_check")])

    # 每个盘顺带带上「怎么登录」和那句短提示：这些是常量，不用问 OpenList，
    # 切盘时提示能立刻变（以前要等一次 2~9 秒的字段接口，字是空的，看着像坏了）。
    _qrdisks = getattr(getattr(mod, "qr", None), "DISKS", {}) or {}
    drivers = [{"driver": d, "label": DISK_LABELS[d],
                "login_kind": (_qrdisks.get(d) or {}).get("kind", ""),
                "login_howto": (_qrdisks.get(d) or {}).get("howto", "")}
               for d in (mod.DISKS if mod else DISK_LABELS)]
    # 默认盘那一份顺手带出去,界面首屏就不用再问一次;走同一个缓存,切盘才多发一问
    schema = (api_netdisk_fields({"driver": [drivers[0]["driver"]]})
              if acct["has_api"] and drivers else
              {"ok": False, "driver": "", "fields": [],
               "msg": why or "账号台模块读不进来,表单出不了"})

    by_driver = []
    for drv in ("Quark", "BaiduNetdisk", "Thunder"):
        sub = [a for a in accounts if a.get("driver") == drv]
        by_driver.append({"driver": drv, "label": DISK_LABELS[drv], "total": len(sub),
                          "ok": len([a for a in sub if a.get("last_ok")]),
                          "bad": len([a for a in sub
                                      if a.get("last_check") and not a.get("last_ok")]),
                          "active": len([a for a in sub if a.get("active")])})
    extra = [a for a in accounts if a.get("driver") not in DISK_LABELS]
    if extra:
        by_driver.append({"driver": "(其他)", "label": "(其他)", "total": len(extra),
                          "ok": 0, "bad": 0, "active": 0})

    scope_rows, _ = tsv_rows(ND_SCOPES)
    ledger, _ = tsv_rows(ND_LEDGER)
    scopes = []
    for r in scope_rows:
        rel_dir = (r.get("dir") or "").replace("\\", "/").strip("/")
        abs_dir = P(rel_dir) if rel_dir else ROOT
        pref = (r.get("remote_prefix") or "").strip("/")
        hit = [x for x in ledger if pref and ("/" + pref) in (x.get("remote_path") or "").replace("\\", "/")]
        scopes.append({
            "name": r.get("name", ""), "dir": rel_dir, "dir_exists": os.path.isdir(abs_dir),
            "remote_prefix": pref, "mount": r.get("mount", ""), "enable": r.get("enabled", r.get("enable", "")),
            "note": (r.get("note") or "")[:400], "uploaded": len(hit),
            "uploaded_bytes": sum(int(x["bytes"]) for x in hit if (x.get("bytes") or "").isdigit()),
            "last_at": max([x.get("at", "") for x in hit]) if hit else "",
        })

    by_status = {}
    for x in ledger:
        by_status[x.get("status", "") or "(空)"] = by_status.get(x.get("status", "") or "(空)", 0) + 1
    by_mount = {}
    for x in ledger:
        m = x.get("mount", "") or "(空)"
        by_mount[m] = by_mount.get(m, 0) + 1

    warn = []
    if not ol["listening"]:
        warn.append("OpenList 没在 127.0.0.1:%d 监听 —— 挂载是空的,登录/探测/上传都跑不了。"
                    "双击 08-数据看板\\启动网盘账号台.bat 把它拉起来(顺带开这张看板)。" % OL_PORT)
    if not acct["loadable"]:
        warn.append("账号台模块读不进来:%s —— 这页只能看,表单出不了。" % (why or "未知原因"))
    elif not acct["writable"]:
        warn.append(acct["write_blocked"])
    if not store["exists"]:
        warn.append("账号库文件不存在(%s)。" % ACCOUNT_DB)
    elif store["total"] == 0:
        warn.append("账号库里 0 个账号 —— 一次网盘都没登录过。夸克直接按下面那张卡里的"
                    "『① 打开扫码窗口』,手机扫一下就自动抓取、自动起名,不用手填任何东西。")
    off = [s["name"] for s in scopes if s["enable"] != "1"]
    if off:
        warn.append("这 %d 档 enable 不是 1,跑上传会被跳过:%s。" % (len(off), "、".join(off)))
    local = [s["name"] for s in scopes if "本地暂存" in s["mount"]]
    if local:
        warn.append("这 %d 档的 mount 还指着 /本地暂存,等于抄到本机另一个目录、没出网盘:%s。"
                    "要真备份得把 mount 改成 /夸克 之类。" % (len(local), "、".join(local)))
    if not acct["needs_admin_pw"]:
        warn.append("这个看板进程里没有 OPENLIST_ADMIN_PASSWORD —— 登录/挂载/探测都要用它向 OpenList 换 token。"
                    "setx 设过之后要重开命令行才生效(看板只报有没有设,永远不读它的值)。")

    return {
        "openlist": ol, "account": acct, "store": store,
        "accounts": accounts, "by_driver": by_driver, "schema": schema, "bind": BIND,
        "drivers": drivers,
        "scopes": scopes,
        "ledger": {"total": len(ledger), "by_status": by_status, "by_mount": by_mount,
                   "bytes": sum(int(x["bytes"]) for x in ledger if (x.get("bytes") or "").isdigit()),
                   "last_at": max([x.get("at", "") for x in ledger]) if ledger else "",
                   "file": ND_LEDGER, "exists": os.path.isfile(P(ND_LEDGER))},
        "warnings": warn,
        "notes": ["这一页是本看板唯一的写路径:填 cookie / 探测 / 启用 / 删账号,其余页签一律只读。",
                  "凭据值只从这张页面的 POST body 穿到账号台手上,当场 DPAPI 加密写进 %s;"
                  "看板不解密、不打印、不落盘任何值,回给浏览器的只有密文长度。" % ACCOUNT_DB,
                  "字段表不是这里写死的,是账号台向本机 OpenList 的 /api/admin/driver/list 现取;"
                  "OpenList 换了字段,这页跟着变。",
                  "OpenList 自己的 data\\data.db 会把挂载凭据明文放在 addition 字段里 —— 这是它的机制,"
                  "所以 F:\\OpenList\\data 别同步到任何地方、5244 别暴露到局域网。",
                  "扫码那条:窗口是本机 Edge/Chrome 开在独立 profile 上的(不碰你日常浏览器),cookie 用 CDP 从"
                  "那个 profile 里取,只在这台机器的内存里过一遍就进 DPAPI;值不回界面、不写日志、不落文件。",
                  "登录位(槽位)那条:一个 profile 只有一个登录位,所以多账号靠多开槽位——夸克第 1 槽 9331/"
                  "profile-Quark,第 2 槽 9341/profile-Quark-02……每格各装一个号的登录态,扫第二个号不会顶掉第一个。",
                  "看守那条:看板自己起了根线程,每 %d 秒问一遍开着的扫码窗口,扫上了就按同一条生产路径入库;"
                  "所以这一页开着与否都不影响收号(11-05 那次「我登录了没反应」就是因为抓取只挂在网页的 2 秒轮询上)。"
                  "绑 --lan 时这根线程也不动写路径。" % WATCH_SEC,
                  "「把日常浏览器里登着的号捞过来」这条堵死了(11-05 实测):Edge/Chrome 新版的 cookie 是 App-Bound(v20)"
                  "加密,Local State 里那把 app_bound_encrypted_key 的头部是 APPB 标记,非浏览器进程拿 DPAPI 解直接 err=13;"
                  "日常 Edge 在跑时它的 Cookies 库连只读打开都拒绝;而且 Chrome/Edge Dev/Firefox 三个 profile 里根本没有"
                  "夸克登录态(__pus/__kps/__uid 一条都没有),本机唯一登着夸克的就是我们自己那个独立 profile。",
                  "『扫上了没』不是看 cookie 名字齐不齐 —— 游客态也带 __pus/__puus;判登录问 pan.quark.cn/account/info"
                  "(游客拿不到 nickname),昵称和 __uid 就是表里的 ID/账号名。drive.quark.cn 那个会员接口要客户端签名,"
                  "裸问真账号也回 31001,不能当判据。认成账号了才自动起名入库(别名取 uid 尾巴,重扫同一个号是更新不是新增)。",
                  "绑 --lan(0.0.0.0) 重开时这页会自动锁掉写:cookie 走 HTTP 明文,同网段谁能嗅谁就能拿走。"],
        "checked_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------------------------------------------------------------- 网盘:切盘时现取字段表

_nd_fields_cache = {}
# 字段表(要填哪几格)是 OpenList 的属性,基本不动,值得按盘缓存一次;
# 可这几格是**活的**:哪个登录位窗口开着、profile 在不在、本机有哪些浏览器 —— 每问都得现探一次端口。
# 连它们一起缓存过,界面就出过"第 2 槽明明在听、下拉却说空槽"的假象(11-05 实测)。
QR_LIVE_KEYS = ("qr_ready", "qr_max_slot", "qr_slots", "qr_browsers")


def _qr_live(mod, driver):
    out = {}
    try:
        qr = getattr(mod, "qr", None)
        out["qr_ready"] = bool(qr)
        out["qr_max_slot"] = int(getattr(qr, "MAX_SLOTS", 0) or 0) if qr else 0
        if hasattr(mod, "qr_slots"):
            out["qr_slots"] = mod.qr_slots(driver)
        if hasattr(mod, "qr_browsers"):
            out["qr_browsers"] = mod.qr_browsers()
    except BaseException:
        pass          # 探不到就少给几格,界面自己会交代"没拿到",不能因此把整张表单弄没
    return out


def api_netdisk_fields(q):
    """界面选另一个盘(夸克→百度→迅雷)时问一次:这个盘要填哪些格子。
    字段名/必填/类型全部来自 OpenList,看板自己不写死;成功的结果按盘缓存一次,
    失败的留着不缓存,免得 OpenList 起来之前那一问被记成永久错误。
    缓存的只有字段表,登录位/浏览器那几格每次现探(见 QR_LIVE_KEYS)。"""
    driver = (q.get("driver") or ["Quark"])[0].strip()
    mod, why = acct_mod()
    if not (mod and hasattr(mod, "form_schema")):
        return {"ok": False, "driver": driver, "fields": [],
                "msg": "账号台模块读不进来:%s" % (why or "未知原因")}
    live = _qr_live(mod, driver)
    cached = _nd_fields_cache.get(driver)
    if cached is not None:
        return dict(cached, **live)
    res = mod.form_schema(driver)
    res.setdefault("driver", driver)
    res.setdefault("fields", [])
    if res.get("ok"):
        _nd_fields_cache[driver] = {k: v for k, v in res.items() if k not in QR_LIVE_KEYS}
    return res


# ---------------------------------------------------------------- 网盘:服务端看守开着的扫码窗口
# 为什么要有这一段(11-05 实测):抓 cookie 那一下本来是「网盘」页签每 2 秒 poll 一次的副作用,
# 结果用户扫完号回来问"没反应"——那张网页根本没开着(日志里 POST /api/netdisk/action 一条都没有),
# 登录态就干躺在窗口里。登录在本机的浏览器、抓取在本机的账号台,没必要非借一张网页来触发。
# 三条规矩:① 只在写侧允许(绑回环)时跑;② 只碰"端口在听"的那几格;
# ③ 先问扫码模块有没有登录标志,没扫上就一次 OpenList 都不惊动(它每登录一回打一行日志,别刷屏)。

WATCH_SEC = 15
_watch = {"on": False, "why": "", "cycle": 0, "last_at": "", "last_err": "",
          "hits": [], "held": [], "_said": {}, "_hold": set()}


def _watch_ready(st):
    """这一格算不算「扫上了」:窗口在听 + 网盘自己的登录标志一条不缺。
    只看 网盘扫码登录.status() 那一份(纯读,不碰 OpenList、不碰凭据值)。"""
    markers = st.get("markers") or []
    return bool(st.get("listening")) and bool(markers) and \
        len(st.get("markers_have") or []) == len(markers)


def qr_watch_sweep(mod):
    """过一遍所有盘所有登录位,回 (这一轮值得 poll 的格子, 现在还开着的格子)。"""
    qr = getattr(mod, "qr", None)
    due, live = [], []
    if not qr:
        return due, live
    for driver in list(mod.DISKS):
        for row in (qr.slots(driver) or []):
            if not row.get("listening"):
                continue
            key = (driver, row["slot"])
            live.append(key)
            try:
                st = qr.status(driver, row["slot"])
            except BaseException:
                continue
            if _watch_ready(st):
                due.append(key)
    return due, live


def _watch_allowed():
    """看守只在写侧允许时跑:界面那条「绑非回环就锁写」的规矩,这根线程一样得守。"""
    if BIND in ("127.0.0.1", "::1"):
        return True, ""
    return False, "看板绑的是 %s,看守不碰写路径" % BIND


def qr_watch_loop():
    held = _watch["_hold"]
    _watch["on"] = True
    while True:
        time.sleep(WATCH_SEC)
        try:
            mod, why = acct_mod()
            if not (mod and getattr(mod, "qr", None) and hasattr(mod, "do_action")):
                _watch["why"] = why or "账号台没给 do_action"
                continue
            ok, block = _watch_allowed()
            if not ok:
                _watch["why"] = block
                continue
            _watch["why"] = ""
            # 顺手体检：每 20 个周期（约 5 分钟看一次门）才真正探一轮，账号台自己再按 6 小时节流。
            # 用户要的是「哪个号失效了就把登录位释放出来」，别等人手动点。
            if _watch["cycle"] % 20 == 0 and hasattr(mod, "reap_dead"):
                try:
                    auth = mod.nd.Auth()
                    if auth.token():
                        rr = mod.reap_dead(auth)
                        if rr.get("freed"):
                            print("[体检] 释放 %s" % "、".join("%s(第%d槽)" % (a, s) for a, s, _ in rr["freed"]),
                                  flush=True)
                except BaseException:
                    pass
            # 顺手扫空壳格：扫一次码就留一个 profile 目录，不扫会越用越少（用户 11-08 撞上的
            # 「只登了 4 个号却说十格满」就是空壳堆出来的）。只清「库里没号 + 窗口没开」的格。
            if _watch["cycle"] % 20 == 5 and hasattr(mod, "_reap_orphan_profiles"):
                try:
                    db = mod.load_db()
                    for _d in ("Quark", "BaiduNetdisk", "Thunder"):
                        n = mod._reap_orphan_profiles(_d, db)
                        if n:
                            print("[清空壳] %s 清掉 %d 个没号也没窗口的登录位" % (_d, n), flush=True)
                except BaseException:
                    pass
            due, live = qr_watch_sweep(mod)
            held &= set(live)                       # 窗口关了就把这格忘掉,下次再开重新算
            _watch["cycle"] += 1
            _watch["last_at"] = dt.datetime.now().strftime("%H:%M:%S")
            _watch["held"] = sorted("%s 第%d槽" % k for k in held)
            for key in due:
                if key in held:
                    continue                        # 已经处理过/本来就登着,别每 15 秒重问一次
                driver, slot = key
                r = mod.do_action("qr", {"phase": "poll", "driver": driver, "slot": slot})
                line = "%s 第%d槽:%s" % (driver, slot, (r.get("msg") or "")[:200])
                if r.get("ok") or (r.get("qr") or {}).get("already"):
                    held.add(key)                   # 收下了/不用重扫 → 这格不再重复问
                if not r.get("ok"):
                    _watch["last_err"] = line
                if _watch["_said"].get(key) != line:    # 同一句话只打一遍,免得日志刷爆
                    _watch["_said"][key] = line
                    _watch["hits"] = (_watch["hits"] + [
                        "%s %s" % (dt.datetime.now().strftime("%H:%M:%S"), line)])[-10:]
                    print("[看守] " + line, flush=True)
        except BaseException as e:
            _watch["last_err"] = "%s: %s" % (type(e).__name__, str(e)[:160])


def watch_state():
    return {"on": _watch["on"], "every_sec": WATCH_SEC, "why": _watch["why"],
            "cycle": _watch["cycle"], "last_at": _watch["last_at"],
            "last_err": _watch["last_err"], "hits": list(_watch["hits"]),
            "held": list(_watch["held"])}


# ---------------------------------------------------------------- HTTP

API = {
    "/api/overview": lambda q: api_overview(),
    "/api/news": api_news,
    "/api/news_facets": lambda q: news_facets(),
    "/api/games": lambda q: api_table(load_games(), q),
    "/api/games_facets": lambda q: api_table_facets(load_games()),
    "/api/repos": lambda q: api_table(load_repos(), q),
    "/api/repos_facets": lambda q: api_table_facets(load_repos()),
    "/api/factory": lambda q: api_table(load_factory(), q),
    "/api/factory_facets": lambda q: api_table_facets(load_factory()),
    "/api/sources": api_sources,
    "/api/reports": lambda q: api_reports(),
    "/api/doc": api_doc,
    "/api/netdisk": lambda q: api_netdisk(),
    "/api/netdisk_fields": api_netdisk_fields,
}

STATIC = {"index.html": ("index.html", "text/html; charset=utf-8"),
          "app.js": ("app.js", "application/javascript; charset=utf-8"),
          "style.css": ("style.css", "text/css; charset=utf-8")}


class Handler(BaseHTTPRequestHandler):
    server_version = "KandataKanban/1.0"

    def _send(self, code, body, ctype="application/json; charset=utf-8", cache="no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            # 客户端中断连接(刷新/关标签/取消下载)时 Windows 抛 ConnectionAbortedError
            # (WinError 10053)，不捕获会累积把进程带崩。
            pass

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)
        if path == "/" or path == "/index.html":
            return self._static("index.html")
        name = path.lstrip("/")
        if name in STATIC:
            return self._static(name)
        if path.startswith("/api/"):
            if path == "/api/netdisk/shot":
                return self._shot(q)
            if path == "/api/netdisk/download":
                return self._download(q)
            fn = API.get(path)
            if not fn:
                return self._send(404, json.dumps({"error": "no such api", "path": path}, ensure_ascii=False))
            try:
                res = fn(q)
                code = 200
                if isinstance(res, tuple):
                    res, code = res
                return self._send(code, json.dumps(res, ensure_ascii=False))
            except Exception as e:
                return self._send(500, json.dumps({"error": "%s: %s" % (type(e).__name__, e)}, ensure_ascii=False))
        if path in ("/robots.txt", "/favicon.ico"):
            return self._send(204, "")
        return self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self):
        # 看板唯一的写入口,只有这一个路径。上面 do_GET 全程只读,别在别处再开写侧。
        if urlparse(self.path).path != "/api/netdisk/action":
            return self._send(405, json.dumps(
                {"ok": False, "msg": "看板只收 POST /api/netdisk/action,其余页签一律只读"},
                ensure_ascii=False))
        if BIND not in ("127.0.0.1", "::1"):
            return self._send(403, json.dumps(
                {"ok": False, "msg": "看板现在绑的是 %s,写侧已锁死 —— cookie 走 HTTP 明文,"
                                      "只有回环才准发出去。用不带 --lan 的方式重开。" % BIND},
                ensure_ascii=False))
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            n = -1
        if n < 0 or n > ND_FORM_MAX:
            return self._send(413, json.dumps(
                {"ok": False, "msg": "body 长度不合法(上限 %d 字节)" % ND_FORM_MAX}, ensure_ascii=False))
        try:
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("不是对象")
        except Exception as e:
            return self._send(400, json.dumps(
                {"ok": False, "msg": "body 读不进来:%s" % e}, ensure_ascii=False))
        mod, why = acct_mod()
        if not (mod and hasattr(mod, "do_action")):
            return self._send(200, json.dumps(
                {"ok": False, "msg": "账号台模块读不进来:%s" % why, "account": None, "accounts": []},
                ensure_ascii=False))
        try:
            # do_action 自己把 SystemExit / Exception 全接住了,到这里只可能是 JSON 之外的意外
            res = mod.do_action(str(payload.get("action") or ""), payload)
        except BaseException as e:
            res = {"ok": False, "msg": "%s: %s" % (type(e).__name__, str(e)[:300]),
                   "account": None, "accounts": []}
        # 写完让账号库缓存失效:下一步 GET 会重读磁盘,不然页面还端着旧 mtime 的那份
        _cache.pop(("abs", ACCOUNT_DB), None)
        return self._send(200, json.dumps(res, ensure_ascii=False))

    def _shot(self, q):
        """某个登录位（槽位）的扫码窗口实时画面（里面通常就是一张二维码），给「网盘」页签内显示。
        这是 GET、只读：不落盘、不进台账、no-store，只有回环口拿得到。
        二维码不是凭据（它是登录页公开广播的一次性串），但也没必要留给别人看。"""
        driver = ((q.get("driver") or ["Quark"])[0] or "").strip()[:30]
        slot = ((q.get("slot") or ["1"])[0] or "1").strip()[:6]
        try:
            slot = max(1, int(slot or 1))      # 下限夹到 1；上限交给账号台 qr._slot 按 MAX_SLOTS 夹（别写死 10，现在 20 格）
        except (TypeError, ValueError):
            slot = 1
        if BIND not in ("127.0.0.1", "::1"):
            return self._send(403, json.dumps(
                {"ok": False, "msg": "看板绑的是 %s，扫码画面不外发" % BIND}, ensure_ascii=False))
        mod, why = acct_mod()
        if not (mod and hasattr(mod, "screenshot")):
            return self._send(503, json.dumps(
                {"ok": False, "msg": "账号台没给截图接口：%s" % (why or "模块读不进来")}, ensure_ascii=False))
        try:
            fn = getattr(mod, "screenshot_ex", None)
            if fn:
                png, err, mode = fn(driver, slot)
            else:
                png, err = mod.screenshot(driver, slot)
                mode = ""
        except BaseException as e:
            png, err, mode = None, "%s: %s" % (type(e).__name__, str(e)[:200]), ""
        if not png:
            return self._send(503, json.dumps({"ok": False, "msg": err or "窗口没开着"}, ensure_ascii=False))
        # 这张图用的裁剪框（x/y/scale）：前端把「点在图上哪」换算回网页坐标，点刷新/页签才落得准。
        clip = {}
        mfn = getattr(mod, "screenshot_meta", None)
        if mfn:
            try:
                clip = (mfn(driver, slot) or {}).get("clip") or {}
            except BaseException:
                clip = {}
        # X-Shot-Mode 让前端知道这张图是「二维码卡片」还是「整页首屏」——后者要打个角标，
        # 否则用户会以为卡片定位坏了。
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Shot-Mode", mode or "card")
        self.send_header("X-Shot-Clip", json.dumps(clip))
        self.end_headers()
        try:
            self.wfile.write(png)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def _download(self, q):
        """把网盘里某个文件经看板流式转发给浏览器（浏览器直接下，不落看板磁盘）。
        path 是挂载点起的路径（如 /quark-03/xx.zip），第一段就是账号别名。
        实测夸克直链 raw_url 要带 cookie + Referer + UA 才放行（否则 Tengine 412），
        而且得走本机代理；所以这里用 fs/get 拿 raw_url，再带上该账号的 cookie 去拉。"""
        if BIND not in ("127.0.0.1", "::1"):
            return self._send(403, json.dumps(
                {"ok": False, "msg": "看板绑的是 %s，下载不外发" % BIND}, ensure_ascii=False))
        path = ((q.get("path") or ["/"])[0] or "/").strip()
        if not path or path == "/" or ".." in path:
            return self._send(400, json.dumps({"ok": False, "msg": "路径不对"}, ensure_ascii=False))
        mod, why = acct_mod()
        if not mod:
            return self._send(503, json.dumps({"ok": False, "msg": "账号台读不进来：%s" % why},
                                              ensure_ascii=False))
        try:
            auth = mod._auth()
            tok = auth.token()
        except BaseException as e:
            return self._send(503, json.dumps(
                {"ok": False, "msg": "拿不到 OpenList 登录态：%s" % (str(e)[:160])},
                ensure_ascii=False))
        import urllib.request
        name = path.rstrip("/").rsplit("/", 1)[-1]
        # 第一段 = 账号别名；用 fs/get 拿带签名的直链 raw_url
        try:
            got = auth.api("/api/fs/get", {"path": path})
            raw_url = ((got.get("data") or {}).get("raw_url")) or ""
        except BaseException:
            raw_url = ""
        if not raw_url:
            return self._send(503, json.dumps(
                {"ok": False, "msg": "OpenList 没给这个文件的下载直链（raw_url 空）"},
                ensure_ascii=False))
        # 该账号的 cookie（只在这条下载请求的内存里用，不落盘不打印）
        cookie = ""
        try:
            alias = path.strip("/").split("/")[0]
            db = mod.load_db()
            for a in db.get("accounts") or []:
                if a.get("alias") == alias:
                    sec = mod.secret_of(a) if a.get("secret") else {}
                    cookie = sec.get("cookie") or sec.get("Cookie") or ""
                    break
        except BaseException:
            cookie = ""
        # 走代理（网盘直链是外网地址）
        _pxy = ""
        try:
            import importlib.util as _ilu
            _pspec = _ilu.spec_from_file_location("net_proxy", P("_工具脚本", "net_proxy.py"))
            _pmod = _ilu.module_from_spec(_pspec)
            _pspec.loader.exec_module(_pmod)
            _pxy = _pmod.proxy_url()
        except Exception:
            _pxy = ""
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": _pxy, "https": _pxy})) if _pxy \
            else urllib.request.build_opener()
        req = urllib.request.Request(raw_url)
        if cookie:
            req.add_header("Cookie", cookie)
        req.add_header("Referer", "https://pan.quark.cn/")
        req.add_header("User-Agent",
                       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        try:
            resp = opener.open(req, timeout=600)
            clen = resp.headers.get("Content-Length")
        except urllib.error.HTTPError as e:
            return self._send(e.code, json.dumps(
                {"ok": False, "msg": "下载失败 HTTP %d：%s" % (e.code, (e.read()[:160] or b"").decode("utf-8", "replace"))},
                ensure_ascii=False))
        except Exception as e:
            return self._send(503, json.dumps(
                {"ok": False, "msg": "下载失败：%s: %s" % (type(e).__name__, str(e)[:160])},
                ensure_ascii=False))
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition",
                         "attachment; filename*=UTF-8''%s" % urllib.parse.quote(name))
        if clen:
            self.send_header("Content-Length", str(clen))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def _static(self, name):
        info = STATIC.get(name)
        if not info:
            return self._send(404, "not found", "text/plain; charset=utf-8")
        fp = os.path.join(HERE, info[0])
        if not os.path.isfile(fp):
            return self._send(404, "缺少文件 %s" % fp, "text/plain; charset=utf-8")
        with open(fp, "rb") as f:
            data = f.read()
        return self._send(200, data, info[1], cache="no-cache")

    def log_message(self, fmt, *args):
        # args[0] 可能是 HTTPStatus 枚举(501 等 send_error 路径)，先安全转 str，
        # 否则 "/api/" in HTTPStatus 会抛 TypeError 累积到把进程带崩。
        head = str(args[0]) if args else ""
        if "/api/" in head:
            return
        try:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))
        except Exception:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt))


def lan_ips():
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips


def main():
    global BIND
    ap = argparse.ArgumentParser()
    ap.add_argument("--lan", action="store_true", help="绑 0.0.0.0(局域网可读);默认只绑 127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--open", action="store_true", help="启动后拉起默认浏览器")
    a = ap.parse_args()
    bind = "0.0.0.0" if a.lan else "127.0.0.1"
    BIND = bind
    srv = ThreadingHTTPServer((bind, a.port), Handler)
    print("数据看板:http://127.0.0.1:%d/  (库根=%s)" % (a.port, ROOT))
    if a.lan:
        for ip in lan_ips():
            print("  局域网:http://%s:%d/" % (ip, a.port))
        print("  --lan:局域网可读,**网盘页签的填 cookie / 删账号已锁死**(cookie 走 HTTP 明文)")
    else:
        print("  只绑回环:网盘页签可写(填 cookie / 探测 / 切活跃 / 删账号)。Ctrl+C 停止。")
    if a.open:
        try:
            import webbrowser
            webbrowser.open("http://127.0.0.1:%d/" % a.port)
        except Exception:
            pass
    threading.Thread(target=qr_watch_loop, daemon=True, name="qr-watch").start()
    print("  网盘看守:每 %d 秒自己问一遍开着的扫码窗口(网页没开着也能收下扫上的号)" % WATCH_SEC)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
