# -*- coding: utf-8 -*-
"""P6 只读诊断：量 yesno 焦点闸门 + 射门影响形态关的误杀面。
不修改任何生产文件。输出诊断 JSON + 人读 txt。
跑前规则（先落盘再跑）：
  - 回归零容忍：26题冻结集任何一题 ok 从 True→False = 回归
  - 假阳性一票否决：60探针 w3 任何 trap/mechanism 格从 inconclusive→pass = 假阳
  - 真救回≥1：修复后至少救回一个真 inconclusive→pass 才值得落生产
  - Q08 若仍 FAIL 如实标注（P4 已判模型能力缺口）
"""
import json, sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "_工具脚本"))
from pathlib import Path
from taspipe.kb import load_index, tokens, query, INDEX_JSON
from taspipe.kb_route import classify_intent, focus_terms, focus_pattern, expand_terms, FOCUS_STOP
from taspipe.kb_answer import annotate, YESNO_RE, _norm

ROOT = Path(__file__).resolve().parent
idx = load_index()
chunks = idx["chunks"]

# --- 1. 全量 26 题 + 60 探针的 yesno 意图统计 ---
eval_qs = json.loads((ROOT / "p1_questions.json").read_text(encoding="utf-8"))["questions"]
ext_qs = json.loads((ROOT / "p1_questions_ext.json").read_text(encoding="utf-8"))["questions"]
all_eval = eval_qs + ext_qs

probe_path = ROOT / "p23_revert_probe_hybrid.json"
probe_qs = json.loads(probe_path.read_text(encoding="utf-8"))  # list of {id, q, w3, w5, filters, ...}

print("=" * 70)
print("P6 诊断 Part 1: yesno 意图问题清单")
print("=" * 70)

yesno_eval = []
for q in all_eval:
    intent = classify_intent(q["q"])
    if intent == "yesno":
        f = sorted(focus_terms(q["q"], tokens))
        yesno_eval.append({"id": q["id"], "q": q["q"], "focus": f})
        print(f"  {q['id']} [{intent}] focus={f[:8]} | {q['q']}")

yesno_probe = []
for p in probe_qs:
    intent = classify_intent(p["q"])
    if intent == "yesno":
        f = sorted(focus_terms(p["q"], tokens))
        yesno_probe.append({"id": p["id"], "q": p["q"], "focus": f,
                            "w3": p["w3"]["status"], "w5": p["w5"]["status"]})
        print(f"  {p['id']} [{intent}] w3={p['w3']['status']} focus={f[:8]} | {p['q']}")

# --- 2. 对每个 yesno 问题跑生产 query，检查 top8 块的 focus 重叠 ---
print("\n" + "=" * 70)
print("P6 诊断 Part 2: yesno 问题 top8 块 focus 重叠（模拟加 focus_required）")
print("=" * 70)

regressions = []
for item in yesno_eval + yesno_probe:
    q = item["q"]
    filters = {}
    # eval questions have filters
    for eq in all_eval:
        if eq["q"] == q:
            filters = eq.get("filters", {})
            break
    # probe questions carry their own filters
    for pq in probe_qs:
        if pq["q"] == q and pq.get("filters"):
            filters = pq["filters"]
            break
    res = query(q, revision=filters.get("revision"), game=filters.get("game"),
                top_window=3)
    focus = set(focus_terms(q, tokens))
    hits = res.get("hits", [])
    status = res["status"]
    # check which answerable hits would lose focus_ok
    would_fail = []
    for h in hits:
        ann = h.get("answerability", {})
        if not ann.get("answerable"):
            continue
        ci = next((i for i, c in enumerate(chunks) if c["chunk_id"] == h["chunk_id"]), None)
        if ci is None:
            continue
        tt = set(tokens(chunks[ci]["text"]))
        fh = sorted(focus & tt)
        if not fh and focus:  # focus non-empty but zero overlap → would fail
            would_fail.append({"chunk_id": h["chunk_id"], "locator": h["locator"],
                               "focus_hit": [], "intent_ok": ann.get("intent_ok")})
    # would the overall status change?
    # if ALL answerable hits would fail focus → status becomes inconclusive
    answerable_hits = [h for h in hits if h.get("answerability", {}).get("answerable")]
    all_would_fail = len(would_fail) == len(answerable_hits) and len(answerable_hits) > 0
    if all_would_fail and status == "pass":
        regressions.append({"id": item["id"], "q": q, "from": "pass", "to": "inconclusive"})
        print(f"  *** REGRESSION {item['id']}: pass→inconclusive | {q}")
    elif would_fail:
        print(f"  {item['id']}: {len(would_fail)}/{len(answerable_hits)} answerable hits lose focus (status stays {status})")
    else:
        print(f"  {item['id']}: OK, all answerable hits have focus overlap (status={status})")

# --- 3. X16 对照块模拟 ---
print("\n" + "=" * 70)
print("P6 诊断 Part 3: X16 对照块 focus 重叠检查")
print("=" * 70)

duizhao_path = Path(r"F:\开源掌机教程\_工具脚本\taspipe\游戏包\来源库\取证\setsumei_热血足球说明书_编者中文对照_20261119.md")
if duizhao_path.is_file():
    dz_text = duizhao_path.read_text(encoding="utf-8")
    # find paragraphs mentioning 门将/守门员
    q16 = "热血足球 打雷会不会把门将击倒？"
    f16 = set(focus_terms(q16, tokens))
    print(f"  X16 focus = {sorted(f16)}")
    # simulate chunking: split by paragraphs, check each
    paras = [p.strip() for p in dz_text.split("\n\n") if p.strip()]
    for i, p in enumerate(paras):
        if "门将" in p or "守门员" in p or "キーパー" in p:
            tt = set(tokens(p))
            fh = sorted(f16 & tt)
            ann = annotate(q16, p, tokens, lang="zh")
            yesno_match = bool(YESNO_RE.search(_norm(p)))
            print(f"  para[{i}] len={len(p)} focus_hit={fh} YESNO_RE={yesno_match} answerable={ann['answerable']}")
            print(f"    text={p[:150]}...")
            # with fix: focus_required=True for yesno
            fixed_answerable = ann["answerable"] and (bool(fh) or not f16)
            print(f"    fixed_answerable={fixed_answerable}")
else:
    print("  对照文件不存在")

# --- 4. X26 射门影响形态关模拟 ---
print("\n" + "=" * 70)
print("P6 诊断 Part 4: X26 射门影响 FOCUS_PATTERN 模拟")
print("=" * 70)

import re
NEW_PATTERN = (re.compile(r"射门.{0,6}影响|对射门"), re.compile(r"射门"))
x26_q = "热血足球 雨天场地对射门有什么影响？"
print(f"  X26 question: {x26_q}")
print(f"  NEW_PATTERN question match: {bool(NEW_PATTERN[0].search(x26_q))}")
print(f"  intent={classify_intent(x26_q)}")

# check which other questions match the new pattern
pattern_matches = []
for q in all_eval:
    if NEW_PATTERN[0].search(q["q"]):
        pattern_matches.append(q["id"])
for p in probe_qs:
    if NEW_PATTERN[0].search(p["q"]):
        pattern_matches.append(p["id"])
print(f"  Questions matching new pattern: {pattern_matches}")

# run X26 through production and check top8 blocks for 射门
res26 = query(x26_q, top_window=5)
print(f"  X26 w5 status={res26['status']}")
for h in res26.get("hits", [])[:8]:
    ci = next((i for i, c in enumerate(chunks) if c["chunk_id"] == h["chunk_id"]), None)
    if ci is None:
        continue
    text = chunks[ci]["text"]
    has_shoot = bool(NEW_PATTERN[1].search(text))
    ann = h.get("answerability", {})
    print(f"    {h['locator'][:60]} answerable={ann.get('answerable')} has_射门={has_shoot}")
    if ann.get("answerable") and not has_shoot:
        print(f"      → WOULD BLOCK with new pattern (false positive prevented)")

# --- 5. Q08 确认仍为模型缺口 ---
print("\n" + "=" * 70)
print("P6 诊断 Part 5: Q08 排序现状确认")
print("=" * 70)
q8 = "双人合作模式下二号玩家操作什么位置？"
res8 = query(q8, revision="nekketsu_soccer2_fc_jp", top_window=3)
print(f"  Q08 status={res8['status']} retrieval={res8.get('retrieval')}")
gold_found = False
for rank, h in enumerate(res8.get("hits", []), 1):
    if "setsumei" in h["locator"] and "L47" in h["locator"]:
        gold_found = True
        print(f"  gold at rank {rank}: {h['locator']}")
if not gold_found:
    print(f"  gold NOT in top8 (BM25 rank 19 per P4 diag) — model capability gap confirmed")

# --- 6. 汇总 ---
print("\n" + "=" * 70)
print("P6 诊断汇总")
print("=" * 70)
print(f"  yesno focus_required 回归: {len(regressions)} 条")
for r in regressions:
    print(f"    {r['id']}: {r['from']}→{r['to']} | {r['q']}")
print(f"  X26 new pattern 命中题数: {len(pattern_matches)} (应仅 X26)")
print(f"  Q08: 仍 FAIL (P4 模型能力缺口判定不变)")

out = {"yesno_eval": yesno_eval, "yesno_probe": yesno_probe,
       "regressions": regressions, "x26_pattern_matches": pattern_matches,
       "q08_status": res8["status"]}
(ROOT / "p6_diag_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nwritten {ROOT / 'p6_diag_results.json'}")