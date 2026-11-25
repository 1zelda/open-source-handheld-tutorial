# -*- coding: utf-8 -*-
"""P7 只读诊断：W03 必杀焦点缺口（证据错）。改生产前量误杀面，零模型零写。

跑前规则（先落盘，结果出来前不得修改）：
  R1 假阳性一票否决：候选形态关若把任何当前真阳/金标块判不可答 => 否决。
  R2 回归零容忍：两臂探针/评测逐格不得变差。
  R3 真救回口径：W03 当前索引已 inconclusive（rank1 可答块是 reference_only 非权威），
     本修复是「预防再索引假阳」——须确证堵住 #23 的 W03 证据错机制
     （对照规则块讲守门员不讲必杀 => 不可答；对照必杀技节讲必杀+守门员 => 可答），
     且当前索引零回归。不硬调参凑 W03 转 pass（排序/权威另说）。
  R4 修不了标诚实缺口：若候选误杀真阳或堵不住机制 => 如实保留 W03 缺口。

候选：窄 FOCUS_PATTERN 问「能不能用必杀」要求答案含「必杀」（同 P6 X26 手法）。
  对照根因：W03 焦点集含必杀，但放行块只重叠守门员（focus_hit=[守门,门员]），
  P6 yesno 闸门只要求任一焦点重叠 => 放行；需形态关补「必杀」硬性要求。
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = r"F:\开源掌机教程"
sys.path.insert(0, os.path.join(ROOT, "_工具脚本"))
from taspipe import kb as K
from taspipe import kb_route as KR

BASE = os.path.join(ROOT, "知识库P1_20261118")
IDX = os.path.join(ROOT, r"_工具脚本\taspipe\游戏包\知识库\index.json")
DUIZHAO = os.path.join(
    ROOT, r"_工具脚本\taspipe\游戏包\来源库\取证\setsumei_热血足球说明书_编者中文对照_20261119.md")

# 候选问句形态（三个口径比窄宽）与答案形态
CANDIDATES = {
    "C1_用必杀": re.compile(r"用必杀"),
    "C2_能不能用必杀": re.compile(r"能不能用必杀|能否用必杀|可不可以用必杀"),
    "C3_必杀能不能": re.compile(r"必杀.{0,6}能不能|能不能.{0,6}必杀"),
}
ANS = re.compile(r"必杀")

index = json.load(open(IDX, encoding="utf-8"))
TEXT = {c["chunk_id"]: c for c in index["chunks"]}


def load_qs():
    """86 题：60 探针(W/X) + 26 评测(Q)，去重带问句原文。"""
    qs = {}
    probe = json.load(open(os.path.join(BASE, "p6_probe_bm25"), encoding="utf-8"))
    for it in probe:
        qs[it["id"]] = it["q"]
    prod = json.load(open(os.path.join(BASE, "p6_prod_bm25.json"), encoding="utf-8"))
    for it in prod["results"]:
        qs[it["id"]] = it["q"]
    return qs, probe, prod


def annotate_with(q, text, lang, extra_pattern):
    orig = KR.FOCUS_PATTERNS
    KR.FOCUS_PATTERNS = orig + [extra_pattern]
    try:
        return K.annotate(q, text, K.tokens, lang=lang)
    finally:
        KR.FOCUS_PATTERNS = orig


def main():
    out = []
    P = out.append
    P("=" * 70)
    P("P7 诊断 Part 1: 候选形态关问句命中面（86 题）")
    P("=" * 70)
    qs, probe, prod = load_qs()
    P(f"  题数: {len(qs)} (探针60 + 评测26)")
    matches = {}
    for name, qrx in CANDIDATES.items():
        hit = [qid for qid, q in qs.items() if qrx.search(q)]
        matches[name] = hit
        P(f"  {name}: 命中 {len(hit)} 题 {hit}")
        for qid in hit:
            P(f"      {qid}: {qs[qid]}")

    P("")
    P("=" * 70)
    P("P7 诊断 Part 2: 当前索引零回归（候选 C1 重判所有可答命中块）")
    P("=" * 70)
    # 取两臂探针所有 answerable=True 命中块，按 chunk_id 取索引原文重判
    flips = []
    checked = 0
    gold_kill = []
    for arm, fn in (("bm25", "p6_probe_bm25"), ("hybrid", "p6_probe_hybrid")):
        pr = json.load(open(os.path.join(BASE, fn), encoding="utf-8"))
        for it in pr:
            qid, q = it["id"], it["q"]
            if not CANDIDATES["C1_用必杀"].search(q):
                continue  # 候选只影响命中问句，其余问句形态关不变 => 必零回归
            for w in ("w3", "w5"):
                for h in it[w].get("hits", []):
                    if not h.get("answerable"):
                        continue
                    c = TEXT.get(h["chunk_id"])
                    if not c:
                        continue
                    checked += 1
                    a = annotate_with(q, c["text"], c.get("lang", "zh"),
                                      (CANDIDATES["C1_用必杀"], ANS))
                    if not a["answerable"]:
                        flips.append((arm, qid, w, h["rank"], h["chunk_id"],
                                      h["locator"], a["pattern_ok"]))
    P(f"  命中问句的可答块重判数: {checked}")
    P(f"  True->False 翻转: {len(flips)}")
    for f in flips:
        P(f"    {f}")
    if not flips:
        P("  零翻转 OK（命中问句的可答块都含必杀）")

    P("")
    P("=" * 70)
    P("P7 诊断 Part 3: 真实对照块验证（W03 证据错机制）")
    P("=" * 70)
    dz = open(DUIZHAO, encoding="utf-8").read()
    paras = [p.strip() for p in dz.split("\n\n") if p.strip()]
    # 规则块：讲守门员/2P分工但不讲必杀
    rules_block = next((p for p in paras if "2P 操作 GK" in p and "必杀" not in p), None)
    # 必杀技节：讲必杀+守门员专用
    skill_block = next((p for p in paras if "守门员专用必杀技" in p), None)
    w03q = qs.get("W03", "热血足球2 守门员能不能用必杀？")
    P(f"  W03 问句: {w03q}")
    for label, blk in (("对照规则块(讲守门员不讲必杀)", rules_block),
                       ("对照必杀技节(讲必杀+守门员)", skill_block)):
        if blk is None:
            P(f"  {label}: 未找到")
            continue
        base_a = K.annotate(w03q, blk, K.tokens)
        new_a = annotate_with(w03q, blk, "zh", (CANDIDATES["C1_用必杀"], ANS))
        P(f"  {label}: len={len(blk)} has_必杀={'必杀' in blk}")
        P(f"    现状(P6): answerable={base_a['answerable']} focus_hit={base_a['focus_hit']} "
          f"intent_ok={base_a['intent_ok']} pattern_ok={base_a['pattern_ok']}")
        P(f"    候选C1 : answerable={new_a['answerable']} pattern_ok={new_a['pattern_ok']} "
          f"focus_ok={new_a['focus_ok']}")
        P(f"    text={blk[:90]}...")

    P("")
    P("=" * 70)
    P("P7 诊断 Part 4: W03 当前 rank1 可答块（须仍可答）")
    P("=" * 70)
    pr = json.load(open(os.path.join(BASE, "p6_probe_bm25"), encoding="utf-8"))
    w03 = next(it for it in pr if it["id"] == "W03")
    for h in w03["w3"].get("hits", [])[:3]:
        c = TEXT.get(h["chunk_id"])
        if not c:
            continue
        new_a = annotate_with(w03q, c["text"], c.get("lang", "zh"),
                              (CANDIDATES["C1_用必杀"], ANS))
        P(f"  rank{h['rank']} {h['authority']} answerable(原)={h['answerable']} "
          f"has_必杀={'必杀' in c['text']} 候选C1_answerable={new_a['answerable']}")
        P(f"    {h['locator']}")

    P("")
    P("=" * 70)
    P("P7 诊断汇总")
    P("=" * 70)
    c1_scope = matches["C1_用必杀"]
    P(f"  C1 命中问句: {c1_scope}（应仅 W03）")
    P(f"  当前索引可答块翻转: {len(flips)}（应 0）")
    rules_blocked = (rules_block is not None and
                     not annotate_with(w03q, rules_block, "zh",
                                       (CANDIDATES["C1_用必杀"], ANS))["answerable"])
    skill_pass = (skill_block is not None and
                  annotate_with(w03q, skill_block, "zh",
                                (CANDIDATES["C1_用必杀"], ANS))["answerable"])
    P(f"  对照规则块被堵: {rules_blocked}（应 True）")
    P(f"  对照必杀技节可答: {skill_pass}（应 True）")
    verdict = (c1_scope == ["W03"] and len(flips) == 0 and rules_blocked and skill_pass)
    P(f"  候选 C1 数据支持: {verdict}")

    res = {"candidates_scope": matches, "flips": flips, "checked": checked,
           "rules_blocked": rules_blocked, "skill_pass": skill_pass,
           "verdict": verdict}
    with open(os.path.join(BASE, "p7_diag_results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    txt = "\n".join(out)
    with open(os.path.join(BASE, "p7_diag_out.txt"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    print(txt)
    print("\nwritten p7_diag_results.json")


if __name__ == "__main__":
    main()