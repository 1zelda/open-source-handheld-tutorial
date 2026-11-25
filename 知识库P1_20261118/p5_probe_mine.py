# -*- coding: utf-8 -*-
"""P5 扩探针集挖矿（只读）：候选题走生产 kb.query（hybrid），
打印 top8 各位的权威/可答/定位，供人工挑「真救回格」（可答权威件在第4-5位）
与「陷阱格」（库里没有答案但话题词会撞块）。零 LLM。
用法：venv python -u p5_probe_mine.py
"""
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb as K  # noqa: E402

CANDS = [
    ("M01", "热血足球联盟 阵型一共有几种？", {"game": "nekketsu_soccer2"}),
    ("M02", "热血足球 1P 得分的内存地址是多少？", {"game": "nekketsu_soccer2"}),
    ("M03", "热血足球 打雷会不会把门将击倒？", {"game": "nekketsu_soccer2"}),
    ("M04", "热血足球 韩国队赢球后是什么庆祝动作？", {"game": "nekketsu_soccer2"}),
    ("M05", "热血足球 哪个队员体力最高？", {"game": "nekketsu_soccer2"}),
    ("M06", "热血足球 全败结局画面显示的密码是什么？", {"game": "nekketsu_soccer2"}),
    ("M07", "热血足球 龙卷拳谁能用？", {"game": "nekketsu_soccer2"}),
    ("M08", "热血足球 美纱子的电话有什么用？", {"game": "nekketsu_soccer2"}),
    ("M09", "热血足球 德国队为什么必杀概率低？", {"game": "nekketsu_soccer2"}),
    ("M10", "热血足球 三倍加速怎么发动？", {"game": "nekketsu_soccer2"}),
    ("M11", "热血足球 选手一闪一闪是故障吗？", {"game": "nekketsu_soccer2"}),
    ("M12", "热血足球 元永在队里打什么位置？", {"game": "nekketsu_soccer2"}),
    ("M13", "热血足球 每支球队最多能挑战几次？", {"game": "nekketsu_soccer2"}),
    ("M14", "热血足球 意大利门将的弱点在哪里？", {"game": "nekketsu_soccer2"}),
    ("M15", "热血足球 倒挂金钩怎么使出来？", {"game": "nekketsu_soccer2"}),
    ("M16", "热血足球联盟 能不能联网对战？", {"game": "nekketsu_soccer2"}),
    ("M17", "热血足球 怎么存档进度？", {"game": "nekketsu_soccer2"}),
    ("M18", "热血足球 球员受伤了怎么治疗？", {"game": "nekketsu_soccer2"}),
    ("M19", "热血足球联盟 怎么给球员升级加点？", {"game": "nekketsu_soccer2"}),
    ("M20", "热血足球 有没有办法跳过中场休息？", {"game": "nekketsu_soccer2"}),
    ("M21", "热血足球 怎么解锁隐藏球队？", {"game": "nekketsu_soccer2"}),
    ("M22", "热血足球 雨天场地对射门有什么影响？", {"game": "nekketsu_soccer2"}),
    ("M23", "热血足球联盟 支持几个手柄同时玩？", {"game": "nekketsu_soccer2"}),
    ("M24", "热血足球 应援曲一共有几首？", {"game": "nekketsu_soccer2"}),
    ("M25", "热血足球 走力 A 型是什么意思？", {"game": "nekketsu_soccer2"}),
    ("M26", "拳皇98 ECK 金手指怎么用？", {"revision": "kof98eck"}),
    ("M27", "热血足球 海月是什么射门？", {"game": "nekketsu_soccer2"}),
    ("M28", "热血足球 香蕉环射门有什么特点？", {"game": "nekketsu_soccer2"}),
    ("M29", "热血足球 秘技效果能持续多久？", {"game": "nekketsu_soccer2"}),
    ("M30", "热血足球 合体技有哪些发动方法？", {"game": "nekketsu_soccer2"}),
]


def main():
    for mid, q, f in CANDS:
        r = K.query(q, top_window=5, **f)
        print(f"== {mid} {q}  status={r['status']}")
        for i, h in enumerate(r["hits"][:8], 1):
            a = h["answerability"]
            print(f"  {i} {h['authority'][:12]:12s} ans={str(a['answerable']):5s} "
                  f"{h['locator'].split('/')[-1][:52]}")


if __name__ == "__main__":
    main()