# -*- coding: utf-8 -*-
"""p4 带视觉反馈的宽度优先导航（Cut 城口 → 右行）。

p3 的三种招（走/爬/右跳）在 xhi=152 全数失效。看 2x 放大图 Z_w002_walk.png 得到两条事实：
  * 卡点右侧是 4~5 层绿砖柱（§33.13 已实测=地形，同层侧贴 B 举空）；
  * 梯子不在他身上，而在他**左侧**约半个身位，所以原地 Up 必然无效。
⇒ 候选动作必须包含"先左移再爬"和"下梯"，且每步留图。本脚本做有界 BFS：
  每个节点=一份快照文件，每条边=一次原子 attempt（同帧截图+RAM），
  访问集按 (screen,xhi,yhi) 去重，只展开分数不落后最优 40 以上的节点，硬上限 140 次。
起点直接用 p3 已经装备好 Super Arm 的 sess/best.state，不再重复跑装备宏。
"""
import os
import sys

sys.path.insert(0, "F:/开源掌机教程/_工具脚本")
from taspipe import statejump as SJ

ROM = "F:/taspipe_scratch/mm_showcase/megaman1_ntsc_hd.nes"
BIZ = "F:/taspipe_scratch/mm_showcase/bizhawk"
G = "F:/taspipe_scratch/mm_showcase/ramdiff/gutsnav/"
WORK = G + "p4_bfs/"
START = G + "p3_nav/sess/best.state"
A_SCREEN, A_XHI, A_YHI, A_CURRENT = 0x460, 0x480, 0x600, 0x5F
MAX_ATT = 140
PRUNE = 40


def say(*a):
    print(*a, flush=True)


def seq(*pairs):
    return ",".join(name for name, cnt in pairs for _ in range(cnt))


MOVES = [
    ("walk", seq(("Right", 16))),
    ("climb", seq(("Up", 24))),
    ("leftclimb", seq(("Left", 8), ("Up", 28))),
    ("rightclimb", seq(("Right", 6), ("Up", 28))),
    ("jumpR", seq(("Right", 6), ("A", 10), ("Right", 12))),
    ("longjumpR", seq(("Right", 14), ("A", 10), ("Right", 14))),
    ("jumpRclimb", seq(("Right", 6), ("A", 10), ("Right", 6), ("Up", 20))),
    ("down", seq(("Down", 20))),
    ("leftwalk", seq(("Left", 12))),
]

os.makedirs(WORK, exist_ok=True)
assert os.path.isfile(START), "起点不存在：%s（先跑 p3 拿到带 Super Arm 的 best.state）" % START

frontier = [(0, START, None)]          # (score, state_path, 描述)
seen = set()
best_score = -1
n_att = 0
with SJ.StateSession(ROM, BIZ, work=WORK + "sess") as s:
    say("ping", s.ping())
    st0 = s.use_state(START, name="start")
    s.load(st0)
    s.run(4)
    say("起点 current=0x%02X screen=%s xhi=%s yhi=%s"
        % (s.read(A_CURRENT), s.read(A_SCREEN), s.read(A_XHI), s.read(A_YHI)))
    frontier = [(s.read(A_SCREEN) * 256 + s.read(A_XHI), st0, "start")]
    seen.add((s.read(A_SCREEN), s.read(A_XHI), s.read(A_YHI)))

    while frontier and n_att < MAX_ATT:
        frontier.sort(key=lambda t: -t[0])
        score, st, _ = frontier.pop(0)
        if score < best_score - PRUNE:
            continue
        for name, spec in MOVES:
            if n_att >= MAX_ATT:
                break
            n_att += 1
            rp = WORK + "sess/r.bin"
            node = WORK + "sess/n%03d.state" % n_att
            sh = WORK + "n%03d_%s.png" % (n_att, name)
            # 截图 / RAM / 存快照挂在同一个 attempt 收尾，三者与末帧同帧，不靠二次推进
            s.attempt(st, spec=spec, extra=6, shot=sh, ram=rp, save=node)
            b = open(rp, "rb").read()
            pos = (b[A_SCREEN], b[A_XHI], b[A_YHI])
            sc = pos[0] * 256 + pos[1]
            if pos in seen:
                continue
            seen.add(pos)
            if b[A_CURRENT] != 6:
                say("!! n%03d 装备掉了 current=0x%02X，丢弃该节点" % (n_att, b[A_CURRENT]))
                continue
            tag = ""
            if sc > best_score:
                tag = " << 新最优"
                best_score = sc
            frontier.append((sc, node, "%s<-?" % name))
            say("n%03d %-10s screen=%d xhi=%d yhi=%d score=%d%s  图=%s"
                % (n_att, name, pos[0], pos[1], pos[2], sc, tag, os.path.basename(sh)))
    say("结束：尝试=%d 最优 score=%d (screen=%d xhi=%d) 队列剩=%d 访问位置=%d"
        % (n_att, best_score, best_score // 256, best_score % 256, len(frontier), len(seen)))
say("DONE")
