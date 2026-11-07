#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_dl.py —— 合法资源下载器(带上游哈希对账)

只收这三类,而且必须能对上账:
  1) release 资产:GitHub 现在会给 assets[].digest = "sha256:...";下载后逐字节比对,
     对不上就标 MISMATCH 并保留文件但拒绝计入"已验证"。上游没给 digest 的标 UPSTREAM_ABSENT。
  2) 源码快照(source 模式):拉仓库 zipball,只有本地 sha256,标 LOCAL_ONLY —— 它能防"我这边坏了",
     防不了"上游换了内容",所以清单里会单列,不和 release 混。
  3) raw 单文件:同 release 处理,但无上游 digest -> LOCAL_ONLY。

绝不收:商业游戏本体(NSP/XCI/VPK/ISO)、prod.keys/merged_keys、解密工具、改存档与联机作弊工具、
以及任何网盘包(夸克/百度网盘等) —— 网盘包给不出哈希,无法验证,这正是它不进台账的原因。

用法:
  py -3 _工具脚本/scene_dl.py                 # 跑登记表里 enabled=1 的全部
  py -3 _工具脚本/scene_dl.py --only gh_atmosphere,vita_vitashell
  py -3 _工具脚本/scene_dl.py --dry-run       # 只看会下什么、多大,不落盘
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from urllib.parse import quote as urlquote

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "06-资讯监控", "合法收录登记表.tsv")
OUT = os.path.join(ROOT, "04-游戏资源库", "爆款收录")
LEDGER = os.path.join(OUT, "收录台账.tsv")
GH = os.environ.get("GH", r"C:\Users\Administrator\.workbuddy\gh-cli\bin\gh.exe")

HDR = ["id", "title", "asset", "repo", "tag", "kind", "bytes", "sha256_local",
       "sha256_upstream", "verify", "needs_data", "dest", "fetched_utc", "url"]

# 一条硬闸门:名字里出现这些词的一律拒收,即使有人误写进登记表
BAN = re.compile(r"\.nsp$|\.xci$|\.iso$|keys\.?dump|merged_keys|prod\.keys|romset|warez|dump pack", re.I)


def sh(args, binary=False):
    p = subprocess.run(args, capture_output=True)
    if binary:
        return p.returncode, p.stdout, p.stderr
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def load():
    rows = []
    with open(REG, encoding="utf-8", newline="") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            r = dict(zip(head, p + [""] * (len(head) - len(p))))
            if r.get("enabled", "1") == "1":
                rows.append(r)
    return rows


def load_done():
    done = set()
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8", newline="") as fh:
            head = fh.readline().rstrip("\n").split("\t")
            for line in fh:
                p = line.rstrip("\n").split("\t")
                r = dict(zip(head, p + [""] * (len(head) - len(p))))
                done.add((r["id"], r["asset"], r["sha256_local"]))
    return done


def gh_api(path):
    rc, out, err = sh([GH, "api", path])
    if rc != 0:
        return None, err.strip()[:160]
    try:
        return json.loads(out), ""
    except Exception as e:
        return None, "badjson:%s" % e


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def plan(rows):
    """把登记表展开成具体的下载任务(资产级)。"""
    tasks, notes = [], []
    for r in rows:
        kind = r.get("kind", "release")
        repo = r["repo"]
        if kind == "release":
            tag = (r.get("tag") or "").strip()
            # 一个仓库可以按平台发好几个 tag(port0r 的 Switch 版在 switch-v0.5.3,latest 是 Quest 包)。
            # 登记了 tag 就按 tags/ 取,没登记才用 latest —— 否则会"抓错平台还自以为成功"。
            ep = ("repos/%s/releases/tags/%s" % (repo, urlquote(tag, safe=""))
                  if tag else "repos/%s/releases/latest" % repo)
            rel, err = gh_api(ep)
            if not rel and not tag:
                # /releases/latest 只看"正式版",只有 pre-release 的仓库必定 404
                # (PS5/switch 自制软件圈一大半是这样)。退到全量列表,取最新一个带资产且非草稿的。
                rels, _e2 = gh_api("repos/%s/releases?per_page=100" % repo)
                rel = next((x for x in (rels or []) if not x.get("draft") and x.get("assets")), None)
                if rel:
                    notes.append((r["id"], "latest 404,改用 %s(%s)" % (
                        rel.get("tag_name"), "pre-release" if rel.get("prerelease") else "release")))
            if not rel:
                notes.append((r["id"], "取 release 失败(%s): %s" % (ep, err)))
                continue
            pat = re.compile(r.get("filter") or r".*")
            mx = float(r.get("max_mb") or 400) * 1048576
            hit = [a for a in rel.get("assets", []) if pat.search(a["name"])]
            if not hit:
                notes.append((r["id"], "无资产匹配 filter=%r(共 %d 个资产)" % (
                    r.get("filter"), len(rel.get("assets", [])))))
            for a in hit:
                if BAN.search(a["name"]):
                    notes.append((r["id"], "拒收 %s:命中黑名单词" % a["name"]))
                    continue
                if a["size"] > mx:
                    notes.append((r["id"], "跳过 %s: %.0f MB 超过 max_mb=%s" % (
                        a["name"], a["size"] / 1048576, r.get("max_mb"))))
                    continue
                dig = (a.get("digest") or "").replace("sha256:", "")
                tasks.append({"id": r["id"], "title": r["name"], "asset": a["name"],
                              "repo": repo, "tag": rel.get("tag_name", ""), "kind": "release",
                              "bytes": a["size"], "url": a["browser_download_url"],
                              "upstream": dig, "needs_data": r.get("needs_data", ""),
                              "note": r.get("note", "")})
        elif kind == "source":
            meta, err = gh_api("repos/%s" % repo)
            if not meta:
                notes.append((r["id"], "取仓库失败: %s" % err))
                continue
            br = meta.get("default_branch", "master")
            tasks.append({"id": r["id"], "title": r["name"], "asset": "%s-%s.zip" % (repo.split("/")[-1], br),
                          "repo": repo, "tag": br, "kind": "source",
                          "bytes": 0, "url": "https://codeload.github.com/%s/zip/refs/heads/%s" % (repo, br),
                          "upstream": "", "needs_data": r.get("needs_data", ""),
                          "note": r.get("note", "")})
        elif kind == "raw":
            tasks.append({"id": r["id"], "title": r["name"], "asset": os.path.basename(r["url"].split("?")[0]),
                          "repo": r.get("repo", "-"), "tag": "-", "kind": "raw", "bytes": 0,
                          "url": r["url"], "upstream": "", "needs_data": r.get("needs_data", ""),
                          "note": r.get("note", "")})
    return tasks, notes


DATA_EXT = re.compile(r"\.(map|iso|rpf|nsf|big|cif|wad|xbe|gcm|rvz|7z0|blob)$", re.I)
# .nsp/.xci/.pkg/.vpk 是"安装包容器"而不是游戏数据本身:自制软件本来就装成 .vpk。
# 所以容器只在"商业规模"以上才点名,小容器另列一节说明判定理由,不许静默吃掉。
CONTAINER_EXT = re.compile(r"\.(nsp|xci|pkg|vpk)$", re.I)
CONTAINER_BIG = 200 * 1048576
BIG = 60 * 1048576


def audit():
    """扫包复检:源码快照里若混进商业游戏数据(大文件或游戏数据扩展名),必须点名,不能默默入账。"""
    findings, bigs, containers = [], [], []
    for dirpath, _, files in os.walk(OUT):
        for fn in files:
            p = os.path.join(dirpath, fn)
            members = []
            try:
                if fn.lower().endswith(".zip"):
                    import zipfile
                    with zipfile.ZipFile(p) as z:
                        members = [(i.filename, i.file_size) for i in z.infolist() if not i.is_dir()]
                elif fn.lower().endswith((".tar.bz2", ".tar.gz", ".tgz")):
                    import tarfile
                    with tarfile.open(p) as t:
                        members = [(m.name, m.size) for m in t.getmembers() if m.isfile()]
            except Exception as e:
                findings.append((os.path.relpath(p, ROOT), "打不开:%s" % e))
                continue
            rel = os.path.relpath(p, ROOT)
            if not members:
                # 裸文件(nro/pkg/vpk/bin/zipball 之外没法解压的东西)也要过量级闸门,不能因为"打不开"就静默跳过
                sz = os.path.getsize(p)
                if CONTAINER_EXT.search(fn) and sz > CONTAINER_BIG:
                    findings.append((rel, "裸安装包容器 >%.0f MB:%s (%.1f MB)" % (CONTAINER_BIG / 1048576, fn, sz / 1048576)))
                elif sz > BIG:
                    bigs.append((rel, "裸文件:%s (%.1f MB)" % (fn, sz / 1048576)))
                continue
            hits = [(n, s) for n, s in members if DATA_EXT.search(n) and s > 262144]
            for n, s in hits:
                findings.append((os.path.relpath(p, ROOT), "包内疑似游戏数据:%s (%.1f MB)" % (n.replace("\\", "/"), s / 1048576)))
            cons = sorted([(n, s) for n, s in members if CONTAINER_EXT.search(n)], key=lambda x: -x[1])
            for n, s in cons:
                row = (os.path.relpath(p, ROOT), "包内安装包容器:%s (%.1f MB)" % (n.replace("\\", "/"), s / 1048576))
                (findings if s > CONTAINER_BIG else containers).append(row)
            top = max(members, key=lambda x: x[1])
            if top[1] > BIG:
                bigs.append((os.path.relpath(p, ROOT), "包内最大文件:%s (%.1f MB)" % (top[0], top[1] / 1048576)))
    rep = os.path.join(OUT, "复检.md")
    with open(rep, "w", encoding="utf-8") as fh:
        fh.write("# 扫包复检(每次下载后自动重算)\n\n")
        fh.write("- 判定条件:包内出现**游戏数据**扩展名(`.map .iso .rpf .nsf .big .cif .wad .xbe .gcm .rvz .7z0 .blob`)且 >256 KB,或单文件 >60 MB。\n")
        fh.write("- `.nsp/.xci/.pkg/.vpk` 按**安装包容器**处理(自制软件本来就装成 .vpk):"
                  ">%.0f MB 才进\"需要人工判定\",小的进下面第三节的\"已判定容器\",**两条都点名,不静默跳过**。\n" % (CONTAINER_BIG / 1048576))
        fh.write("- 这一步是**产物级**验证:只看文件名为'源码快照'不够,得打开包看里面到底有什么。\n")
        fh.write("- **裸文件**(解压不了的 `.nro/.pkg/.vpk/.bin` 等)同样过量级:>200 MB 的容器进\"需要人工判定\",其他 >60 MB 进\"超大文件\"。\n\n")
        if not findings and not bigs:
            fh.write("## 结论:干净\n\n未发现疑似游戏数据或超大文件。\n")
        if findings:
            fh.write("## 需要人工判定(%d)\n\n" % len(findings))
            for a, b in findings[:40]:
                fh.write("- `%s` — %s\n" % (a, b))
            fh.write("\n")
        if bigs:
            fh.write("## 超大文件(不一定是问题,但要知情)(%d)\n\n" % len(bigs))
            for a, b in bigs[:40]:
                fh.write("- `%s` — %s\n" % (a, b))
            fh.write("\n")
        if containers:
            fh.write("## 已判定为自制容器(仍列出,不静默吃掉)(%d)\n\n" % len(containers))
            for a, b in containers[:60]:
                fh.write("- `%s` — %s\n" % (a, b))
            fh.write("\n> 判定理由:这些是**作者自己 release 出来的自制软件安装包**(.vpk/.nsp 是容器格式,不是游戏数据本体)。"
                      "商业本体一旦超过 %.0f MB 会自动升到上面\"需要人工判定\"那一节。\n" % (CONTAINER_BIG / 1048576))
    print("\n扫包复检:疑似游戏数据 %d 处,超大文件 %d 处,已判定容器 %d 处 -> %s"
          % (len(findings), len(bigs), len(containers), rep))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = load()
    if args.only:
        keep = {x.strip() for x in args.only.split(",") if x.strip()}
        rows = [r for r in rows if r["id"] in keep]
    tasks, notes = plan(rows)
    done = load_done()

    print("计划 %d 个任务(登记 %d 行)" % (len(tasks), len(rows)))
    for t in tasks:
        print("  %-22s %-46s %6.1f MB  upstream_digest=%s" % (
            t["id"], t["asset"], t["bytes"] / 1048576, "有" if t["upstream"] else "无"))
    for n in notes:
        print("  ! %s | %s" % n)
    if args.dry_run:
        return

    os.makedirs(OUT, exist_ok=True)
    fresh = []

    def record(t, dest, loc, verify):
        """**逐条落账**:下载/确认成功一条就立刻追加一行台账。
        2026-10-20 修的坑:原来所有 fresh 行攒到循环结束才一次性 append,结果 10-16 08:38 那轮
        scene_dl 中途死掉(日志里整个 section 连 exit= 都没有),已下载的
        atmosphere-1.12.1 永远没入账 —— 文件在磁盘上、哈希相符,之后每轮都打印"已存在,跳过",
        台账却一直没有这一行。账实相符必须是**逐条**保证,不能靠"跑完这轮"。"""
        row = "\t".join([
            t["id"], t["title"], t["asset"], t["repo"], t["tag"], t["kind"],
            str(os.path.getsize(dest)), loc, t["upstream"], verify, t["needs_data"],
            os.path.relpath(dest, ROOT).replace("\\", "/"),
            dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), t["url"]])
        with open(LEDGER, "a", encoding="utf-8", newline="") as fh:
            if not os.path.exists(LEDGER) or os.path.getsize(LEDGER) == 0:
                fh.write("\t".join(HDR) + "\n")
            fh.write(row + "\n")
        done.add((t["id"], t["asset"], loc))
        fresh.append(row)
        print("%s %-52s %.1f MB  sha256 %s" % (
            {"OK": "√", "MISMATCH": "!!", "UPSTREAM_ABSENT": "?", "LOCAL_ONLY": "~"}[verify],
            t["asset"], os.path.getsize(dest) / 1048576, verify))

    for t in tasks:
        d = os.path.join(OUT, t["id"])
        os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, t["asset"])
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            loc = sha256_of(dest)
            if t["upstream"] and loc == t["upstream"]:
                # 哈希相符也要查台账:文件在、账没记(外部下载/上轮中途死掉)时必须补记,
                # 不能一句"跳过"就把账实差异永远留在那里(2026-10-20 atmosphere 1.12.1 实测)
                if (t["id"], t["asset"], loc) not in done:
                    print("+ %-52s 文件已在磁盘但台账缺行,补记" % t["asset"])
                    record(t, dest, loc, "OK")
                    continue
                print("= %-52s 已存在且哈希相符,跳过" % t["asset"])
                continue
            if not t["upstream"] and (t["id"], t["asset"], loc) in done:
                print("= %-52s 已存在且已入账,跳过" % t["asset"])
                continue
        rc, body, err = 1, "", ""
        for attempt in range(3):          # schannel 的 TLS 抖动能靠重试解决,别一失败就当"这个源不存在"
            rc, body, err = sh(["curl", "-sSL", "--fail", "--max-time", "1800", "-o", dest, t["url"]])
            if rc == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0:
                break
        if rc != 0 or not os.path.exists(dest) or os.path.getsize(dest) == 0:
            print("X %-52s 下载失败 rc=%s %s" % (t["asset"], rc, err.strip()[:120]))
            continue
        loc = sha256_of(dest)
        if not t["upstream"]:
            verify = "UPSTREAM_ABSENT" if t["kind"] == "release" else "LOCAL_ONLY"
        else:
            verify = "OK" if loc == t["upstream"] else "MISMATCH"
        record(t, dest, loc, verify)      # 逐条落账,见 record() 注释里的 10-16 事故

    # 兜底对账:本轮任务之外、磁盘上还躺着没入账的文件(外部下载/历史事故遗留),
    # 也按 (id 目录, 文件名) 补一行 —— 账实相符的最后一班岗。
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8", newline="") as fh:
            head = fh.readline().rstrip("\n").split("\t")
            booked = {line.rstrip("\n").split("\t")[11] for line in fh if line.strip()}
    else:
        head, booked = HDR[:], set()
    orphans = 0
    for dp, _, fs in os.walk(OUT):
        for fn in fs:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            if rel in booked or fn.lower() in ("readme.md", "复检.md", "收录台账.tsv", "_download.log"):
                continue
            pid = os.path.basename(dp)
            t = next((x for x in tasks if x["id"] == pid and x["asset"] == fn), None)
            if t is None:
                t = {"id": pid, "title": pid, "asset": fn, "repo": "-", "tag": "-",
                     "kind": "raw", "upstream": "", "needs_data": "",
                     "url": "https://github.com/%s" % pid.replace("__", "/")}
            loc = sha256_of(p)
            if (t["id"], t["asset"], loc) in done:
                continue
            print("+ 对账补记 %s(磁盘有、台账无)" % rel)
            record(t, p, loc, "LOCAL_ONLY" if not t["upstream"] else
                   ("OK" if loc == t["upstream"] else "MISMATCH"))
            orphans += 1
    if orphans:
        print("对账补记 %d 个遗留文件" % orphans)

    # 台账体检:文件不在了(被判定不收/手工删过)就把该行请出台账,不留幽灵条目
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8", newline="") as fh:
            head = fh.readline().rstrip("\n").split("\t")
            keep, dropped = [], []
            for line in fh:
                p = line.rstrip("\n").split("\t")
                r = dict(zip(head, p + [""] * (len(head) - len(p))))
                (keep if os.path.exists(os.path.join(ROOT, r["dest"])) else dropped).append(line.rstrip("\n"))
        if dropped:
            with open(LEDGER, "w", encoding="utf-8", newline="") as fh:
                fh.write("\t".join(head) + "\n")
                fh.write("\n".join(keep) + "\n")
            print("台账清掉 %d 行(对应文件已不存在):%s" % (
                len(dropped), ", ".join(sorted({d.split("\t")[0] for d in dropped}))))
        rows_all = keep
    else:
        rows_all = []
    total = 0
    for line in rows_all:
        p = line.split("\t")
        try:
            total += int(p[6])
        except (ValueError, IndexError):
            pass
    print("\n本次入账 %d 项;台账累计 %d 项,合计 %.1f MiB = %.1f MB(十进制)"
          % (len(fresh), len(rows_all), total / 1048576, total / 1e6))
    audit()


if __name__ == "__main__":
    main()
