# -*- coding: utf-8 -*-
"""生产接线实测对照件：臂 union12/top3 vs 生产 hybrid vs 生产 bm25_only。

逐格直接计数（E.summarize 口径），不推算。用法：py -3 -u gen_prod_compare.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(p):
    return json.loads((HERE / p).read_text(encoding="utf-8"))


def main():
    arm = load("p1_results_ext.json")["variants"]["union12/top3_conditional"]
    hyb = load("prod_results_hybrid.json")
    bm = load("prod_results_bm25.json")
    ag = {g["id"]: g for g in arm["grades"]}
    hg = {g["id"]: g for g in hyb["grades"]}
    bg = {g["id"]: g for g in bm["grades"]}
    ids = [g["id"] for g in hyb["grades"]]

    lines = ["# 生产接线实测对照（2026-11-19）", "",
             "口径：top3_conditional + union12（用户批准）。判分器与臂侧同一份 eval_common.grade。",
             "生产 hybrid = kb.query 走 kb_dense.enhance（BGE-M3 + bge-reranker-v2-m3，CUDA）；",
             "生产 bm25 = 无稠密增强时的明示退回路径。臂侧 BM25 是 Haystack 实现，生产是自研 BM25，",
             "两者词表相同但打分实现不同，逐题允许有差异，差异逐格列出。", "",
             "## 1. 总数（逐格计数）", "",
             "| 口径 | 过/总 | strict_pass | gold_in_topk | refuse | version_guard | 失败题 |",
             "|---|---|---|---|---|---|---|"]
    for name, s in [("臂 union12/top3", arm["summary"]),
                    ("生产 hybrid_union12", hyb["summary"]),
                    ("生产 bm25_only", bm["summary"])]:
        bt = s["by_tier"]

        def cell(t):
            x = bt.get(t, {"ok": 0, "total": 0})
            return f"{x['ok']}/{x['total']}"
        lines.append(f"| {name} | {s['ok']}/{s['total']} | {cell('strict_pass')} | "
                     f"{cell('gold_in_topk')} | {cell('refuse')} | {cell('version_guard')} | "
                     f"{', '.join(s['failed_ids']) or '无'} |")
    lines += ["", "## 2. 逐题矩阵", "",
              "| 题 | 档 | 臂 union12/top3 | 生产 hybrid | 生产 bm25 | hybrid 检索 | gold位(hyb) | 附条件 |",
              "|---|---|---|---|---|---|---|---|"]
    for i in ids:
        a, h, b = ag[i], hg[i], bg[i]

        def mark(g):
            return ("OK" if g["ok"] else "FAIL") + "/" + g["status"]
        lines.append(f"| {i} | {h['tier']} | {mark(a)} | {mark(h)} | {mark(b)} | "
                     f"{h.get('retrieval') or '-'} | {h.get('gold_pos') or '-'} | "
                     f"{'Y' if h.get('condition') else '-'} |")
    lines += ["", "## 3. 生产与臂不一致的题（逐格）", ""]
    diff = 0
    for i in ids:
        a, h = ag[i], hg[i]
        if a["ok"] != h["ok"] or a["status"] != h["status"]:
            diff += 1
            lines.append(f"- **{i}**：臂 {a['status']}/{'OK' if a['ok'] else 'FAIL'}"
                         f"（{a['why']}）→ 生产 {h['status']}/{'OK' if h['ok'] else 'FAIL'}"
                         f"（{h['why']}），gold位={h.get('gold_pos')}")
    if not diff:
        lines.append("无（26 题 ok 与 status 全部一致）。")
    lines += ["", "## 4. 拒答与附条件明细（生产 hybrid）", ""]
    for i in ids:
        h = hg[i]
        tags = []
        if h.get("refusal"):
            tags.append(f"拒答={h['refusal']}")
        if h.get("condition"):
            tags.append(h["condition"])
        if tags:
            lines.append(f"- {i}：{'；'.join(tags)}")
    out = HERE / "生产接线实测_2026-11-19.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写 {out.name}（{len(lines)} 行），不一致题 {diff}")


if __name__ == "__main__":
    main()