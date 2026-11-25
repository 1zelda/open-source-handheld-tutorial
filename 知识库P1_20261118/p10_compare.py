# -*- coding: utf-8 -*-
"""P10 两臂逐格重验对比（零 LLM，只读已落盘产物）。

bm25 臂：P10 vs P7 生产基线须逐格零差异（base 625 未动 + 全局 IDF 兜底构造零回归）。
hybrid 臂：P10 vs P7 基线 ok 零回归；vs P8 全局 IDF 须修 Q10；探针复现 P9 改善格。
跑前规则：R1 假阳一票否决 / R2 回归零容忍 / R3 真救回≥1。
用法：py -3 -u p10_compare.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8")


def load(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def grades_by_id(ev):
    return {g["id"]: g for g in ev["grades"]}


def probe_by_id(rows):
    return {r["id"]: r for r in rows}


def ok_set(ev):
    return {g["id"] for g in ev["grades"] if g["ok"]}


def probe_status(rows, w):
    return {r["id"]: r[w]["status"] for r in rows}


def main():
    verdict = []

    def check(name, cond, detail=""):
        verdict.append((name, bool(cond)))
        print(f"{'OK ' if cond else 'FAIL'} {name}" + (f" | {detail}" if detail else ""))

    # ── bm25 臂：逐格零差异 ──────────────────────────────────
    b10 = load("p10_prod_bm25.json")
    b7 = load("p7_prod_bm25.json")
    gb10, gb7 = grades_by_id(b10), grades_by_id(b7)
    diff = [i for i in gb7 if json.dumps(gb10.get(i), sort_keys=True, ensure_ascii=False)
            != json.dumps(gb7[i], sort_keys=True, ensure_ascii=False)]
    check("bm25 评测逐格零差异(vs P7)", not diff and b10["summary"]["ok"] == b7["summary"]["ok"],
          f"ok={b10['summary']['ok']}/{b10['summary']['total']} diff_ids={diff}")
    pb10 = load("p10_probe_bm25.json")
    pb7 = load("p7_probe_bm25")
    ppb10, ppb7 = probe_by_id(pb10), probe_by_id(pb7)
    pdiff = [i for i in ppb7
             if json.dumps({k: ppb10.get(i, {}).get(k) for k in ("flip", "w3", "w5")},
                           sort_keys=True, ensure_ascii=False)
             != json.dumps({k: ppb7[i][k] for k in ("flip", "w3", "w5")},
                           sort_keys=True, ensure_ascii=False)]
    check("bm25 探针逐格零差异(vs P7)", not pdiff, f"diff_ids={pdiff}")

    # ── hybrid 臂：ok 零回归 + 复现 P9 ───────────────────────
    h10 = load("p10_prod_hybrid.json")
    h7 = load("p7_prod_hybrid.json")
    h8 = load("p8_reindex_hybrid_eval.json")
    ok10, ok7, ok8 = ok_set(h10), ok_set(h7), ok_set(h8)
    reg = sorted(ok7 - ok10)
    new = sorted(ok10 - ok7)
    check("hybrid 评测 ok 零回归(vs P7)", not reg,
          f"ok={h10['summary']['ok']}/{h10['summary']['total']} 回归={reg} 新增={new}")
    check("hybrid 评测 ok 集 == P7 基线", ok10 == ok7,
          f"fail={h10['summary']['failed_ids']}")
    gh10, gh8 = grades_by_id(h10), grades_by_id(h8)
    q10_fix = (gh8["Q10"]["ok"] is False and gh10["Q10"]["ok"] is True
               and gh8["Q10"]["gold_pos"] is None and gh10["Q10"]["gold_pos"] == 8)
    check("hybrid Q10 修好(vs P8 全局: False→True, gold None→8)", q10_fix,
          f"P10 Q10 ok={gh10['Q10']['ok']} gold_pos={gh10['Q10']['gold_pos']}")
    new_vs8 = sorted(ok10 - ok8)
    check("hybrid vs P8 ok 新增 == ['Q10']", new_vs8 == ["Q10"], f"新增={new_vs8}")

    # ── hybrid 探针：复现 P9 改善格 + 无真回归 ───────────────
    ph10 = load("p10_probe_hybrid.json")
    ph7 = load("p7_probe_hybrid")
    pph10, pph7 = probe_by_id(ph10), probe_by_id(ph7)
    flips = []
    for i in pph7:
        for w in ("w3", "w5"):
            s7 = pph7[i][w]["status"]
            s10 = pph10.get(i, {}).get(w, {}).get("status")
            if s7 != s10:
                flips.append((i, w, s7, s10))
    pass_reg = [(i, w, a, b) for i, w, a, b in flips if a == "pass" and b != "pass"]
    # P9 预期：唯一 pass→非pass 是 X24 w5（trap 假阳修复，非回归）
    check("hybrid 探针 pass→非pass 仅 X24 w5(trap 修复)",
          pass_reg == [("X24", "w5", "pass", "inconclusive")],
          f"pass_reg={pass_reg}")
    new_pass = sorted({(i, w) for i, w, a, b in flips if a != "pass" and b == "pass"})
    expect_new = {("W03", "w3"), ("W03", "w5"), ("W09", "w3"), ("W09", "w5"),
                  ("W10", "w5"), ("W13", "w5"), ("X03", "w3")}
    check("hybrid 探针新 pass 格 == P9 预期", set(new_pass) == expect_new,
          f"新pass={sorted(new_pass)}")
    # W29/X16/X26 不许翻（P6 守住 + 重排器吸收）
    held = []
    for i in ("W29", "X16", "X26"):
        for w in ("w3", "w5"):
            if pph7[i][w]["status"] != pph10.get(i, {}).get(w, {}).get("status"):
                held.append((i, w))
    check("hybrid W29/X16/X26 状态没翻(P6 守住)", not held, f"翻={held}")
    # R1（跑前规则口径，同 P8/P9）：新增假阳一票否决。既有 trap 放行属诚实缺口非 R1 触发。
    def trap_pass(rows):
        return {r["id"] for r in rows if r["kind"] == "trap"
                and (r["w3"]["status"] == "pass" or r["w5"]["status"] == "pass")}
    tp10, tp7 = trap_pass(ph10), trap_pass(ph7)
    new_trap = sorted(tp10 - tp7)
    check("R1 hybrid 无新增 trap 放行(vs P7)", not new_trap,
          f"新增={new_trap} trap标记格={sorted(tp10)}（X17/X18 经文件级核实真阳正对照，X16 应拒已守住）")
    # 既有 trap 标记格状态未变（X17/X18 实为真阳：密码 L237/3次 L235；pass→pass 无回归）
    pre_changed = [(i, w) for i in sorted(tp10 & tp7) for w in ("w3", "w5")
                   if pph10[i][w]["status"] != pph7[i][w]["status"]]
    check("trap 标记格(X17/X18 真阳)状态未变(pass→pass)", not pre_changed,
          f"状态变={pre_changed}（真阳正对照，P10 未恶化；hits 重排属域内 IDF 预期，见报告）")
    # W03 真答案核实：rank1 必杀技节 cca1975a46e1（非规则块）
    w03 = pph10["W03"]["w3"]
    top1 = w03["hits"][0] if w03["hits"] else {}
    check("W03 w3 真答案 rank1=必杀技节 cca1975a46e1(非规则块)",
          w03["status"] == "pass" and top1.get("chunk_id") == "cca1975a46e1"
          and top1.get("answerable") is True,
          f"status={w03['status']} top1={top1.get('chunk_id')} ans={top1.get('answerable')}")

    n_ok = sum(1 for _, c in verdict if c)
    print(f"\nP10_COMPARE {n_ok}/{len(verdict)}")
    print(f"bm25 ok={b10['summary']['ok']}/26  hybrid ok={h10['summary']['ok']}/26")
    sys.exit(0 if n_ok == len(verdict) else 1)


if __name__ == "__main__":
    main()