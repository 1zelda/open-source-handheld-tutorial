#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量下载 PortMaster 官方标注"自带完整游戏、解压即玩"的全部端口包, 逐个 MD5 校验。

数据源: 02-模拟器库/已clone仓库/R36S专用/PortMaster-Info/ports.json
清单  : 04-游戏资源库/公版与开源游戏/portmaster_r36s_拿来即玩.txt (由 portmaster_r36s_index.py 生成)
输出  : 04-游戏资源库/公版与开源游戏/ports全量合法池/<name>.zip
台账  : 同目录 _manifest.tsv  (name, 状态, 字节, 期望md5, 实得md5, url)

可反复执行: 已存在且 MD5 相符的包直接跳过(断点续传靠 .part 文件)。

用法: py -3 _工具脚本/portmaster_bulk_dl.py [--limit N] [--only 名字前缀]
"""
import hashlib
import io
import json
import os
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INFO = os.path.join(ROOT, "02-模拟器库", "已clone仓库", "R36S专用",
                    "PortMaster-Info", "ports.json")
LIST = os.path.join(ROOT, "04-游戏资源库", "公版与开源游戏", "portmaster_r36s_拿来即玩.txt")
DEST = os.path.join(ROOT, "04-游戏资源库", "公版与开源游戏", "ports全量合法池")
MANIFEST = os.path.join(DEST, "_manifest.tsv")

# 单个包超过这个体积就先跳过(1GB 内存机器的重包, 放最后人工决定)
MAX_MB = 400


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def names_from_list():
    out = []
    with open(LIST, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            out.append(line.split("\t")[0])
    return out


def fetch(url, tmp, tries=4):
    last = None
    for attempt in range(tries):
        pos = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        req = urllib.request.Request(url, headers={"Range": "bytes=%d-" % pos} if pos else {})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp, \
                    open(tmp, "ab" if pos else "wb") as fh:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
            return True
        except Exception as exc:                      # 断流/超时都重来
            last = exc
            time.sleep(3 + 5 * attempt)
    print("    最终失败: %s" % last)
    return False


def main():
    limit = None
    only = ""
    max_mb = MAX_MB
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    if "--max-mb" in sys.argv:
        max_mb = int(sys.argv[sys.argv.index("--max-mb") + 1])

    with open(INFO, encoding="utf-8") as fh:
        ports = json.load(fh)["ports"]
    os.makedirs(DEST, exist_ok=True)

    todo = [n for n in names_from_list() if n.startswith(only)]
    if limit:
        todo = todo[:limit]

    prev = {}
    if os.path.exists(MANIFEST):      # 增量跑(--only/--limit)时不能把之前的记录冲掉
        with open(MANIFEST, encoding="utf-8") as fh:
            for line in fh.readlines()[1:]:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 6:
                    prev[p[0]] = p
    order = [n + ".zip" for n in names_from_list()]

    def record(row):
        prev[row[0]] = row
        with open(MANIFEST, "w", encoding="utf-8", newline="") as fh:
            fh.write("package\tstatus\tbytes\tmd5_want\tmd5_got\turl\n")
            for pkg in order + [k for k in prev if k not in order]:
                if pkg in prev:
                    fh.write("\t".join(str(x) for x in prev[pkg]) + "\n")

    ok = have = fail = skip = 0
    total_bytes = 0
    for i, name in enumerate(todo, 1):
        pkg = name + ".zip"
        rec = ports.get(pkg)
        if not rec:
            print("[%d/%d] ? 上游无此端口: %s" % (i, len(todo), pkg))
            record((pkg, "no_record", "", "", "", ""))
            fail += 1
            continue
        src = rec["source"]
        url, want = src["url"], (src.get("md5") or "").lower()
        size = src.get("size") or 0
        if not want:
            print("[%d/%d] ! 无官方 MD5, 不下: %s" % (i, len(todo), pkg))
            record((pkg, "no_md5", size, "", "", url))
            skip += 1
            continue
        if size / 1e6 > max_mb:
            print("[%d/%d] > 超 %dMB 跳过: %s (%.1fMB)" % (i, len(todo), max_mb, pkg, size / 1e6))
            record((pkg, "too_big", size, want, "", url))
            skip += 1
            continue

        out = os.path.join(DEST, pkg)
        if os.path.exists(out) and md5(out) == want:
            print("[%d/%d] = 已有: %s" % (i, len(todo), pkg))
            record((pkg, "already", size, want, want, url))
            have += 1
            total_bytes += size
            continue

        tmp = out + ".part"
        print("[%d/%d] 下载 %s (%.1f MB)" % (i, len(todo), pkg, size / 1e6))
        if not fetch(url, tmp):
            record((pkg, "dl_fail", size, want, "", url))
            fail += 1
            continue
        got = md5(tmp)
        if got != want:
            print("    x MD5 不符 -> 删除 期望=%s 实得=%s" % (want, got))
            os.remove(tmp)
            record((pkg, "md5_mismatch", size, want, got, url))
            fail += 1
            continue
        os.replace(tmp, out)
        real = os.path.getsize(out)
        print("    + ok %.1f MB" % (real / 1e6))
        record((pkg, "downloaded", real, want, got, url))
        ok += 1
        total_bytes += real

    print("\n合计: 新下载 %d, 已存在 %d, 跳过 %d, 失败 %d" % (ok, have, skip, fail))
    print("本地体积: %.2f GB" % (total_bytes / 1e9))
    print("台账: %s" % MANIFEST)


if __name__ == "__main__":
    main()
