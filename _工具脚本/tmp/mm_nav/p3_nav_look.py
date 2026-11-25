# -*- coding: utf-8 -*-
"""p3 带 Super Arm 的可视化导航（每步一张图，人眼看完再走下一步）。

修掉 p1_walkright.py 的两个错：
  1) 从没装备 Super Arm —— 本脚本先跑生产包里的"只装备不放"宏
     （negative_control.macro：Start×8 → Down×12 → Start×8，等价 k=3 ⇒ 0x5F=6），
     装备证据用 e3.png 已确认的口径：左上多出第二根短能量条 + 装色变化。
  2) 拿 B 当跳跃 —— MM1 跳跃是 **A**，B 是射击/举块。
状态机：走 → 没进步就试爬梯(Up) → 再没进步就右跳(Right+A) → 还没进步算卡。
每轮 attempt 原子收尾（截图+存快照+RAM），所以图与数值同帧，不靠事后补拍。
"""
import json
import os
import sys

sys.path.insert(0, "F:/开源掌机教程/_工具脚本")
from taspipe import statejump as SJ

ROM = "F:/taspipe_scratch/mm_showcase/megaman1_ntsc_hd.nes"
BIZ = "F:/taspipe_scratch/mm_showcase/bizhawk"
G = "F:/taspipe_scratch/mm_showcase/ramdiff/gutsnav/"
PACK = "F:/开源掌机教程/_工具脚本/taspipe/游戏包/megaman1_weapons.showcase.json"
WORK = G + "p3_nav/"
A_SCREEN, A_XHI, A_YHI, A_OWNED, A_CURRENT = 0x460, 0x480, 0x600, 0x5D, 0x5F
MAX_ITER = 70


def say(*a):
    print(*a, flush=True)


doc = json.load(open(PACK, encoding="utf-8"), strict=False)
arm = [e for e in doc["elements"] if e["element_id"] == "super_arm"][0]
EQUIP = arm["negative_control"]["macro"]      # 只装备、不放第二下 B
PATCHES = arm["trigger"]["patches"]           # owned=0xFF，让菜单里出现全部武器
say("装备宏 token=%d  patches=%s" % (len(EQUIP.split(",")), PATCHES))
os.makedirs(WORK, exist_ok=True)


with SJ.StateSession(ROM, BIZ, work=WORK + "sess") as s:
    say("ping", s.ping())
    src = s.use_state(G + "cut_spawn.state", name="cut_spawn")
    # 第 1 步：装备。dump 走生产 patch 通道（load 时打补丁），末帧=装备完成后
    n = s.dump(WORK + "equip", spec=EQUIP, extra=20, state=src, patches=PATCHES)
    last = os.path.join(WORK + "equip", sorted(os.listdir(WORK + "equip"))[-1])
    os.replace(last, WORK + "z_equip_end.png")
    say("装备逐帧 %d 张，末帧已挪到 z_equip_end.png" % n)
    say("装备后 owned=0x%02X current=0x%02X" % (s.read(A_OWNED), s.read(A_CURRENT)))
    cur = s.save("arm0")
    s.load(cur)
    s.run(5)
    sc, x, y = s.read(A_SCREEN), s.read(A_XHI), s.read(A_YHI)
    say("装备后出生点 screen=%s xhi=%s yhi=%s" % (sc, x, y))

    best = (sc, x)
    stuck = 0
    mode = "walk"
    for i in range(MAX_ITER):
        if mode == "walk":
            spec = ",".join(["Right"] * 16)
            act = "walk"
        elif mode == "climb":
            spec = ",".join(["Up"] * 16)
            act = "climb"
        else:
            spec = ",".join((["Right"] * 5 + ["A"] * 12) * 2)
            act = "jump"
        st_path = WORK + "r.bin"
        shot = WORK + "w%03d_%s.png" % (i, act)
        s.attempt(cur, spec=spec, extra=6, shot=shot, ram=st_path)
        b = open(st_path, "rb").read()
        sc2, x2, y2 = b[A_SCREEN], b[A_XHI], b[A_YHI]
        moved = (sc2, x2) > best or (sc2 == best[0] and x2 > best[1])
        if moved:
            best = (sc2, x2)
            stuck = 0
            mode = "walk"
            cur = s.save("best")
            say("i%02d %s 进步 screen=%s xhi=%s yhi=%s -> best.state" % (i, act, sc2, x2, y2))
        elif (sc2, y2) != (sc, y) and mode == "climb":
            # 高度变了但没右移：还在梯子上，继续爬
            cur = s.save("climb")
            say("i%02d %s 升高度 yhi %s->%s（继续爬）" % (i, act, y, y2))
        else:
            stuck += 1
            mode = "climb" if mode == "walk" else ("jump" if mode == "climb" else "walk")
            say("i%02d %s 无效 screen=%s xhi=%s yhi=%s 换招->%s 连续卡=%d"
                % (i, act, sc2, x2, y2, mode, stuck))
        sc, x, y = sc2, x2, y2
        if stuck >= 9:
            say("i%02d 三种招轮完 9 次仍不动，停手等看图" % i)
            break
    say("终点 best=%s 迭代=%d 图目录=%s" % (str(best), i + 1, WORK))
say("DONE")
