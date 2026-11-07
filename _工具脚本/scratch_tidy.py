#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scratch_tidy.py —— _scratch 探测残渣归档(2026-10-21 新增)

_scratch 是探测脚本/日志的暂存区,几轮下来 200+ 个文件,找东西要翻半天。
这个工具把**修改时间超过 N 天**的文件按日期搬进 _scratch/_归档/YYYY-MM-DD/,
当天的和最近 N 天的留在原地。只搬不删,随时可以搬回来。

用法:
  py -3 _工具脚本/scratch_tidy.py            # 归档 7 天前的(默认)
  py -3 _工具脚本/scratch_tidy.py --days 3   # 归档 3 天前的
  py -3 _工具脚本/scratch_tidy.py --dry-run  # 只看看会搬什么
幂等:已在归档目录里的不动;跑多少次结果一样。
"""
import argparse
import datetime as dt
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(ROOT, "_scratch")
ARCHIVE = os.path.join(SCRATCH, "_归档")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cutoff = dt.datetime.now() - dt.timedelta(days=args.days)

    moved, kept = [], 0
    for fn in sorted(os.listdir(SCRATCH)):
        p = os.path.join(SCRATCH, fn)
        if not os.path.isfile(p):
            continue
        mtime = dt.datetime.fromtimestamp(os.path.getmtime(p))
        if mtime >= cutoff:
            kept += 1
            continue
        day = mtime.strftime("%Y-%m-%d")
        dest_dir = os.path.join(ARCHIVE, day)
        dest = os.path.join(dest_dir, fn)
        if os.path.exists(dest):
            continue
        moved.append((fn, day))
        if not args.dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(p, dest)

    print("_scratch 归档:%s" % ("(dry-run)" if args.dry_run else "完成"))
    print("  搬走 %d 个(%d 天前的),留下 %d 个(最近 %d 天)" % (len(moved), args.days, kept, args.days))
    for fn, day in moved[:40]:
        print("   -> _归档/%s/%s" % (day, fn))
    if len(moved) > 40:
        print("   ...还有 %d 个" % (len(moved) - 40))


if __name__ == "__main__":
    main()
