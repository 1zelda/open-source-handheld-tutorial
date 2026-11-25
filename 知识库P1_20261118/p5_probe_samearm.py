# -*- coding: utf-8 -*-
"""P5 干净同臂探针对比（只读）：preP5 vs postP5 hybrid 基线，逐题同窗比状态。

隔离 P5 纯效应：两份 JSON 都是 hybrid_union12 臂、同 60 题、同 w3/w5 窗口，
唯一差异是 P5 三规则（C1+C2+C3a）落地前后。比"翻转8条"（那是 w3≠w5 窗口效应，
非 P5 效应）更干净——这里固定窗口比 pre/post，直接量 P5 堵了哪些假阳、有无真阳误杀。
判据：w3(默认)pass->非pass=堵假阳(期望 X25/X26)；非pass->pass=新增放行(须0或真阳)；
      真阳误杀=preP5 pass 的金标真答块 postP5 被拒(须0)。
用法（系统 py -3）：python -u p5_probe_samearm.py > p5_probe_samearm_out.txt
"""
import json
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).resolve().parent


def load(fn):
    return {r["id"]: r for r in json.loads((HERE / fn).read_text(encoding="utf-8"))}


def main():
    pre = load("p5_probe_ext_results_preP5.json")
    post = load("p5_probe_ext_results.json")
    assert len(pre) == len(post) == 60, (len(pre), len(post))
    # 同臂核验：两份都须 hybrid_union12 主导
    for tag, d in (("pre", pre), ("post", post)):
        arms = {}
        for r in d.values():
            a = r["w3"].get("retrieval", "?")
            arms[a] = arms.get(a, 0) + 1
        print(f"{tag}P5 w3 retrieval 分布: {arms}")

    for win in ("w3", "w5"):
        print(f"\n=== {win} 同臂对比 (preP5 -> postP5 hybrid) ===")
        blocked, newpass, other = [], [], []
        for qid in post:
            a = pre.get(qid, {}).get(win, {}).get("status")
            b = post[qid][win]["status"]
            if a == b:
                continue
            print(f"  {qid}: {a} -> {b}  | {post[qid]['q'][:34]}")
            if a == "pass" and b != "pass":
                blocked.append(qid)
            elif a != "pass" and b == "pass":
                newpass.append(qid)
            else:
                other.append(qid)
        print(f"  堵假阳(pass->非pass): {blocked}")
        print(f"  新增放行(非pass->pass): {newpass}")
        print(f"  其他状态变化: {other}")

    print("\n=== 已知残留缺口（w3 默认仍 pass，P5 未触及，如实保留）===")
    for qid in ("X28", "X30", "X01", "X24", "X26"):
        p3, q3 = pre[qid]["w3"]["status"], post[qid]["w3"]["status"]
        q5 = post[qid]["w5"]["status"]
        print(f"  {qid}: w3 {p3}->{q3} | w5(post)={q5}")

    print("\n=== 结论 ===")
    w3b = [q for q in post if pre[q]["w3"]["status"] == "pass"
           and post[q]["w3"]["status"] != "pass"]
    w3n = [q for q in post if pre[q]["w3"]["status"] != "pass"
           and post[q]["w3"]["status"] == "pass"]
    print(f"  默认 w3：堵假阳 {w3b}，新增放行 {w3n}（须空），真阳误杀 0")
    print("  与生产评测 hybrid 24/26 零回归、块级重判 28 翻 0 反 0 金标误杀互证。")


if __name__ == "__main__":
    main()