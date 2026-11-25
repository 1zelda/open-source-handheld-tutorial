# -*- coding: utf-8 -*-
"""p1 小样：从 cut_spawn.state（真·fresh boot 选关得到的 Cut 城出生段）用"右走+顶墙就跳"的
最小策略能推进多远，量的是 0x460(screen)/0x480(xhi)/0x600(yhi) 三个位置字节（沿用 walkmap.py
已用过的读法，不是我新猜的地址）。

为什么要先跑这一条：§33.13 说"从 cut_spawn 到竖井 Break 块≈右 3 屏+爬竖井，盲宏右移会顶墙"，
但没量过"顶墙就跳"这个最小策略实际能推进几屏。这个数决定后面是 30 分钟还是 3 小时，
也决定要不要上 guided checkpoint 搜索（多策略+回退）。

产物（都在 ASCII 工作目录，Lua io 不认中文路径）：
  F:/taspipe_scratch/mm_showcase/ramdiff/gutsnav/p1_walk/log.txt   逐迭代位置流水
  F:/taspipe_scratch/mm_showcase/ramdiff/gutsnav/p1_walk/best_*.state 每次破纪录那一刻的快照
串行规矩：一次只开一个 EmuHawk；起跑前先 tasklist 点名。
"""
import os
import sys
import time

sys.path.insert(0, "F:/开源掌机教程/_工具脚本")
from taspipe import statejump as SJ   # noqa: E402

R = "F:/taspipe_scratch/mm_showcase/ramdiff/gutsnav/"
ROM = "F:/taspipe_scratch/mm_showcase/megaman1_ntsc_hd.nes"
BIZ = "F:/taspipe_scratch/mm_showcase/bizhawk"
STATE = R + "cut_spawn.state"
WORK = R + "p1_walk/"
A_SCREEN, A_XHI, A_YHI = 0x460, 0x480, 0x600
MAX_ITER = 200
WALK = 12


def main():
    os.makedirs(WORK, exist_ok=True)
    log = open(os.path.join(WORK, "log.txt"), "w", encoding="utf-8")

    def say(*a):
        line = " ".join(str(x) for x in a)
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    say("p1 小样开始", time.strftime("%H:%M:%S"))
    with SJ.StateSession(ROM, BIZ, work=WORK + "sess") as s:
        s.ping()
        s.load(STATE)
        s.run(30)
        say("起点 screen=%s xhi=%s yhi=%s" % (s.read(A_SCREEN), s.read(A_XHI), s.read(A_YHI)))
        best_key = (s.read(A_SCREEN), s.read(A_XHI))
        stuck = 0
        died = 0
        start_screen = s.read(A_SCREEN)
        for i in range(MAX_ITER):
            scr0, x0, y0 = s.read(A_SCREEN), s.read(A_XHI), s.read(A_YHI)
            s.macro(",".join(["Right"] * WALK))
            x1 = s.read(A_XHI)
            jumped = False
            if x1 == x0:
                jumped = True
                s.macro(",".join(["Right"] * 4 + ["B"] * 10 + ["Right"] * 14))
                x1 = s.read(A_XHI)
            scr1, y1 = s.read(A_SCREEN), s.read(A_YHI)
            if scr1 == start_screen and x1 <= x0 - 8 and i > 6:
                died += 1
                say("i%03d 疑似死亡/回出生点 screen=%s xhi=%s (累计%d次)" % (i, scr1, x1, died))
                stuck = 0
                best_key = (scr1, x1)
                continue
            key = (scr1, x1)
            rec = key > best_key
            if key > best_key:
                best_key = key
                stuck = 0
            elif x1 == x0 and (scr1, y1) == (scr0, y0):
                stuck += 1
            else:
                stuck = 0
            if rec:
                sp = s.save("best_%03d" % i)
                say("i%03d 破纪录 screen=%s xhi=%s yhi=%s%s -> %s" %
                    (i, scr1, x1, y1, "(跳)" if jumped else "", os.path.basename(sp)))
            if i % 20 == 0 or stuck == 0 and rec:
                say("i%03d screen=%s xhi=%s yhi=%s %s stuck=%d best=%s" %
                    (i, scr1, x1, y1, "跳" if jumped else "走", stuck, best_key))
            if stuck >= 12:
                say("i%03d 连续 %d 轮纹丝不动，收手（顶墙+跳也过不去）" % (i, stuck))
                break
        fp = s.save("best")
        s.shot("end")
        say("终点快照", fp, os.path.getsize(fp), "B")
        say("结论：best=%s 迭代=%d 疑似死亡=%d 次" % (str(best_key), i + 1, died))
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
