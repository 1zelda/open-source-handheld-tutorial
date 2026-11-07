#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backup.py —— 知识库备份(2026-10-21 新增)

为什么要有:全库没有 git、没有副本。台账 9000+ 条、判定表 150+ 行、教程 253 篇
都是这些天一点点攒出来的,误删/盘坏就得从零再来。备份必须成为日常动作。

备份范围(**只备份攒出来的东西,不备份能重新获得的**):
  收:06-资讯监控(台账/判定/登记/日报/周报/下架抢救,全部 TSV+JSON+MD)
      01-教程库、03-BIOS库(连文件)、05-硬件与机型资料、交接稿/README/指北
  不收:02-模拟器库(9 万文件的 clone 镜像,gh clone 能重新获得)
        04-游戏资源库 的 payload(release 资产,上游还在;要一起备份加 --with-payload)

用法:
  py -3 _工具脚本/backup.py --dest D:\\库备份            # 必须显式给目标(不猜)
  py -3 _工具脚本/backup.py --dest D:\\库备份 --with-payload   # 连 04 的 payload 一起(约 1.3GB)
  py -3 _工具脚本/backup.py --dest D:\\库备份 --dry-run

产物:dest 下按时间戳的 zip(知识库部分)+ 一行摘要。同名目标重复跑会覆盖旧 zip
(以时间戳区分),目标盘不在会直接报错,不静默失败。
"""
import argparse
import datetime as dt
import os
import sys
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# (源路径, 归档内前缀);None 表示不存在就跳过并说明
INCLUDE = [
    ("06-资讯监控", "06-资讯监控"),
    ("01-教程库", "01-教程库"),
    ("03-BIOS库", "03-BIOS库"),
    ("05-硬件与机型资料", "05-硬件与机型资料"),
    ("交接稿-项目目标与现状.md", "交接稿-项目目标与现状.md"),
    ("README.md", "README.md"),
    ("Switch-PSVita-掌机_破解与移植发布源指北.md", "Switch-PSVita-掌机_破解与移植发布源指北.md"),
]
EXCLUDE_DIRS = {"__pycache__"}


def zip_dir(zf, src, prefix):
    n = 0
    for dirpath, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in files:
            p = os.path.join(dirpath, fn)
            rel = os.path.join(prefix, os.path.relpath(p, src)).replace("\\", "/")
            zf.write(p, rel)
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True, help="备份目标目录(不会猜,不给就报错)")
    ap.add_argument("--with-payload", action="store_true", help="连 04-游戏资源库 的 payload 一起备份(约 1.3GB)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dest = args.dest
    if not os.path.isdir(dest):
        print("X 目标目录不存在:%s(先建好或换个路径)" % dest)
        return 2
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(dest, "开源掌机教程_知识库_%s.zip" % stamp)

    items = list(INCLUDE)
    if args.with_payload:
        items.append(("04-游戏资源库", "04-游戏资源库"))

    total = 0
    missing = []
    for src, _ in items:
        if not os.path.exists(os.path.join(ROOT, src)):
            missing.append(src)
    if missing:
        print("! 跳过不存在的:%s" % ", ".join(missing))
        items = [x for x in items if os.path.exists(os.path.join(ROOT, x[0]))]

    if args.dry_run:
        for src, prefix in items:
            print("  将打包:%s" % src)
        print("  -> %s(dry-run,未写盘)" % out)
        return 0

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src, prefix in items:
            p = os.path.join(ROOT, src)
            if os.path.isfile(p):
                zf.write(p, prefix)
                total += 1
            else:
                total += zip_dir(zf, p, prefix)
    size = os.path.getsize(out)
    print("备份完成:%s" % out)
    print("  %d 个文件,%.1f MB" % (total, size / 1048576))
    print("  建议:每周至少一次;换了机器/盘之后先从这里恢复 06 与 01,再 gh clone 补 02")


if __name__ == "__main__":
    sys.exit(main())
