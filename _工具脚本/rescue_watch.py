#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rescue_watch.py —— 下架抢救层(2026-10-20 新增,回答"珍贵且会被立即下架的资源"怎么办)

为什么单独一层:这类资源的窗口期是**小时到天**级,日更监控(08:30 一轮)根本来不及。
2026-08-17 任天堂一天 7 份 DMCA 扫掉 GitHub 401 个 Switch 模拟器仓库(Suyu 311 / Skyline 29 / MonoNX 17),
fork 与备份一锅端;Eden 2026-03 转自建 git、Citron 走自家 release 页、Suyu 2026-09-13 归档、
Ryujinx org 整个消失、re3/reVC 451 下架。**镜像从出现到消失经常只有几天** —— 所以这一层的职责是:
  ① 存活检查:登记表里每个目标活着就立刻抓(源码 tarball / 页面快照 / git 裸库镜像);
  ② 雷达:GitHub 搜索盯 ≤30 天内新建的同名/同线仓库,新镜像一冒头就抓;
  ③ 存在性巡检:已挂源的 140 个 GitHub 仓库,谁 404 了立刻告警(改名会 301 跟随,404 就是真没了);
  ④ 情报面:台账里命中"下架信号"词的新闻条目,把正文里的 GitHub 链接挖出来当临时雷达目标。

与 scene_dl 的分工:scene_dl 收"已判定可下的 release/源码"(合法收录登记表,白名单制,慢而稳);
本层收"正在消失的东西"(下架抢救登记表,黑名单式紧迫,快而全)。落盘都在 04-游戏资源库/下架抢救/,
sha256 对账口径与 scene_dl 一致(上游给不了 digest 的一律 LOCAL_ONLY)。

硬闸门与 scene_dl 同源:BAN(nsp/xci/iso/merged_keys/prod.keys/romset/warez/dump pack)出现的链接一律不抓;
泄露 SDK 类**默认只告警**(项目既定拒收范围),要抓得先把登记表里那行 action 从 alert 改成 capture_src。

用法:
  py -3 _工具脚本/rescue_watch.py                  # 单轮(检查+雷达+巡检+新闻信号)
  py -3 _工具脚本/rescue_watch.py --watch 7200     # 循环模式,每 2 小时一轮(抢救窗口要的就是这个)
  py -3 _工具脚本/rescue_watch.py --dry-run        # 只检查会抓什么,不落盘
  py -3 _工具脚本/rescue_watch.py --no-news --no-sweep   # 只跑登记表+雷达
  py -3 _工具脚本/rescue_watch.py --radar-days 14  # 雷达只认 14 天内新建的仓(默认 30)
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlparse
from urllib.parse import quote as urlquote

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "06-资讯监控", "下架抢救登记表.tsv")
SRC_REG = os.path.join(ROOT, "06-资讯监控", "源登记表.tsv")
LEDGER = os.path.join(ROOT, "06-资讯监控", "台账.tsv")
OUT = os.path.join(ROOT, "04-游戏资源库", "下架抢救")
RESCUE_LEDGER = os.path.join(OUT, "收录台账.tsv")
RESCUE_LOG = os.path.join(ROOT, "06-资讯监控", "抢救日志.md")
STATE = os.path.join(ROOT, "06-资讯监控", "_rescue_state.json")
GH = os.environ.get("GH", r"C:\Users\Administrator\.workbuddy\gh-cli\bin\gh.exe")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

HDR = ["id", "first_seen_utc", "source_id", "kind", "name", "slug", "commit",
       "url", "category", "priority", "status", "local_path", "sha256", "bytes", "verify"]

# 与 scene_dl.py 同一条硬闸门(名字/URL 里出现这些的一律不抓,即使有人误写进登记表)
BAN = re.compile(r"\.nsp$|\.xci$|\.iso$|keys\.?dump|merged_keys|prod\.keys|romset|warez|dump pack", re.I)

# 从新闻正文里挖 GitHub 仓库链接(排除常见非仓库路径)
GH_LINK = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:[/#?].*)?$", re.I)
GH_LINK_ANY = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I)
GH_PATH_SKIP = {"features", "topics", "explore", "marketplace", "sponsors", "settings",
                "notifications", "pulls", "issues", "orgs", "users", "about", "pricing",
                "login", "signup", "readme", "apps", "collections", "events", "trending"}


def sh(args, binary=False, timeout=180):
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # 超时不当异常抛:上层按"检查失败"处理并继续,抢救层最怕一个卡死拖垮整轮
        return (124, b"" if binary else "", b"timeout" if binary else "timeout")
    if binary:
        return p.returncode, p.stdout, p.stderr
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def now_utc():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def confirm_gone(slug):
    """双轨确认"真的没了":gh api 说 404 可能是限流/瞬态(彩排实测 godotengine/godot 就被误报过一次,
    而它 118734★ 活得好好的)。必须再用 curl 打一次 HTML 页面:
      200 = 活着(gh api 误报,按 TRANSIENT 处理,下轮再查);
      404 = 真删除;451 = DMCA 法律下架(正是抢救层要抓的信号,算确认消失)。
    返回 (是否确认消失, curl 看到的码)。"""
    code, _ = curl_get("https://github.com/%s" % slug, max_time=60)
    return code in ("404", "451"), code


def gh_api(path):
    rc, out, err = sh([GH, "api", path], timeout=90)
    if rc != 0:
        return None, (err or out).strip()[:160] or ("timeout" if rc == 124 else "rc=%d" % rc)
    try:
        return json.loads(out), ""
    except Exception as e:
        return None, "badjson:%s" % e


def curl_get(url, out=None, max_time=180):
    """下载;给了 out 就存文件返回 (http_code, None);没给就返回 (http_code, 文本)。
    code 形如 "200"/"404"/"429" 或 "curl_err_28" —— 必须拿到 HTTP 码,
    否则 citron-emu.com 这种 429 的页面会被当成正常快照存下来(彩排实测踩到)。"""
    args = ["curl.exe", "-sL", "--max-time", str(max_time), "-A", UA, "-w", "\n%{http_code}"]
    if out:
        args += ["-o", out]
    args.append(url)
    try:
        rc, so, se = sh(args, binary=True, timeout=max_time + 30)
    except subprocess.TimeoutExpired:
        return ("curl_err_28", b"" if out else "")
    if rc != 0:
        return ("curl_err_%d" % rc, b"" if out else "")
    if out:
        return ("200" if os.path.exists(out) else "no_file", None)
    text = so.decode("utf-8", "replace")
    code = "200"
    if "\n" in text:
        text, code = text.rsplit("\n", 1)
    return (code.strip() or "000", text)


def slug_of(url):
    p = urlparse(url)
    parts = [x for x in p.path.split("/") if x]
    if len(parts) >= 2 and parts[0] not in GH_PATH_SKIP:
        return "%s/%s" % (parts[0], parts[1])
    return ""


def load_registry():
    rows = []
    if not os.path.exists(REG):
        return rows
    with open(REG, encoding="utf-8", newline="") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            r = dict(zip(head, p + [""] * (len(head) - len(p))))
            if r.get("enabled", "1") != "0":
                rows.append(r)
    return rows


def load_done():
    """已抓过的 (slug, commit) 集合 + 站点上次快照 sha + git 镜像上次 HEAD。"""
    done, site_sha, git_head = set(), {}, {}
    if os.path.exists(RESCUE_LEDGER):
        with open(RESCUE_LEDGER, encoding="utf-8", newline="") as fh:
            head = fh.readline().rstrip("\n").split("\t")
            for line in fh:
                p = line.rstrip("\n").split("\t")
                r = dict(zip(head, p + [""] * (len(head) - len(p))))
                if r.get("slug") and r.get("commit") and r.get("status") == "CAPTURED":
                    done.add((r["slug"], r["commit"]))
                if r.get("kind") == "site_snapshot" and r.get("sha256"):
                    site_sha[r["url"]] = r["sha256"]
                if r.get("kind") == "git_mirror" and r.get("url") and r.get("commit"):
                    git_head[r["url"]] = r["commit"]
    return done, site_sha, git_head


def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def append_rescue_ledger(row):
    fresh = not os.path.exists(RESCUE_LEDGER)
    os.makedirs(OUT, exist_ok=True)
    with open(RESCUE_LEDGER, "a", encoding="utf-8", newline="") as fh:
        if fresh:
            fh.write("\t".join(HDR) + "\n")
        fh.write("\t".join(str(row.get(c, "")) for c in HDR) + "\n")


def ledger_row(rid, source_id, kind, name, slug, commit, url, category, priority,
               status, local_path="", sha="", nbytes=0, verify="LOCAL_ONLY"):
    return {"id": rid, "first_seen_utc": now_utc(), "source_id": source_id, "kind": kind,
            "name": name, "slug": slug, "commit": commit, "url": url, "category": category,
            "priority": priority, "status": status, "local_path": local_path,
            "sha256": sha, "bytes": nbytes, "verify": verify if status == "CAPTURED" else ""}


# ---------------- 三种抓取动作 ----------------

def capture_src(slug, source_id, category, priority, dry, done):
    """GitHub 仓库活着就抓源码 tarball(codeload,按最新 commit);有新 commit 才再抓。"""
    if BAN.search(slug):
        return ("BANNED", slug, "")
    info, err = gh_api("repos/" + slug)
    if info is None:
        # 单通道不判死刑:先双轨确认(见 confirm_gone 注释),瞬故障留给下一轮
        gone, code2 = confirm_gone(slug)
        if gone:
            return ("GONE", slug, "%s|curl=%s" % (err, code2))
        return ("TRANSIENT", slug, err)
    branch = info.get("default_branch") or "HEAD"
    commits, err = gh_api("repos/%s/commits?per_page=1" % slug)
    if not commits:
        # HTTP 409 "Git Repository is empty" = 仓库还在但内容被清空(下架/剥离的中间态),
        # 这本身就是要告警的信号 —— 2026-10-20 实测 MeloNX/MeloNX 就是这个状态
        if err and ("empty" in err.lower() or "409" in err):
            return ("EMPTY", slug, err)
        return ("ERROR", slug, err or "no-commits")
    sha = commits[0]["sha"]
    if (slug, sha) in done:
        return ("NOCHANGE", slug, sha[:8])
    if dry:
        return ("WOULD_CAPTURE", slug, sha[:8])
    dest = os.path.join(OUT, "%s__%s.tar.gz" % (slug.replace("/", "__"), sha[:8]))
    url = "https://codeload.github.com/%s/tar.gz/%s" % (slug, sha)
    # 抢救层最忌"一次网络抖动就当抓过了":首轮实测 6 个主线仓全部因瞬时故障失败,
    # 重跑才成功。所以下载失败在原地重试一次,还不行才留给下一轮(没进台账=下轮会再抓)。
    code, _ = curl_get(url, out=dest)
    if code != "200" or not os.path.exists(dest) or os.path.getsize(dest) < 1024:
        if os.path.exists(dest):
            os.remove(dest)
        code, _ = curl_get(url, out=dest, max_time=300)
    if code != "200" or not os.path.exists(dest) or os.path.getsize(dest) < 1024:
        if os.path.exists(dest):
            os.remove(dest)
        return ("ERROR", slug, code or "empty")
    digest = sha256_of(dest)
    append_rescue_ledger(ledger_row(
        "rs__%s__%s" % (slug.replace("/", "__"), sha[:8]), source_id, "source_tarball",
        info.get("full_name", slug), slug, sha, "https://github.com/" + slug,
        category, priority, "CAPTURED", os.path.relpath(dest, ROOT).replace(os.sep, "/"),
        digest, os.path.getsize(dest)))
    return ("CAPTURED", slug, sha[:8])


def _norm_html(body):
    """页面判重前的归一化:剥掉每次都变的噪音,否则"页面无变化"永远不成立。
    实测七类(前四类 2026-10-20 彩排踩的,后三类 2026-10-22 对重复快照做 diff 补的):
    Cloudflare challenge 参数 __CF$cv$params={r:'16位hex',t:'base64'}(eden/ryujinx 站都有)、
    Forgejo 页脚渲染耗时 Page/Template: <strong>325ms</strong>(自建 git 站每请求都不同)、
    Forgejo/Gitea 的 CSRF 令牌(长 hex)、epoch/构建号长数字;
    citron-emu.com 停车页的点击追踪 data-ct="<80+位 base64url>"(每请求随机,10-21 一天存了 5 份)、
    LiteSpeed 插件的 bv_unique_id:"<16位>" 与 <template id="<20位>"></template>
    (ryujinx.io 10-20~10-21 存了 3 份,归一化后逐行 diff 只剩这两类)。"""
    b = re.sub(r"__CF\$cv\$params=\{[^}]*\}", "", body)
    b = re.sub(r"<strong>\d+ms</strong>", "", b)
    b = re.sub(r"[a-f0-9]{32,}", "", b)
    b = re.sub(r"\b\d{10,}\b", "", b)
    b = re.sub(r'data-ct="[A-Za-z0-9_\-]{30,}"', "", b)
    b = re.sub(r'"bv_unique_id":"[A-Za-z0-9]{8,}"', "", b)
    b = re.sub(r'bv_unique_id="[A-Za-z0-9]{8,}"', "", b)
    b = re.sub(r'<template id="[A-Za-z0-9]{12,}"></template>', "", b)
    b = re.sub(r'data-wp-key="[0-9a-f]{10,}"', "", b)
    b = re.sub(r'&quot;imageId&quot;:&quot;[0-9a-f]{10,}&quot;', "", b)
    b = re.sub(r'"[0-9a-f]{13}":', "", b)                 # WP 交互 API 的块实例 key(裸 JSON 形态)
    b = re.sub(r'sessionId: "[0-9a-f-]{36}"', "", b)
    b = re.sub(r'ysid":"[A-Za-z0-9]{10,}"', "", b)
    b = re.sub(r'Template: [0-9a-f]{16,}', "", b)         # Airlift 优化器模板号
    b = re.sub(r'Cached Timestamp: [^,\n]+', "", b)       # Airlift 缓存时间戳,每请求都不同
    b = re.sub(r'Optimization Time: [0-9.]+ms', "", b)    # Airlift 优化耗时,每请求都不同
    return b


def snapshot_site(url, source_id, category, priority, dry, site_sha):
    """页面快照:内容没变就不重复存(按 sha 去重),变了才落盘 —— 站点结构突变正是出事前兆。"""
    host = urlparse(url).netloc.replace(":", "_")
    code, body = curl_get(url)
    if code != "200" or not body:
        return ("ERROR", url, code or "empty")
    # JS 挑战页( citron 停车站的 Loading... + location.replace,体内带 JWT,每次都不一样):
    # 这不是站点内容,是 bot 墙 —— 不当成 CAPTURED 存,否则每轮挑战页都新存一份、sha 还永远不同。
    if re.search(r"<title>Loading\.\.\.</title>", body) and "location.replace" in body:
        return ("BLOCKED", url, "js_challenge_page")
    digest = hashlib.sha256(_norm_html(body).encode("utf-8", "replace")).hexdigest()
    if site_sha.get(url) == digest:
        return ("NOCHANGE", url, digest[:8])
    if dry:
        return ("WOULD_CAPTURE", url, digest[:8])
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M")
    dest = os.path.join(OUT, "_sites", "%s__%s.html" % (host, ts))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(body)
    append_rescue_ledger(ledger_row(
        "site__%s__%s" % (host, ts), source_id, "site_snapshot", host, "", "",
        url, category, priority, "CAPTURED",
        os.path.relpath(dest, ROOT).replace(os.sep, "/"), digest, len(body)))
    return ("CAPTURED", url, digest[:8])


def git_mirror(url, source_id, category, priority, dry, last_head=""):
    """git clone --mirror(裸库全量镜像);已镜像过的做 remote update。
    HEAD 没变就不写台账行(否则每轮 remote update 都记一条,台账无限涨)。"""
    host = urlparse(url).netloc.replace(":", "_")
    dest = os.path.join(OUT, "_git", host)
    if dry:
        return ("WOULD_CAPTURE", url, "")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.isdir(dest):
        rc, _, err = sh(["git", "-C", dest, "remote", "update", "--prune"], timeout=300)
    else:
        rc, _, err = sh(["git", "clone", "--mirror", url, dest], timeout=300)
    if rc != 0:
        return ("GONE" if rc == 128 else "ERROR", url, err.strip()[:120])
    rc, out, _ = sh(["git", "-C", dest, "rev-parse", "HEAD"])
    head = out.strip() if rc == 0 else ""
    if head and head == last_head:
        return ("NOCHANGE", url, head[:12])
    size = 0
    for dp, _, fs in os.walk(dest):
        for f in fs:
            try:
                size += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    append_rescue_ledger(ledger_row(
        "git__%s__%s" % (host, (head or dt.datetime.now().strftime("%H%M"))[:12]),
        source_id, "git_mirror", host, "", head, url, category, priority, "CAPTURED",
        os.path.relpath(dest, ROOT).replace(os.sep, "/"), "", size))
    return ("CAPTURED", url, head[:12])


# ---------------- 雷达 ----------------

def run_radar(entry, radar_days, dry, done, known_slugs):
    q = entry.get("radar_q", "")
    rx = re.compile(entry.get("radar_rx", ""), re.I) if entry.get("radar_rx") else None
    if not q:
        return []
    hits = []
    # 查询词必须 URL 编码:"re3 gta" 这种带空格的直接塞给 gh api 会被它卡死(实测挂 90 秒)
    data, err = gh_api("search/repositories?q=%s&sort=created&order=desc&per_page=30" % urlquote(q))
    if not data:
        return [("RADAR_ERR", q, err)]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=radar_days)
    for it in data.get("items", []):
        full = it.get("full_name", "")
        created = it.get("created_at") or ""
        try:
            cdt = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
        except Exception:
            continue
        if cdt < cutoff:
            continue
        # 只按仓库名匹配,不按 description:彩排实测 "re3 gta" 这条雷达按 full+desc 匹配
        # 捞回 irregularnetwork/GTA-Skate-3-Trilogy 这种只是名字里带 gta 的无关仓。
        # 线名进仓库名才算同线镜像(hottabxp/re3、codepdbh/re3-gta-advance-port 都能中)。
        if rx and not rx.search(full):
            continue
        if full in known_slugs:
            hits.append(("KNOWN", full, created[:10]))
            continue
        if entry.get("action") == "alert":          # 泄露 SDK 线:只告警不抓
            hits.append(("ALERT_ONLY", full, created[:10]))
            continue
        st, slug, extra = capture_src(full, entry["id"], entry.get("category", ""),
                                      entry.get("priority", ""), dry, done)
        hits.append((st, full, extra or created[:10]))
        if st == "CAPTURED":
            known_slugs.add(full)
    return hits


# ---------------- 情报面:新闻条目里的 GitHub 链接 ----------------

def news_targets(days):
    """台账里最近 N 天命中"下架信号"的条目 -> 抓正文 -> 挖 GitHub 仓库链接。"""
    if not os.path.exists(LEDGER) or days <= 0:
        return []
    cutoff = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    import csv
    with open(LEDGER, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if not (r.get("flag_focus") or "").__contains__("下架抢救"):
                continue
            if (r.get("first_seen_utc") or "")[:10] < cutoff:
                continue
            out.append((r.get("title", ""), r.get("url", "")))
    return out


def links_from_news(days):
    found = []
    for title, url in news_targets(days):
        code, body = curl_get(url, max_time=60)
        if code or not body:
            continue
        for m in GH_LINK_ANY.finditer(body):
            slug = "%s/%s" % (m.group(1), m.group(2))
            owner, repo = m.group(1), m.group(2)
            if owner.lower() in GH_PATH_SKIP or repo.lower() in GH_PATH_SKIP:
                continue
            if BAN.search(slug):
                continue
            if slug not in found:
                found.append(slug)
    return found


# ---------------- 存在性巡检 ----------------

def sweep_registry_sources(dry, state):
    """已挂 GitHub 源里谁 404 了立刻告警(gh api 跟随改名,404 = 真删除)。结果缓存 6 小时。
    注意:这个函数天生就是查**源登记表里的仓**——所以调用方传进来的 known_slugs(雷达去重用)
    绝不能拿来跳过一个都不查(彩排实测踩过:第一版把 known_slugs 当跳过集,结果查了 0 个)。"""
    alerts, checked = [], 0
    if not os.path.exists(SRC_REG):
        return alerts, checked
    last = state.setdefault("sweep", {})
    now = time.time()
    with open(SRC_REG, encoding="utf-8", newline="") as fh:
        fh.readline()
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < 4 or p[3] != "1" or "github.com/" not in p[2]:
                continue
            slug = slug_of(p[2])
            if not slug:
                continue
            ts = last.get(slug, 0)
            if now - ts < 6 * 3600:
                continue
            checked += 1
            info, err = gh_api("repos/" + slug)
            if info is None:
                gone, code2 = confirm_gone(slug)   # 双轨确认,瞬故障不当消失
                if gone:
                    alerts.append((slug, p[1]))
                    if not dry:
                        append_rescue_ledger(ledger_row(
                            "gone__%s" % slug.replace("/", "__"), "sweep", "gone_alert",
                            p[1], slug, "", p[2], "已挂源消失", "P0", "GONE"))
                else:
                    last[slug] = 0                 # 没确认就不进 6 小时缓存,下轮重查
                    continue
            last[slug] = now
    return alerts, checked


# ---------------- 输出 ----------------

def write_log(lines):
    os.makedirs(os.path.dirname(RESCUE_LOG), exist_ok=True)
    with open(RESCUE_LOG, "a", encoding="utf-8") as fh:
        fh.write("\n## %s 轮次\n\n" % dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
        fh.write("\n".join(lines) + "\n")


def write_daily_section(lines):
    rep = os.path.join(ROOT, "06-资讯监控", "日报", dt.date.today().isoformat() + ".md")
    if not os.path.exists(rep):
        return
    body = open(rep, encoding="utf-8").read()
    # 日报里只留**最新一轮**的抢救段:2 小时频率下每轮都追加会把日报撑爆
    # (2026-10-20 实测一天 13 轮 = 13 个段)。完整逐轮历史在 06-资讯监控/抢救日志.md。
    head = "## 抢救层动态"
    if head in body:
        out, skip = [], False
        for line in body.splitlines():
            if line.startswith(head):
                skip = True
                continue
            if skip and line.startswith("## "):
                skip = False
            if not skip:
                out.append(line)
        body = "\n".join(out).rstrip() + "\n"
    body += ("\n## 抢救层动态(%s 轮;完整历史看 `06-资讯监控/抢救日志.md`)\n\n" %
             dt.datetime.now().strftime("%H:%M")) + "\n".join(lines) + "\n\n"
    # **原子替换**:先写临时文件再 os.replace。2026-10-20 实测教训 —— 直接 open(rep,"w") 是先截断再写,
    # 进程万一死在中间(管道被 Select-Object 掐断就是这么死的),日报会变成 0 字节,整天的报表全没。
    tmp = rep + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.replace(tmp, rep)


def fmt(lines):
    return [("- " + l) for l in lines]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=0, help="循环模式:每 N 秒跑一轮(0=单轮)")
    ap.add_argument("--dry-run", action="store_true", help="只检查不落盘")
    ap.add_argument("--no-news", action="store_true", help="跳过新闻信号(台账下架条目挖链接)")
    ap.add_argument("--no-sweep", action="store_true", help="跳过已挂源存在性巡检")
    ap.add_argument("--radar-days", type=int, default=30, help="雷达只认 N 天内新建的仓")
    ap.add_argument("--news-days", type=int, default=7,
                    help="新闻信号回看台账最近 N 天的下架报道(默认 7;下架事件一周内都还值得挖链接)")
    args = ap.parse_args()

    # 并发锁(2026-10-21 新增):抢救层现在有两个跑者——Qoder_Handheld_Rescue 计划任务
    # (每 2 小时)和 daily_run 里的日更步,外加手动跑。三个都可能撞在同一批文件上
    # (下架抢救台账/抢救日志/当天日报),无锁并发会交叉写。锁文件带 pid,
    # pid 活着就让路,pid 死了(上次异常退出)自动清锁继续。
    lock = os.path.join(os.path.dirname(RESCUE_LOG), "_rescue.lock")
    if os.path.exists(lock):
        try:
            old_pid = int(open(lock, encoding="utf-8").read().strip() or 0)
        except ValueError:
            old_pid = 0
        alive = False
        if old_pid > 0:
            r = subprocess.run(["tasklist", "/FI", "PID eq %d" % old_pid, "/NH"],
                               capture_output=True)
            alive = ("%d" % old_pid) in r.stdout.decode("utf-8", "replace")
        if alive:
            print("另一轮抢救监控在跑(pid %d),本轮让路" % old_pid)
            return 0
        print("清掉陈旧的抢救锁(pid %d 已不在)" % old_pid)
        try:
            os.remove(lock)
        except OSError:
            pass
    with open(lock, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    try:
        _main_loop(args)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass
    return 0


def _main_loop(args):
    while True:
        t0 = dt.datetime.now()
        dry = args.dry_run
        done, site_sha, git_head = load_done()
        state = load_state()
        registry = load_registry()
        known_slugs = {slug_of(r["watch_url"]) for r in registry if r.get("watch_url")}
        # 已挂源的 GitHub 仓库也算"已知",雷达命中它们不算新发现
        if os.path.exists(SRC_REG):
            with open(SRC_REG, encoding="utf-8", newline="") as fh:
                fh.readline()
                for line in fh:
                    p = line.rstrip("\n").split("\t")
                    if len(p) >= 4 and "github.com/" in (p[2] or ""):
                        s = slug_of(p[2])
                        if s:
                            known_slugs.add(s)

        lines, n_cap, n_gone, n_radar = [], 0, 0, 0

        # ① 登记表逐项
        for r in registry:
            action = r.get("action", "")
            url = r.get("watch_url", "")
            sid = r["id"]
            if action == "capture_src":
                st, slug, extra = capture_src(slug_of(url), sid, r.get("category", ""),
                                              r.get("priority", ""), dry, done)
                if st == "CAPTURED":
                    n_cap += 1
                    lines.append("抓取 **%s** %s @%s" % (r["name"], slug, extra))
                elif st == "GONE":
                    n_gone += 1
                    lines.append("⚠ **已消失** %s %s(%s)——立刻去 Wayback 找快照" % (r["name"], slug, extra or "404"))
                elif st == "EMPTY":
                    n_gone += 1
                    lines.append("⚠ **仓库已被清空** %s(%s)——内容被剥离,等同下架,留证" % (r["name"], slug))
                elif st == "NOCHANGE":
                    lines.append("无变化 %s @%s" % (slug, extra))
                elif st == "WOULD_CAPTURE":
                    lines.append("[dry-run] 将抓取 %s @%s" % (slug, extra))
                elif st == "TRANSIENT":
                    lines.append("检查未确认 %s(gh api 瞬态,双轨复核仍活着,下轮再查)" % slug)
                else:
                    lines.append("检查失败 %s(%s)" % (slug, st))
            elif action == "snapshot_site":
                st, u, extra = snapshot_site(url, sid, r.get("category", ""),
                                             r.get("priority", ""), dry, site_sha)
                if st == "CAPTURED":
                    n_cap += 1
                    lines.append("抓取页面快照 %s(%s)" % (u, extra))
                elif st == "WOULD_CAPTURE":
                    lines.append("[dry-run] 将存页面快照 %s" % u)
                elif st == "BLOCKED":
                    lines.append("站点返回 JS 挑战页(未存快照;不是下架,是 bot 墙)%s" % u)
                elif st == "ERROR":
                    n_gone += 1
                    lines.append("⚠ 站点异常 %s(%s)" % (u, extra))
                else:
                    lines.append("页面无变化 %s" % u)
            elif action == "git_mirror":
                st, u, extra = git_mirror(url, sid, r.get("category", ""),
                                          r.get("priority", ""), dry,
                                          git_head.get(url, ""))
                if st == "CAPTURED":
                    n_cap += 1
                    lines.append("抓取 git 裸库镜像 %s(HEAD %s)" % (u, extra))
                elif st == "NOCHANGE":
                    lines.append("git 镜像无新提交 %s(HEAD %s)" % (u, extra))
                elif st == "WOULD_CAPTURE":
                    lines.append("[dry-run] 将镜像 git 裸库 %s" % u)
                elif st == "GONE":
                    n_gone += 1
                    lines.append("⚠ git 站不可达 %s(%s)" % (u, extra))
                else:
                    lines.append("git 镜像异常 %s(%s)" % (u, extra))
            elif action == "alert":
                # alert 行分两种:带 radar_q 的是"只告警雷达"(泄露 SDK 线),走雷达但命中不抓;
                # 不带的是"残存仓存在性盯梢"(Kenji-NX issue 仓),只查不抓。
                if r.get("radar_q"):
                    hits = run_radar(r, args.radar_days, dry, done, known_slugs)
                    for st, slug, extra in hits:
                        if st == "ALERT_ONLY":
                            lines.append("雷达发现(只告警不抓) %s %s" % (slug, extra))
                        elif st == "RADAR_ERR":
                            lines.append("雷达查询失败 %s(%s)" % (slug, extra))
                    continue
                st, slug, extra = capture_src(slug_of(url), sid, r.get("category", ""),
                                              r.get("priority", ""), True, done)  # 只查不抓
                if st == "GONE":
                    n_gone += 1
                    lines.append("⚠ 残存仓也没了 %s(%s)" % (r["name"], extra or "404"))
                elif st == "EMPTY":
                    n_gone += 1
                    lines.append("⚠ 残存仓已被清空 %s(%s)" % (r["name"], extra))
                else:
                    lines.append("残存仓仍在 %s(%s)" % (r["name"], extra))
            elif action == "radar":
                hits = run_radar(r, args.radar_days, dry, done, known_slugs)
                for st, slug, extra in hits:
                    if st == "CAPTURED":
                        n_cap += 1
                        n_radar += 1
                        lines.append("雷达命中并抓取 **%s** @%s" % (slug, extra))
                    elif st == "ALERT_ONLY":
                        lines.append("雷达发现(只告警) %s %s" % (slug, extra))
                    elif st == "KNOWN":
                        pass
                    elif st == "RADAR_ERR":
                        lines.append("雷达查询失败 %s(%s)" % (slug, extra))
                    elif st == "EMPTY":
                        lines.append("雷达目标 %s 是空仓库(留证)" % slug)
                    else:
                        lines.append("雷达目标 %s -> %s" % (slug, st))

        # ② 存在性巡检(已挂 GitHub 源)
        if not args.no_sweep:
            alerts, checked = sweep_registry_sources(dry, state)
            for slug, name in alerts:
                n_gone += 1
                lines.append("⚠ **已挂源消失** %s(%s)——该源 GitHub 仓库 404,立刻查 Wayback/镜像" % (name, slug))
            lines.append("存在性巡检:查 %d 个已挂 GitHub 源,异常 %d 个" % (checked, len(alerts)))

        # ③ 情报面:下架新闻里的 GitHub 链接
        if not args.no_news:
            links = links_from_news(args.news_days)
            fresh = [s for s in links if s not in known_slugs]
            for slug in fresh[:10]:
                if (slug, "") in done:
                    continue
                st, sl, extra = capture_src(slug, "news", "新闻信号", "P0", dry, done)
                if st == "CAPTURED":
                    n_cap += 1
                    known_slugs.add(slug)
                    lines.append("新闻信号命中并抓取 **%s** @%s" % (slug, extra))
                elif st == "GONE":
                    lines.append("新闻信号指向的仓库已 404:%s(可能刚被扫,留证)" % slug)
                else:
                    lines.append("新闻信号目标 %s -> %s" % (slug, st))
            if fresh:
                lines.append("新闻信号:下架报道里挖到 %d 个 GitHub 链接" % len(fresh))

        if not dry:
            save_state(state)
        head = "本轮:抓取 %d / 告警 %d / 雷达命中 %d(登记表 %d 项%s)" % (
            n_cap, n_gone, n_radar, len(registry),
            "" if args.no_news else " +新闻信号")
        out = [head] + lines
        print("\n".join(out))
        if not dry:
            write_log(out)
            write_daily_section(out)
        print("耗时 %.1fs;台账 %s" % (
            (dt.datetime.now() - t0).total_seconds(),
            "未写入(dry-run)" if dry else RESCUE_LEDGER))
        if not args.watch:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
