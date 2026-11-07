#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ports_watch.py —— PortMaster 新端口发现层(2026-10-20 新增,不下载,只发现)。

干什么:PortMaster 的端口全走 `PortsMaster/PortMaster-Releases` 仓库(根目录一个端口一个 zip),
本地池已有 632 个 zip,但"上游今天新上了哪个端口/哪个端口换版了"以前没有任何一层在看 ——
论坛和媒体只报**热门**端口,长尾的(独立游戏、同人、老游戏复刻)全靠人工翻仓库。

做法:每天拉一次 git trees(一次 API 调用拿到全量文件名+大小+blob sha),和旧快照比对:
  新文件名        = 新端口(首发)
  同名但 sha 变了 = 该端口换版了
快照落 `06-资讯监控/PortMaster端口快照.tsv`;变化写 `06-资讯监控/PortMaster新端口.md`(累计清单)
并追加当天日报。**本脚本只发现不下载** —— 和 scene_dl 的分工一样:发现层薄、快、全;
收录要你过一眼再写 `合法收录登记表.tsv`(端口本体普遍在 5~60 MB,批量下之前先看清单)。

用法: py -3 _工具脚本/ports_watch.py            (比对并更新快照)
      py -3 _工具脚本/ports_watch.py --dry-run  (只比对,不写任何文件)
"""
import csv
import datetime as dt
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
SNAP = "06-资讯监控/PortMaster端口快照.tsv"
REPORT = "06-资讯监控/PortMaster新端口.md"
LOCAL_POOL = "04-游戏资源库/公版与开源游戏/ports全量合法池"
GH = os.environ.get("GH", r"C:\Users\Administrator\.workbuddy\gh-cli\bin\gh.exe")
REPO = "PortsMaster/PortMaster-Releases"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def sh(a, binary=False, timeout=120):
    p = subprocess.run(a, capture_output=True, timeout=timeout, cwd=ROOT)
    return p.returncode, (p.stdout if binary else p.stdout.decode("utf-8", "replace")), p.stderr


def fetch_tree():
    """一次 git/trees 调用拿全量清单;失败返回 None(不写快照,下轮再试)。"""
    rc, out, err = sh([GH, "api", "repos/%s/git/trees/HEAD?recursive=1" % REPO], timeout=120)
    if rc != 0:
        print("拉 PortMaster 清单失败(gh api): %s" % err.strip()[:160])
        return None
    try:
        data = json.loads(out)
    except Exception as e:
        print("清单 JSON 解析失败: %s" % e)
        return None
    blobs = {}
    for e in data.get("tree", []):
        if e.get("type") == "blob":
            blobs[e["path"]] = (int(e.get("size") or 0), (e.get("sha") or "")[:12])
    return blobs


def load_snap():
    """旧快照 -> {path: (size, sha, first_seen, last_seen, last_change)}。"""
    old = {}
    if os.path.exists(SNAP):
        with open(SNAP, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                if r.get("path"):
                    old[r["path"]] = (int(r["size"] or 0), r.get("sha", ""),
                                      r.get("first_seen", ""), r.get("last_seen", ""),
                                      r.get("last_change", ""))
    return old


def main():
    dry = "--dry-run" in sys.argv
    today = dt.date.today().isoformat()
    blobs = fetch_tree()
    if blobs is None:
        return 1
    old = load_snap()
    new_ports, updated = [], []
    for path, (size, sha) in sorted(blobs.items()):
        o = old.get(path)
        if o is None:
            new_ports.append((path, size))
        elif o[1] != sha:
            updated.append((path, size, o[0]))
    print("PortMaster 清单:%d 个文件 | 新端口 %d | 换版 %d | 快照原有 %d" % (
        len(blobs), len(new_ports), len(updated), len(old)))
    if dry:
        for p, s in new_ports[:30]:
            print("  [新] %-40s %6.1f MB" % (p, s / 1048576))
        for p, s, o in updated[:30]:
            print("  [换版] %-38s %.1f -> %.1f MB" % (p, o / 1048576, s / 1048576))
        print("(dry-run,未写快照)")
        return 0
    with open(SNAP, "w", encoding="utf-8", newline="") as fh:
        fh.write("path\tsize\tsha\tfirst_seen\tlast_seen\tlast_change\n")
        for path, (size, sha) in sorted(blobs.items()):
            o = old.get(path)
            fs = o[2] if o else today
            lc = today if (o is None or o[1] != sha) else (o[4] or fs)
            fh.write("%s\t%d\t%s\t%s\t%s\t%s\n" % (path, size, sha, fs, today, lc))
    # 本地池对照:清单里有、本地还没有的端口(下载候选)。
    # 命名必须归一化再比:本地池是全小写带点(`cave.story-evo.zip`),上游清单是 Title Case 带空格
    # (`Cave Story-evo.zip`)—— 2026-10-20 实测直接按文件名比只有 25/167 命中,全是命名差异。
    def norm(n):
        return n.lower().replace(" ", "").replace(".", "").replace("_", "").replace("-", "")

    local = set()
    if os.path.isdir(LOCAL_POOL):
        for fn in os.listdir(LOCAL_POOL):
            if fn.lower().endswith(".zip"):
                local.add(norm(fn))
    missing = [p for p in blobs if norm(os.path.basename(p)) not in local]
    cat_norm = {norm(os.path.basename(p)) for p in blobs}
    stale = [n for n in sorted(local) if n not in cat_norm]
    if stale:
        print("本地池里有、上游清单没有的:%d 个(历史版本/改名,仅供参考别手动删)" % len(stale))
    lines = []
    if new_ports or updated:
        lines.append("## PortMaster 变化 %s(清单 %d 个)\n\n" % (today, len(blobs)))
        if new_ports:
            lines.append("**新端口 %d 个**(首发,想要就加进 `合法收录登记表.tsv` 再跑 scene_dl):\n\n" % len(new_ports))
            for p, s in new_ports:
                lines.append("- `%s` %.1f MB%s\n" % (
                    p, s / 1048576,
                    "" if norm(os.path.basename(p)) in local else " **本地还没有**"))
            lines.append("\n")
        if updated:
            lines.append("**换版 %d 个**:\n\n" % len(updated))
            for p, s, o in updated:
                lines.append("- `%s` %.1f -> %.1f MB\n" % (p, o / 1048576, s / 1048576))
            lines.append("\n")
        with open(REPORT, "a", encoding="utf-8") as fh:
            fh.write("".join(lines))
        # 追加当天日报(只留最新一轮;完整历史在 PortMaster新端口.md)
        rep = "06-资讯监控/日报/%s.md" % today
        if os.path.exists(rep):
            head = "## PortMaster 新端口"
            body = open(rep, encoding="utf-8").read()
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
            # 原子替换,理由同 rescue_watch:别让"先截断再写"把日报毁在半路
            body += "\n## PortMaster 新端口(%s 轮)\n\n" % dt.datetime.now().strftime("%H:%M")
            body += "".join(lines)
            tmp = rep + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(body)
            os.replace(tmp, rep)
    print("清单有、本地池没有的端口:%d 个(下载候选,不自动下)" % len(missing))
    print("快照 -> %s;变化清单 -> %s" % (SNAP, REPORT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
