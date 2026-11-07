#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 PortMaster 那 77 个 needs_free 端口里"作者官网直链就能拿到"的免费素材抓到本地。

为什么只做这一部分：itch.io 的免登录下载链路实测走不通(见 免费素材/README.md),
Steam / Google Drive 需要账号,所以那些只能留成人工清单。本脚本只管**能直取、能复算哈希**的。

跑法:  py -3 _工具脚本/free_assets_dl.py            # 抓缺的
       py -3 _工具脚本/free_assets_dl.py --check    # 只校验本地已存在的
账本:  04-游戏资源库/公版与开源游戏/免费素材/免费素材台账.tsv
"""
import argparse
import datetime
import hashlib
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "04-游戏资源库", "公版与开源游戏", "免费素材")
LEDGER = os.path.join(OUT, "免费素材台账.tsv")
AUDIT = os.path.join(ROOT, "04-游戏资源库", "公版与开源游戏", "portmaster_自备数据审计.tsv")
COLS = ["port", "file", "bytes", "sha256", "url", "fetched_utc", "install_hint"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# port -> 直链(全部 2026-10-11 用 curl 实测 200/206,Content-Type 是 zip)
DIRECT = {
    "lastscenario": "http://www.scfworks.com/files/Last%20Scenario%20v122.zip",
    "thecurseofissyos": "https://locomalito.com/files/the-curse-of-issyos.zip",
    "evilegg": "https://ivysly.com/static/games/EvilEgg/Evil%20Egg_windows_nodrm.zip",
    "canabalt-hf": "https://github.com/ninjamuffin99/canabalt-assets/archive/refs/heads/main.zip",
    "retsend": "https://github.com/mxmgorin/retsend/archive/refs/heads/main.zip",
}


def clean(s):
    return re.sub(r"[\t\r\n\"]+", " ", s or "").strip()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_ledger():
    if not os.path.exists(LEDGER):
        return {}
    rows = {}
    with open(LEDGER, encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) >= 5:
                rows[f[0]] = dict(zip(COLS, f))
    return rows


def save_ledger(rows):
    with open(LEDGER, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(COLS) + "\n")
        for port in sorted(rows):
            r = rows[port]
            fh.write("\t".join(clean(r.get(c, "")) for c in COLS) + "\n")


def hints():
    """从审计表里取这些端口各自的'素材放哪'原文。"""
    out = {}
    if not os.path.exists(AUDIT):
        return out
    import csv
    with open(AUDIT, encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            out[r["name"]] = r["inst"]
    return out


def fetch(port, url):
    d = os.path.join(OUT, port)
    os.makedirs(d, exist_ok=True)
    name = urllib.parse.unquote(url.split("/")[-1])
    dest = os.path.join(d, name)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            if total:
                sys.stdout.write("\r  %-18s %6.1f/%6.1f MB" % (port, got / 1e6, total / 1e6))
                sys.stdout.flush()
    print()
    os.replace(tmp, dest)
    return dest, name, got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验本地文件,不联网")
    args = ap.parse_args()

    rows = load_ledger()
    hint = hints()
    changed = 0

    for port, url in sorted(DIRECT.items()):
        known = rows.get(port)
        if known:
            dest = os.path.join(OUT, port, known["file"])
            if os.path.exists(dest):
                loc = sha256_of(dest)
                if loc == known["sha256"]:
                    print("= %-18s 已存在且哈希相符,跳过  (%s)" % (port, known["file"]))
                    continue
                print("! %-18s 本地哈希与账本不符,重抓" % port)
        if args.check:
            print("x %-18s 本地缺失: %s" % (port, known["file"] if known else "(未入账)"))
            continue
        dest, name, got = fetch(port, url)
        rows[port] = {
            "port": port, "file": name, "bytes": str(got), "sha256": sha256_of(dest),
            "url": url, "fetched_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "install_hint": clean(hint.get(port, ""))[:300],
        }
        changed += 1
        print("+ %-18s %s  %.1f MB" % (port, name, got / 1e6))

    save_ledger(rows)
    total = sum(int(r["bytes"]) for r in rows.values())
    print("\n本次新抓 %d 项;账本累计 %d 项,合计 %d B = %.1f MB(十进制) -> %s"
          % (changed, len(rows), total, total / 1e6, LEDGER))
    print("仍未自动化的端口清单见 %s/README.md" % OUT)


if __name__ == "__main__":
    main()
