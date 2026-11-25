# -*- coding: utf-8 -*-
"""阶段2 四分类对账（零 LLM，只读已落盘产物 + 真实文件反查）。

四分类：回归（对→错，零容忍）/ 修错（错→对，含尺子升级暴露的假 pass）/
策略变化（口径升级本身）/ 金标修订（Q02 问句补范围）。
基线 = p10_prod_* / p10_probe_*（v1 尺子、p1 题集、旧 kind）。
新件 = ph2_prod_*（v1+v2 双尺子、p2 题集）/ ph2_probe_*（新 kind）。
检索默认未动 ⇒ 除 Q02 外 v1 逐格须与基线一致；探针 status 须逐格一致。
用法：py -3 -u ph2_compare.py
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.stdout.reconfigure(encoding="utf-8")

from taspipe import kb as K  # noqa: E402
from taspipe import sources as S  # noqa: E402

V1_KEYS = ("ok", "status", "top1", "n_hits", "gold_pos")


def load(name):
    p = HERE / name
    if not p.is_file():
        p = HERE / (name + ".json")
    return json.loads(p.read_text(encoding="utf-8"))


def by_id(grades):
    return {g["id"]: g for g in grades}


def main():
    verdict = []
    ledger = {"回归": [], "修错": [], "策略变化": [], "金标修订": [], "未变": []}

    def check(name, cond, detail=""):
        verdict.append((name, bool(cond)))
        print(f"{'OK ' if cond else 'FAIL'} {name}" + (f" | {detail}" if detail else ""))

    p2q = load("p2_questions_ext.json")
    p1q = load("p1_questions_ext.json")
    qtext = {q["id"]: q["q"] for q in p1q["questions"]}

    for arm in ("bm25", "hybrid"):
        base = load(f"p10_prod_{arm}")
        new = load(f"ph2_prod_{arm}")
        gb, gn = by_id(base["grades"]), by_id(new["grades"])
        # 1. 除 Q02 外 v1 逐格零差异（检索未动的直接证据）
        diff = []
        for i in gb:
            if i == "Q02":
                continue
            if any(gn[i].get(k) != gb[i].get(k) for k in V1_KEYS):
                diff.append(i)
        check(f"{arm} 除Q02外 v1 逐格零差异(vs P10)", not diff, f"diff={diff}")
        for i in diff:
            ledger["回归"].append({"arm": arm, "id": i, "kind": "v1格变化",
                                   "old": {k: gb[i].get(k) for k in V1_KEYS},
                                   "new": {k: gn[i].get(k) for k in V1_KEYS}})
        # 2. Q02 金标修订登记
        q02n = next(q for q in p2q["questions"] if q["id"] == "Q02")
        check(f"{arm} Q02 问句已补范围", q02n["q"] != qtext["Q02"] and "热血队内" in q02n["q"],
              f"old={qtext['Q02']!r} new={q02n['q']!r}")
        ledger["金标修订"].append({"arm": arm, "id": "Q02",
                                   "old_q": qtext["Q02"], "new_q": q02n["q"],
                                   "v1_old": gb["Q02"]["ok"], "v1_new": gn["Q02"]["ok"],
                                   "v2_new": gn["Q02"]["v2"]["ok"]})
        # 3. v1→v2 逐题归类（尺子升级 = 策略变化；假 pass 暴露 = 修错）
        for i in gn:
            g = gn[i]
            v1ok, v2ok = g["ok"], g["v2"]["ok"]
            if v1ok == v2ok:
                ledger["未变"].append({"arm": arm, "id": i, "ok": v1ok})
            elif v1ok and not v2ok:
                ledger["修错"].append({"arm": arm, "id": i, "类别": "假pass暴露",
                                       "v1": True, "v2": False,
                                       "selected": g["v2"]["selected_locator"],
                                       "why": g["v2"]["why"]})
            else:
                ledger["回归"].append({"arm": arm, "id": i, "kind": "v2比v1宽（异常）"})
        stricter = [r for r in ledger["回归"] if r.get("kind") == "v2比v1宽（异常）"]
        check(f"{arm} v2 不比 v1 宽（无异常翻转）", not stricter, f"异常={stricter}")
        # 4. 探针 status 逐格零差异（kind 重标不影响检索）
        pb = {r["id"]: r for r in load(f"p10_probe_{arm}")}
        pn = {r["id"]: r for r in load(f"ph2_probe_{arm}.json")}
        pdiff = [i for i in pb
                 if pb[i]["flip"] != pn[i]["flip"]
                 or pb[i]["w3"]["status"] != pn[i]["w3"]["status"]
                 or pb[i]["w5"]["status"] != pn[i]["w5"]["status"]]
        check(f"{arm} 探针60题 flip/w3/w5 status 逐格零差异", not pdiff, f"diff={pdiff}")
        # 5. 出证契约：pass 恰 1 块 selected_evidence 且在 hits 内；非 pass 不带
        bad = []
        for r in new["results"]:
            res = r["res"]
            sel = res.get("selected_evidence") or []
            if res["status"] == "pass":
                if len(sel) != 1 or sel[0]["chunk_id"] not in {h["chunk_id"] for h in res["hits"]}:
                    bad.append(r["id"])
            elif sel:
                bad.append(r["id"] + "(非pass带sel)")
        check(f"{arm} 出证契约逐题成立", not bad, f"bad={bad}")
        # 6. 分表计数 == 逐格求和
        g2s = [g["v2"] for g in new["grades"]]
        st = new["summary_v2"]["split_table"]
        recount = {k: sum(int(g[k]) for g in g2s) for k in
                   ("direct_recall", "correct_evidence", "wrong_evidence",
                    "missed_answer", "citation_valid", "version_condition_error")}
        check(f"{arm} v2 分表==逐格求和", all(st[k] == v for k, v in recount.items()),
              f"recount={recount}")
        # 7. 指纹齐全 + 索引身份
        fp = new.get("fingerprints", {})
        idx = fp.get("indexes", {})
        check(f"{arm} 指纹齐全且索引身份正确",
              fp.get("question_file", {}).get("name") == "p2_questions_ext.json"
              and idx.get("base", {}).get("sha256_16") == "09096a016496405a"
              and idx.get("base", {}).get("chunks") == 625
              and idx.get("base", {}).get("bytes") == 2916773
              and idx.get("hybrid", {}).get("sha256_16") == "8d12dd89abbbdad6"
              and idx.get("hybrid", {}).get("chunks") == 639
              and idx.get("hybrid", {}).get("bytes") == 2953449
              and all(fp.get("code_sha256_16", {}).get(n) for n in
                      ("kb.py", "kb_route.py", "kb_dense.py", "eval_common.py", "prod_eval.py")),
              f"base={idx.get('base')} hybrid={idx.get('hybrid')}")

    # 8. Q10 hybrid 假 pass 暴露实例（评审§1.1 的实锤）
    h = load("ph2_prod_hybrid")
    q10 = by_id(h["grades"])["Q10"]
    check("Q10 hybrid v1过/v2不过，放行依据=无关块8c20fcc4311e",
          q10["ok"] is True and q10["v2"]["ok"] is False
          and q10["v2"]["selected_locator"] is not None
          and "素材生产规范" in q10["v2"]["selected_locator"]
          and "#L18-L31" in q10["v2"]["selected_locator"],
          f"v1={q10['ok']} v2={q10['v2']['ok']} sel={q10['v2']['selected_locator']}")

    # 9. 探针重标完整性：新分类合法 + 问句/filters 与备份逐字一致 + kind_v1 在册
    ext = load("probe_questions_ext.json")
    bak = load("probe_questions_ext.json.bak_20261120")
    tax = {"true_negative", "insufficient_source", "positive_control", "ambiguous"}
    ok_tax = all(q["kind"] in tax and q.get("kind_v1") and q.get("kind_note") and q.get("evidence")
                 for q in ext["questions"])
    ok_txt = all(a["q"] == b["q"] and a.get("filters") == b.get("filters")
                 for a, b in zip(bak["questions"], ext["questions"]))
    check("探针重标：30条新分类+证据附注齐全，问句/filters逐字未动", ok_tax and ok_txt,
          f"tax={ok_tax} txt={ok_txt}")

    # 10. 真实文件反查：两份对照件 + 双索引 sha/字节
    m = json.loads(K.CORPUS_MAP.read_text(encoding="utf-8"))
    zh = [e for e in m["entries"] if e.get("hybrid_only")]
    expect = {"setsumei_热血足球说明书_编者中文对照_20261119.md": ("da3200681eb4f34d", 7472),
              "urawaza_FC热血足球_编者中文对照_20261119.md": ("4389b67595729f60", 1735)}
    badf = []
    for e in zh:
        p = S.resolve_path(e["path"])
        sha = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        exp = expect.get(p.name)
        if e.get("index") is not False or not exp or sha != exp[0] or p.stat().st_size != exp[1]:
            badf.append(p.name)
    check("两份对照件 sha/字节/index:false 未动", not badf and len(zh) == 2, f"bad={badf}")

    # 11. 审计新检查在真实审计里存在且撤回段在册
    a = K.audit()
    ids = {c["check_id"] for c in a["checks"]}
    ret = next(c for c in a["checks"] if c["check_id"] == "retraction_markers")
    check("审计含 authority_inheritance + retraction_markers 且 L230 在册",
          {"authority_inheritance", "retraction_markers"} <= ids
          and any(":L230:" in d for d in ret["detail"]),
          f"checks={sorted(ids)}")

    (HERE / "ph2_ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    n_ok = sum(1 for _, c in verdict if c)
    print(f"\nPH2_COMPARE {n_ok}/{len(verdict)}")
    print(f"四分类：回归={len(ledger['回归'])} 修错={len(ledger['修错'])} "
          f"策略变化=尺子升级(v1→v2) 金标修订={len(ledger['金标修订'])} 未变={len(ledger['未变'])}")
    print(f"修错明细：{[(r['arm'], r['id']) for r in ledger['修错']]}")
    print("ledger written ph2_ledger.json")
    sys.exit(0 if n_ok == len(verdict) else 1)


if __name__ == "__main__":
    main()