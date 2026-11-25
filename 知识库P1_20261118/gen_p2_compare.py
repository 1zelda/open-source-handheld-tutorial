# -*- coding: utf-8 -*-
"""P2 实测对照件生成：P1 两路 vs P2 三路，26 题逐格矩阵 + 差异归因。
用法：py -3 -u gen_p2_compare.py（输出 P2实测对照_2026-11-19.md）
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def gm(d):
    return {g["id"]: g for g in d["grades"]}


def cell(g):
    return "OK" if g["ok"] else "FAIL"


def main():
    p1h, p1b = load("prod_results_hybrid.json"), load("prod_results_bm25.json")
    p2h, p2b, p2w = (load("p2_prod_results_hybrid.json"),
                     load("p2_prod_results_bm25.json"),
                     load("p2_prod_results_window5.json"))
    a, b, c, e, f = gm(p1h), gm(p1b), gm(p2h), gm(p2b), gm(p2w)
    resw = {r["id"]: r["res"] for r in p2w["results"]}
    resh = {r["id"]: r["res"] for r in p2h["results"]}
    idx = json.loads((HERE.parent / "_工具脚本" / "taspipe" / "游戏包" / "知识库"
                      / "index.json").read_text(encoding="utf-8"))
    langs = {}
    for ch in idx["chunks"]:
        langs[ch.get("lang", "zh")] = langs.get(ch.get("lang", "zh"), 0) + 1
    lines = ["# P2 实测对照（2026-11-19，26 题冻结集，逐格直接计数）", "",
             "口径：生产 kb.query 真实入口；判分器 eval_common.grade 与臂侧同一份。",
             "P1 两路来自接线完成版实测；P2 三路为 v4 索引（tok3/chunk4）重建后本轮真跑。",
             "window5 只是测量变体，生产默认 top_window=3（用户批准口径）未动。", "",
             "## 总分", "",
             "| 路 | P1 | P2 | 失败题 |", "|---|---|---|---|"]
    for name, x, y in [("hybrid（默认 top3）", a, c), ("bm25_only", b, e),
                       ("hybrid + window5（仅测量）", None, f)]:
        p1s = f"{sum(g['ok'] for g in x.values())}/26" if x else "—"
        fails = ", ".join(i for i, g in y.items() if not g["ok"]) or "无"
        lines.append(f"| {name} | {p1s} | {sum(g['ok'] for g in y.values())}/26 | {fails} |")
    lines += ["", "refuse 档：P2 三路均 9/9；version_guard：三路均 1/1。", "",
              "## 逐题矩阵", "",
              "| 题 | P1 hybrid | P1 bm25 | P2 hybrid | P2 bm25 | P2 window5 | 金标位(hyb/w5) | w5 条件 |",
              "|---|---|---|---|---|---|---|---|"]
    for qid in a:
        gp = f"{c[qid].get('gold_pos')}/{f[qid].get('gold_pos')}"
        cond = f[qid].get("condition") or "—"
        lines.append(f"| {qid} | {cell(a[qid])} | {cell(b[qid])} | {cell(c[qid])} "
                     f"| {cell(e[qid])} | {cell(f[qid])} | {gp} | {cond} |")
    lines += ["", "## 变化归因（逐格）", "",
              "- **P22/P23 转绿（两路）**：假名成词（tok3）+ 真贪心打包（chunk4）+ 日文 howto 形态关。"
              "P23 金标块（setsumei L269 たいりょく）旧分词 dl=0 永远召回不到；P22 日文操作块旧形态关误杀。"
              "bm25_only 也转绿证明不依赖稠密。",
              "- **Q02 window5 转绿**：金标稳定在第 4 位，top3 窗口够不着；window5 附条件出证"
              "（condition 点名第 4 位）。默认 top3 下仍 FAIL——这是窗口口径差异，不是检索回归。",
              "- **Q07 bm25 转绿**：贪心合并后日文块词频集中，BM25 排序改善。",
              "- **Q08 三路仍 FAIL**：跨语扩展已触发（query_expansion 含 協力/モード/ポジション/2），"
              "但金标 L47（２Ｐ協力プレイ…１ＰはＭＦ…２ＰはＧＫ）全库唯一，被メンバー紹介段"
              "（ポジション高频）压出 top8；稠密也救不回。不硬调参，留待后续。",
              "- **Q10 hybrid/window5 仍 FAIL、bm25 OK**：union12 重排把金标块（素材生产规范 L185-190）"
              "挤出 top8，与 P1 诊断一致，是池口径的真代价。",
              "- **Q03/Q06 bm25 FAIL、hybrid OK**：词法路排序差，稠密+重排救回（P1 起如此，非本轮变化）。",
              "- **window5 零回归**：P2 hybrid 所有 OK 题在 window5 仍 OK；refuse 9/9 不变。", "",
              "## 底账", "",
              f"- 索引：{len(idx['chunks'])} 块（ja{langs.get('ja', 0)}/zh{langs.get('zh', 0)}），"
              "zh 逐块同 v2 sha 零漂移（说明书自身编辑除外），"
              "16 题金标行全覆盖（verify_rebuild_v4.py）。",
              "- 闸门 84/84（+10）、全量 selftest 673/673（+10）、dense cuda 重建、"
              "audit 6 pass/0 fail/1 inconclusive（authoritative_ready 为接线前既有语料缺口）。",
              "- 结果件：p2_prod_results_hybrid.json / p2_prod_results_bm25.json / "
              "p2_prod_results_window5.json（含逐题 res 全文，可复核）。"]
    out = HERE / "P2实测对照_2026-11-19.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written {out} {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()