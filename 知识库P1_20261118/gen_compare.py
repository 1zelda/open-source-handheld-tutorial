# -*- coding: utf-8 -*-
"""从终版评测结果逐格生成效果对比件：矩阵+翻转清单+真实输出样例。只读结果JSON。"""
import json
from pathlib import Path

H = Path(__file__).resolve().parent
out = json.loads((H / "p1_results_ext.json").read_text(encoding="utf-8"))
spec = json.loads((H / "p1_questions_ext.json").read_text(encoding="utf-8"))
qs = spec["questions"]
V4 = ["union/strict_top1", "union/top3_conditional",
      "union12/strict_top1", "union12/top3_conditional"]
SHORT = {"union/strict_top1": "union·严格", "union/top3_conditional": "union·top3",
         "union12/strict_top1": "u12·严格", "union12/top3_conditional": "u12·top3"}

def cell(v, qid):
    g = next(x for x in out["variants"][v]["grades"] if x["id"] == qid)
    return ("✓" if g["ok"] else "✗") + g["status"]

def res(v, qid):
    return next(x["result"] for x in out["variants"][v]["results"] if x["id"] == qid)

L = []
L.append("# 效果对比：权威策略 × 重排池口径（26 题冻结集，全部取自终版实测结果）\n")
L.append("日期：2026-11-19。数据源：p1_results_ext.json（arm3 跑批），逐格直接计数。")
L.append("用户已批准推荐口径：**top3_conditional + union12**（本件用于看清差别在哪）。\n")
L.append("## 1. 六变体总表\n")
L.append("| 变体 | 总过 | strict_pass | gold_in_topk | refuse | version_guard |")
L.append("|---|---|---|---|---|---|")
for v, d in out["variants"].items():
    s = d["summary"]; t = s["by_tier"]
    L.append(f"| {v} | {s['ok']}/{s['total']} | "
             f"{t['strict_pass']['ok']}/{t['strict_pass']['total']} | "
             f"{t['gold_in_topk']['ok']}/{t['gold_in_topk']['total']} | "
             f"{t['refuse']['ok']}/{t['refuse']['total']} | "
             f"{t['version_guard']['ok']}/{t['version_guard']['total']} |")
L.append("\n拒答档 9/9 六变体全保持：放宽策略/扩池都没有引入新假阳性。\n")
L.append("## 2. 逐题矩阵（4 主力变体）\n")
L.append("✓=该题判分通过 ✗=未过；后面是闸门状态。u12=union12 池。\n")
L.append("| 题 | 问句 | 档位 | " + " | ".join(SHORT[v] for v in V4) + " |")
L.append("|---|---|---|---|---|---|---|")
for q in qs:
    L.append(f"| {q['id']} | {q['q']} | {q['expect']} | "
             + " | ".join(cell(v, q["id"]) for v in V4) + " |")

L.append("\n## 3. 翻转清单（差别到底在哪几题）\n")
L.append("### 3.1 策略效果（union12 池固定，严格 → top3 附条件）\n")
for q in qs:
    a = next(x for x in out["variants"][V4[2]]["grades"] if x["id"] == q["id"])
    b = next(x for x in out["variants"][V4[3]]["grades"] if x["id"] == q["id"])
    if a["ok"] != b["ok"]:
        rb = res(V4[3], q["id"])
        L.append(f"- **{q['id']}** {q['q']}：严格={a['status']} → top3={b['status']}"
                 + (f"（{rb.get('condition')}）" if rb.get("condition") else ""))
L.append("\n### 3.2 池效果（top3 策略固定，union → union12）\n")
for q in qs:
    a = next(x for x in out["variants"][V4[1]]["grades"] if x["id"] == q["id"])
    b = next(x for x in out["variants"][V4[3]]["grades"] if x["id"] == q["id"])
    if a["ok"] != b["ok"]:
        turn = "过→败" if a["ok"] else "败→过"
        L.append(f"- **{q['id']}** {q['q']}：**{turn}**"
                 f"（union={a['status']} → union12={b['status']}；"
                 f"状态相同但金标在不在 hits 里不同，strict_pass/gold_in_topk 档要求金标在场）")

def example(qid, va, vb, note, n=3):
    L.append(f"\n### 例：{qid}（{note}）\n")
    q = next(x for x in qs if x["id"] == qid)
    L.append(f"问句：{q['q']}\n")
    gold = q.get("gold")
    for v in (va, vb):
        r = res(v, qid)
        g = next(x for x in out["variants"][v]["grades"] if x["id"] == qid)
        L.append(f"**{SHORT.get(v, v)}** → {'✓过' if g['ok'] else '✗没过'} / {r['status']}")
        L.append(f"闸门理由：{r.get('reason', '')}")
        if r.get("condition"):
            L.append(f"附条件：{r['condition']}")
        hits = r.get("hits", [])
        for i, h in enumerate(hits[:n], 1):
            a = h.get("answerability", {})
            mark = ""
            if gold and gold["path_contains"] in h["locator"]:
                import re
                m = re.search(r"#L(\d+)-L(\d+)$", h["locator"])
                if m and int(m.group(1)) <= gold["line_end"] and int(m.group(2)) >= gold["line_start"]:
                    mark = " **【金标】**"
            L.append(f"{i}. `{h['locator']}` 权威={h['authority']} 可答={a.get('answerable')}{mark}")
            L.append(f"   > {h['snippet'][:80].replace(chr(10), ' ')}")
        if gold:
            import re
            pos = []
            for i, h in enumerate(hits, 1):
                if gold["path_contains"] not in h["locator"]:
                    continue
                m = re.search(r"#L(\d+)-L(\d+)$", h["locator"])
                if m and int(m.group(1)) <= gold["line_end"] and int(m.group(2)) >= gold["line_start"]:
                    pos.append(i)
            L.append(f"金标位置：{'第' + str(pos[0]) + '位' if pos else '不在 hits（被挤出 top8）'}")
        L.append("")

L.append("\n## 4. 真实输出样例（命中原文摘录，非转述）\n")
example("Q03", V4[2], V4[3], "策略翻转：权威件在第2位，严格卡死、top3附条件放行")
example("Q10", V4[1], V4[3], "池代价：扩池后金标被新候选挤出top8", n=8)
example("P22", V4[1], V4[3], "池收益：日文PK战金标从池外进hits第3位")
L.append("## 5. 一句话结论\n")
L.append("top3 附条件多过的题，检索本来就命中了权威件，只是不在最高分位——放行时强制携带")
L.append("condition 字段，证据标准不放松；union12 多收的是库里有答案但以前永远找不到的题，")
L.append("代价是 Q10 一道压线题。拒答档全保持，放宽没有换来假阳性。")
(H / "效果对比_2026-11-19.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("written", len(L), "lines")