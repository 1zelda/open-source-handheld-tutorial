# -*- coding: utf-8 -*-
"""p2 装备 Super Arm —— 先证明"调得出"，再谈导航。

上一轮 p1_walkright.py 的错（用户当面指出）：从 cut_spawn 只会 Right+跳，
**一次都没进武器菜单把 Super Arm 装备上**，按 B 是 Buster 开枪 ⇒ 举空。
本脚本不自创宏：直接从生产知识包取 super_arm 的 trigger.macro / patches
（Start 开菜单 -> Down 走格 -> Start 确认 -> B 举 -> B 投），只是把 base_state
从"没块的 Guts 出生段"换成 cut_spawn，逐帧 dump 后**人眼看图**确认三件事：
  1) 装色变了（换装只在菜单确认事件加载，直写 RAM 配色是错的）；
  2) 左上能量条变成 Super Arm 的 2 格（不再是 Buster 满条）；
  3) 0x5F current 真的等于 Super Arm 那一格。
"""
import json
import os
import shutil
import sys

sys.path.insert(0, "F:/开源掌机教程/_工具脚本")
from taspipe import statejump as SJ

ROM = "F:/taspipe_scratch/mm_showcase/megaman1_ntsc_hd.nes"
BIZ = "F:/taspipe_scratch/mm_showcase/bizhawk"
G = "F:/taspipe_scratch/mm_showcase/ramdiff/gutsnav/"
PACK = "F:/开源掌机教程/_工具脚本/taspipe/游戏包/megaman1_weapons.showcase.json"
WORK = G + "p2_arm/"
A_OWNED, A_CURRENT = 0x5D, 0x5F
A_ENERGY = 0x6B


def say(*a):
    print(*a, flush=True)


doc = json.load(open(PACK, encoding="utf-8"), strict=False)
arm = [e for e in doc["elements"] if e["element_id"] == "super_arm"][0]
MACRO = arm["trigger"]["macro"]
PATCHES = arm["trigger"]["patches"]
os.makedirs(WORK, exist_ok=True)
say("宏取自生产包 长度=%d token  patches=%s" % (len(MACRO.split(",")), PATCHES))

with SJ.StateSession(ROM, BIZ, work=WORK + "sess") as s:
    say("ping", s.ping())
    st = s.use_state(G + "cut_spawn.state", name="cut_spawn")
    s.load(st)
    s.run(30, shot="shot=s0_pre.png")
    say("装备前 owned=0x%02X current=0x%02X" % (s.read(A_OWNED), s.read(A_CURRENT)))

    n = s.dump(WORK + "pos", spec=MACRO, extra=30, state=st, patches=PATCHES)
    say("逐帧 dump 帧数=%s 宏长约%d" % (n, len(MACRO.split(","))))
    last = os.path.join(WORK + "pos", sorted(os.listdir(WORK + "pos"))[-1])
    shutil.copyfile(last, WORK + "z_last.png")
    say("末帧=%s (%d B)" % (WORK + "z_last.png", os.path.getsize(WORK + "z_last.png")))
    # 举+投之后再空跑 60 帧，看有没有"手里顶着块"的画面
    s.run(60, shot="shot=z_after60.png")

    say("装备后 owned=0x%02X current=0x%02X 能量 0x6B..0x72=%s"
        % (s.read(A_OWNED), s.read(A_CURRENT), [s.read(A_ENERGY + i) for i in range(8)]))
    p = s.save("cut_arm")
    say("已存带 Super Arm 的出生段快照 -> %s (%d B)" % (p, os.path.getsize(p)))

    # 顺带：带着新装往右走 90 帧，看那堵绿砖柱到底挡不挡路（只出图，不做结论）
    s.macro(",".join(["Right"] * 90), shot="shot=z_walk90.png")
    say("右行90帧后 xhi=%s yhi=%s screen=%s" % (s.read(0x480), s.read(0x600), s.read(0x460)))
say("DONE")
