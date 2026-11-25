# -*- coding: utf-8 -*-
"""P7 只读模拟：YESNO_RE 补「隐性肯定」答案形态的误杀面。零模型零写。

根因（p7_diag 已证）：W03 真答案「守门员专用必杀技为龙卷风拳」不含 YESNO_RE 词
（不能/可以/支持…），被 yesno 意图校验器判 intent_ok=False ⇒ 不可答。
窄 FOCUS_PATTERN 治不了（intent_ok 是硬关）。须给 YESNO_RE 补隐性肯定形态。

跑前规则（先落盘）：
  R1 假阳一票否决：补词后任何 yesno 问句新增「答非所问」可答块 => 否决该候选。
  R2 回归零容忍：现有可答块不得变不可答（补词是放宽，理论上只增不减，须验证）。
  R3 真救回：W03 真答案（对照必杀技节）须转可答，且当前索引 W03 状态不恶化。
  R4 修不了标诚实缺口：所有候选都引假阳 => 保留 W03 缺口，不硬调参。

候选（补入 YESNO_RE 的隐性肯定形态）：
  E1 专用        E2 专用必杀技|专用技   E3 持有   E4 才能   E5 专用.*为|为.*专用
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = r"F:\开源掌机教程"
sys.path.insert(0, os.path.join(ROOT, "_工具脚本"))
from taspipe import kb as K
from taspipe import kb_answer as KA
from taspipe import kb_route as KR

BASE = os.path.join(ROOT, "知识库P1_20261118")
IDX = os.path.join(ROOT, r"_工具脚本\taspipe\游戏包\知识库\index.json")
DUIZHAO = os.path.join(
    ROOT, r"_工具脚本\taspipe\游戏包\来源库\取证\setsumei_热血足球说明书_编者中文对照_20261119.md")
TEXT = {c["chunk_id"]: c for c in json.load(open(IDX, encoding="utf-8"))["chunks"]}

EXT = {
    "E1_专用": r"专用",
    "E2_专用必杀技": r"专用必杀技|专用技",
    "E3_持有": r"持有",
    "E4_才能": r"才能",
    "E5_专用为": r"专用.{0,8}为|为.{0,8}专用",
}
ORIG_YESNO = KA.YESNO_RE


def annotate_yesno(q, text, lang, ext_rx):
    KA.YESNO_RE = re.compile(ORIG_YESNO.pattern + "|" + ext_rx)
    try:
        return K.annotate(q, text, K.tokens, lang=lang)
    finally:
        KA.YESNO_RE = ORIG_YESNO


def main():
    out = []
    P = out.append
    # 收集 yesno 问句（86 题）+ 两臂探针命中块
    qs = {}
    probes = {}
    for arm, fn in (("bm25", "p6_probe_bm25"), ("hybrid", "p6_probe_hybrid")):
        pr = json.load(open(os.path.join(BASE, fn), encoding="utf-8"))
        probes[arm] = pr
        for it in pr:
            qs[it["id"]] = it["q"]
    prod = json.load(open(os.path.join(BASE, "p6_prod_bm25.json"), encoding="utf-8"))
    for it in prod["results"]:
        qs[it["id"]] = it["q"]
    yesno_qs = {qid: q for qid, q in qs.items() if KR.classify_intent(q) == "yesno"}
    P("=" * 70)
    P(f"P7 YESNO_RE 补词模拟：yesno 问句 {len(yesno_qs)} 题")
    P("=" * 70)
    for qid, q in yesno_qs.items():
        P(f"  {qid}: {q}")

    # W03 真答案（对照必杀技节）
    dz = open(DUIZHAO, encoding="utf-8").read()
    paras = [p.strip() for p in dz.split("\n\n") if p.strip()]
    skill = next(p for p in paras if "守门员专用必杀技" in p)
    w03q = qs["W03"]

    summary = {}
    for name, ext in EXT.items():
        P("")
        P("=" * 70)
        P(f"候选 {name}: YESNO_RE += {ext}")
        P("=" * 70)
        # W03 真答案是否转可答
        a_skill = annotate_yesno(w03q, skill, "zh", ext)
        P(f"  W03 真答案(对照必杀技节): answerable={a_skill['answerable']} "
          f"intent_ok={a_skill['intent_ok']} focus_hit={a_skill['focus_hit']}")
        # 两臂探针 yesno 问句命中块重判：新增可答 / 变不可答
        new_true = []
        new_false = []
        for arm, pr in probes.items():
            for it in pr:
                qid, q = it["id"], it["q"]
                if qid not in yesno_qs:
                    continue
                for w in ("w3", "w5"):
                    for h in it[w].get("hits", []):
                        c = TEXT.get(h["chunk_id"])
                        if not c:
                            continue
                        a = annotate_yesno(q, c["text"], c.get("lang", "zh"), ext)
                        was = bool(h.get("answerable"))
                        now = a["answerable"]
                        if now and not was:
                            new_true.append((arm, qid, w, h["rank"], h["chunk_id"],
                                             h["locator"], c["text"]))
                        elif was and not now:
                            new_false.append((arm, qid, w, h["rank"], h["chunk_id"]))
        P(f"  新增可答块(潜在假阳): {len(new_true)}  变不可答(回归): {len(new_false)}")
        for nt in new_true:
            arm, qid, w, rank, cid, loc, txt = nt
            P(f"    [+] {arm} {qid} {w} rank{rank} {loc}")
            P(f"        问:{qs[qid]}")
            P(f"        块:{txt[:100].replace(chr(10),' ')}")
        for nf in new_false:
            P(f"    [-] {nf}")
        summary[name] = {"skill_answerable": a_skill["answerable"],
                         "new_true": len(new_true), "new_false": len(new_false),
                         "new_true_detail": [(x[1], x[2], x[3], x[5]) for x in new_true]}

    P("")
    P("=" * 70)
    P("P7 模拟汇总")
    P("=" * 70)
    for name, s in summary.items():
        P(f"  {name}: 真答案可答={s['skill_answerable']} 新增可答={s['new_true']} "
          f"回归={s['new_false']}")
    with open(os.path.join(BASE, "p7_yesno_sim_results.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    txt = "\n".join(out)
    with open(os.path.join(BASE, "p7_yesno_sim_out.txt"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    print(txt)
    print("\nwritten p7_yesno_sim_results.json")


if __name__ == "__main__":
    main()