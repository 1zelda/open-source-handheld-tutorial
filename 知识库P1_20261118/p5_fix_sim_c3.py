# -*- coding: utf-8 -*-
"""P5 候选 C3 模拟（只读）：FOCUS_STOP 并入域泛词，量误杀面。

原理：FOCUS_STOP 已停用域标题词(热血/足球/拳皇)与问句框架词(游戏/模式/玩家/队员/角色)。
X25/X26/X28 假块的唯一焦点命中是域泛词(球员/射门/eck)——这类词几乎出现在本域每个块里，
不是问句特有焦点。候选 C3 把 {球员,射门,eck,kof98,地址,内存} 并入停用表，
使焦点/锚必须命中问句特有词(治疗/雨天/金手指/得分)。在 C1+C2 基础上叠加。
核对：嫌疑块须堵；26 金标须活；26+60 逐题域内可答权威块不得清零（真回归）。
用法（系统 py -3）：python -u p5_fix_sim_c3.py > p5_fix_sim_c3_out.txt
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb as K  # noqa: E402
from taspipe import kb_route as KR  # noqa: E402
from taspipe import kb_answer as KA  # noqa: E402
import p5_fix_sim as S  # noqa: E402  复用 cand/find（C1+C2）

EXTRA_STOP = {"球员", "射门", "eck", "kof98", "地址", "内存"}


def main():
    idx = K.load_index(K.INDEX_JSON)
    chunks = idx["chunks"]
    ext = json.loads((HERE / "probe_questions_ext.json").read_text(encoding="utf-8"))
    old = json.loads((HERE / "probe_questions.json").read_text(encoding="utf-8"))
    frozen = json.loads((HERE / "p1_questions_ext.json").read_text(encoding="utf-8"))
    probes = ext["questions"] + [dict(q, kind="regression") for q in old["questions"]]
    pmap = {q["id"]: q["q"] for q in probes}
    suspect = [("X25", "必杀全清单", 137, 158), ("X26", "必杀全清单", 137, 158),
               ("X28", "素材生产规范", 18, 31), ("X30", "必杀全清单", 3, 7),
               ("X01", "必杀全清单", 194, 210), ("X24", "必杀全清单", 101, 119)]

    orig_stop = set(KR.FOCUS_STOP)
    KR.FOCUS_STOP = orig_stop | EXTRA_STOP
    # kb_answer 从 kb_route import 的是函数引用，focus_terms 内部读 KR.FOCUS_STOP 全局 => 生效
    print("=== C3 停用词扩充后焦点变化抽查 ===")
    for qid in ["X25", "X26", "X28", "X02", "Q10", "X07"]:
        q = pmap.get(qid)
        if q:
            print(f"  {qid} focus={sorted(KR.focus_terms(q, K.tokens))}")

    print("\n=== 嫌疑块（C1+C2+C3，须堵，X30 除外）===")
    for qid, pp, a, b in suspect:
        q = pmap[qid]
        for c in S.find(chunks, pp, a, b):
            ca, na, r3, hit = S.cand(q, c["text"], c.get("lang", "zh"), False)
            print(f"  {qid} L{c['line_start']}-{c['line_end']} 现={ca} 新={na} hit={hit[:5]}")

    print("\n=== 26 题金标块（须仍可答；基线=原表，候选=C3）===")
    killed = 0
    for q in frozen["questions"]:
        g = q.get("gold")
        if not g:
            continue
        cs = S.find(chunks, g["path_contains"], g["line_start"], g["line_end"])
        KR.FOCUS_STOP = orig_stop
        cur = [KA.annotate(q["q"], c["text"], K.tokens, c.get("lang", "zh"))["answerable"] for c in cs]
        KR.FOCUS_STOP = orig_stop | EXTRA_STOP
        new = [S.cand(q["q"], c["text"], c.get("lang", "zh"), False)[1] for c in cs]
        if any(cur) and not any(new):
            killed += 1
            print(f"  {q['id']} KILLED {q['q'][:26]}")
            for c, ca, na in zip(cs, cur, new):
                print(f"     L{c['line_start']} 现={ca} 新={na}")
    print(f"  金标误杀数：{killed}")

    print("\n=== 26+60 逐题域内可答权威块清零回归（基线=原表，候选=C3）===")
    reg = 0
    for q in frozen["questions"] + probes:
        f = q.get("filters", {})
        r = KR.route(q["q"])
        if f.get("game"):
            r["game_ids"] = [f["game"]]
        if f.get("revision"):
            r["revisions"] = [f["revision"]]
        scope = [c for c in chunks if KR.in_scope(c, r)]
        KR.FOCUS_STOP = orig_stop
        cur_auth = [c for c in scope if c.get("authority") == "authoritative"
                    and KA.annotate(q["q"], c["text"], K.tokens, c.get("lang", "zh"))["answerable"]]
        KR.FOCUS_STOP = orig_stop | EXTRA_STOP
        new_auth = [c for c in scope if c.get("authority") == "authoritative"
                    and S.cand(q["q"], c["text"], c.get("lang", "zh"), False)[1]]
        if cur_auth and not new_auth:
            reg += 1
            print(f"  {q['id']:5s} REGRESS {q['q'][:30]} {len(cur_auth)}→0")
    print(f"  清零回归题数：{reg}")
    KR.FOCUS_STOP = orig_stop


if __name__ == "__main__":
    main()