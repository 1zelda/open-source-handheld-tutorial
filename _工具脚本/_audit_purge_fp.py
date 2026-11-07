"""审计红线误杀：列出索引里挂着「已删除」的文件，并挑出只因为 dump 没有词边界才被删的那些。

判据本体不在这里复制 —— 直接 import 生产模块 switch2_emu_fetch，用它的 suspect_reason
现判据给每个文件定性，本文件只额外算「把 dump 改成词边界之后还剩不剩得上红线」。

跑法：py -3 -X utf8 _工具脚本/_audit_purge_fp.py
只读，不还原。它点名的误杀就照着名单自己修：
    git -C <仓> checkout HEAD -- <路径>
（HEAD 里还在，所以这一条同时把工作树和索引抹平；switch2_emu_fetch 没有 restore 子命令。）
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import switch2_emu_fetch as M

GIT = M.GIT
# 两档都查，路径写死：M.SRC 由 MIRROR_AREA 决定，11-04 我在别的命令上栽过一次"没设环境变量
# 就动了默认档"，所以这种只读的跨档盘点不跟默认档走。
AREAS = [r"F:\开源掌机教程\06-资讯监控\成品移植游戏库\源码",
         r"F:\开源掌机教程\06-资讯监控\Switch2模拟器\源码"]

# 生产判据里那段 dump（无边界，objdump 这类工具名也会命中）换成带边界的版本
DUMP_BOUNDARY = re.compile("(?<![a-z0-9])dump(?![a-z0-9])", re.I)


def only_unbounded_dump(rel, size):
    """现判据说是红线，但把 dump 要求成独立词之后就不再是红线 —— 即误杀。"""
    reason = M.suspect_reason(rel, size)
    if not reason:
        return ""
    low = rel.lower()
    if "dump" not in low:
        return ""
    # 把 firmware / .nro 这两条支路另算：它们命中就与 dump 无关
    if re.search("(firmware|" + chr(92) + ".nro" + chr(92) + "b)", low):
        return ""
    return reason if not DUMP_BOUNDARY.search(low) else ""


def main():
    rows = []
    for src in AREAS:
        if not os.path.isdir(src):
            print("档不在盘上，跳过：%s" % src, flush=True)
            continue
        dirs = [d for d in sorted(os.listdir(src)) if os.path.isdir(os.path.join(src, d))]
        print("== %s（%d 仓）" % (os.path.basename(os.path.dirname(src)), len(dirs)), flush=True)
        for i, d in enumerate(dirs, 1):
            p = os.path.join(src, d)
            r = subprocess.run([GIT, "-C", p, "diff", "--cached", "--name-only",
                                "--diff-filter=D"], capture_output=True)
            for rel in r.stdout.decode("utf-8", "replace").splitlines():
                rel = rel.strip()
                if not rel:
                    continue
                s = subprocess.run([GIT, "-C", p, "cat-file", "-s", "HEAD:" + rel],
                                   capture_output=True)
                size = int(s.stdout.decode().strip()) if s.returncode == 0 else 0
                rows.append((d, rel, size, M.suspect_reason(rel, size),
                             only_unbounded_dump(rel, size)))
            if i % 20 == 0 or i == len(dirs):
                print("  扫 %d/%d 仓，累计挂着删除标记的文件 %d 个"
                      % (i, len(dirs), len(rows)), flush=True)

    mis = [x for x in rows if x[4]]
    keep = [x for x in rows if x[3] and not x[4]]
    other = [x for x in rows if not x[3]]
    print("")
    print("索引里挂着删除标记的文件：%d 个，涉及 %d 个仓" % (len(rows), len(set(x[0] for x in rows))))
    print("改成词边界后不再是红线（误杀，该还原）：%d" % len(mis))
    for x in mis:
        print("  误杀 %s :: %s（%.1f MB，旧判据=%s）" % (x[0], x[1], x[2] / 1048576.0, x[3]))
    print("仍是红线（删得对，不动）：%d" % len(keep))
    for x in keep[:20]:
        print("  红线 %s :: %s（%.1f MB，%s）" % (x[0], x[1], x[2] / 1048576.0, x[3]))
    if len(keep) > 20:
        print("  ...另有 %d 条，跑 restore 前的名单在盘上" % (len(keep) - 20))
    print("现判据已经不算红线、却仍挂着删除标记（别的路径动的手，比如上游改名）：%d" % len(other))
    for x in other[:10]:
        print("  存疑 %s :: %s（%.1f MB）" % (x[0], x[1], x[2] / 1048576.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
