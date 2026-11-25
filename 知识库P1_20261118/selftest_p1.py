# -*- coding: utf-8 -*-
"""P1 路由/意图/可答性自检：正例 + 恒量反证格。

反证格原则（用户口径）：判据要配"不该亮的必须不亮"。
每条 PASS/FAIL 逐条打印，末尾逐格计数，不做倒推。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "_工具脚本"))

from p1_router import route, classify_intent
from p1_answerability import annotate
from taspipe.kb import tokens

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"{'OK ' if cond else 'FAIL'} {name}" + (f" | {detail}" if detail else ""))


# ── 路由正例 ──────────────────────────────────────────────
R = [
    ("热血足球世界杯怎么触发", "retro_soccer", True),          # 反证：不许被"世界杯"带去电竞
    ("燕返是谁的必杀", "retro_soccer", True),
    ("草薙京的出招表在哪", "kof98", True),
    ("98UM 和 ECK 什么区别", "kof98", True),
    ("街机改版整合包里有多少游戏", "arcade_hacks", True),
    ("素材生产规范对掉帧怎么规定", "project_docs", True),
    ("kb.py 的候选过滤在哪", "tooling", True),
]
for q, dom, avail in R:
    r = route(q)
    check(f"route+ {q[:18]}", r["domain"] == dom and r["corpus_available"] == avail,
          f"got={r['domain']} avail={r['corpus_available']}")

# ── 路由反证：域外必须识别且声明零语料 ──────────────────────
R_OUT = [
    ("英雄联盟全球总决赛冠军是哪支战队", "esports_lol"),
    ("DOTA2 TI14 奖金池多少", "esports_dota"),
    ("原神纳西妲圣遗物怎么配", "modern_games"),
]
for q, dom in R_OUT:
    r = route(q)
    check(f"route- {q[:18]}", r["domain"] == dom and r["corpus_available"] is False,
          f"got={r['domain']} avail={r['corpus_available']}")

# 反证：无域词的问题必须 unrouted（查全部），不许硬塞某个域
r = route("今天天气怎么样")
check("route-unrouted 天气", r["domain"] == "unrouted" and r["corpus_available"] is True)
# 反证：显式强词优先于弱词（"拳皇98里射门"不许因为"射门"落到足球）
r = route("拳皇98里的射门彩蛋")
check("route-strong优先 拳皇98射门", r["domain"] == "kof98", f"got={r['domain']}")

# ── 意图分类（pilot 真题） ─────────────────────────────────
I = [
    ("这张 ECK 卡带的 ROM SHA1 指纹是多少", "value_lookup"),   # Q09：不许落到 count
    ("热血足球联盟一共有多少种必杀射门", "count"),             # Q01
    ("说明书里每队上场几名球员", "count"),                     # Q06
    ("联赛模式一共要打多少场比赛", "count"),                   # Q07
    ("燕返原生只有哪个角色会使", "identity"),                  # Q02
    ("GK・キャラ是什么位置", "identity"),                      # Q08
    ("能不能关掉队友改成 1v1", "yesno"),                       # Q10
    ("一直输球会不会触发隐藏结局", "yesno"),                   # Q17（yesno 先于 existence）
    ("我想控制队长以外的队员，该怎么换人", "howto"),           # Q05
    ("有没有转会市场可以买卖队员", "existence"),               # Q15
]
for q, want in I:
    got = classify_intent(q)
    check(f"intent {q[:16]}", got == want, f"got={got}")

# ── 可答性正例：金标块必须可答 ──────────────────────────────
A_OK = [
    ("热血足球联盟一共有多少种必杀射门",
     "## 概述\n《热血足球联盟》共 23 种必杀射门（12 角色 + 11 对手），一角色一必杀。"),
    ("说明书里每队上场几名球员",
     "＜ルール＞ ６人制。フィールドプレイヤー５＋ＧＫ１。"),
    ("联赛模式一共要打多少场比赛",
     "＜リーグ戦＞ 全３６試合。勝ち点で順位を競う。"),
    ("燕返原生只有哪个角色会使",
     "つばめがえし（燕返）：仅 Yoritsune（小辫子）原生持有。"),
    ("这张 ECK 卡带的 ROM SHA1 指纹是多少",
     "sha1 c5947d19c6a2f4a5b6c7d8e9f0a1b2c3d4e5f6a7 ／41,735,830B"),
    ("能不能关掉队友改成 1v1",
     "ECK 固定 3v3 队战是 ROM 侧限制，四条输入路径实测全否，关不掉。"),
    ("GK・キャラ是什么位置",
     "ＧＫ・キャラはゴールキーパー（门将）のこと。"),
]
for q, txt in A_OK:
    a = annotate(q, txt, tokens)
    check(f"ans+ {q[:16]}", a["answerable"],
          f"intent={a['intent']} f={a['focus_ok']} p={a['pattern_ok']} i={a['intent_ok']}")

# ── 可答性反证：pilot 假阳性原型必须被拦 ────────────────────
A_BAD = [
    # Q09 原型：视频指纹规则命中"指纹/sha1"，但没有 40 位 hex
    ("这张 ECK 卡带的 ROM SHA1 指纹是多少",
     "视频指纹去重：对切片计算 sha1 指纹，按 切片×平台×账号 判重投。"),
    # Q02 原型：秘技表有"燕返/小辫子"词，但没回答"原生只有谁"
    ("燕返原生只有哪个角色会使",
     "暂停中按特定键可发动隐藏秘技，燕返、小辫子相关词条见附表。"),
    # Q02 变体反证："仅会燕返者"不含原生归属，不算回答
    ("燕返原生只有哪个角色会使",
     "困难难度：仅会燕返者 100% 发动。秘技后全员获得全部技能（燕返/爆裂等）。"),
    # Q15 原型：足球块有"队员/买卖"泛词命中，但没有转会/市场事实
    ("有没有转会市场可以买卖队员",
     "热血足球世界杯模式：淘汰赛制，输球即出局，队员受伤会退场。"),
    # Q10 原型：讲 3v3 玩法但没有能力断言
    ("能不能关掉队友改成 1v1",
     "游戏采用 3v3 队战玩法，队友会在场上支援。"),
    # Q06 原型：足球中文块无"人制/名"计数
    ("说明书里每队上场几名球员",
     "热血足球是经典 FC 足球游戏，支持多人对战。"),
    # 串答反证：问比赛场数，"６人制"块不许冒充答案
    ("联赛模式一共要打多少场比赛",
     "＜ルール＞ ６人制。フィールドプレイヤー５＋ＧＫ１。"),
]
for q, txt in A_BAD:
    a = annotate(q, txt, tokens)
    check(f"ans- {q[:16]}", not a["answerable"],
          f"intent={a['intent']} f={a['focus_ok']} p={a['pattern_ok']} i={a['intent_ok']}")

# ── 恒量反证：空问句/无焦点词不许崩也不许全绿 ────────────────
a = annotate("", "任意文本", tokens)
check("empty-q topic兜底", a["intent"] == "topic")

n_ok = sum(1 for _, ok in results if ok)
print(f"\nSELFTEST {n_ok}/{len(results)}")
sys.exit(0 if n_ok == len(results) else 1)