# -*- coding: utf-8 -*-
"""来源继承修正回归：生产 query 双臂实测，冻结题集与旧交付只读。"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
HERE = Path(__file__).resolve().parent
P1 = ROOT / "知识库P1_20261118"
OLD = P1 / "kb_final_20261124"
sys.path.insert(0, str(ROOT / "_工具脚本"))
sys.path.insert(0, str(ROOT / "知识库小样_20261118"))

from taspipe import kb as K
from taspipe import kb_blind_eval as BE
from taspipe import kb_dense as KD
from taspipe import kb_provenance as KP
from taspipe import kb_selector as KS
from taspipe import sources as S
import eval_common as E

ARMS = ("base_default", "base_strict", "hybrid_default", "hybrid_strict")
CONFLICTS = {
    "Q01": "冻结 strict_pass 与来源资格冲突：23 种仅见搜狐 S3，S1 无可核验总量。",
    "Q02": "冻结 strict_pass 与来源资格冲突：金表 L70-L85 属 S1 二手操作表。",
    "Q03": "冻结 strict_pass 与来源资格冲突：按键序列属 S1 二手操作表。",
    "Q04": "冻结 strict_pass 与来源资格冲突：难度句属 S1 二手操作表。",
    "Q05": "冻结 strict_pass 与来源资格冲突：换人规则属 S1 二手操作表。",
    "Q18": "新发现历史标注冲突：S1 只写发动音效，S8 才写ひっさつＯＫ且为二手件。",
    "X03": "冻结 positive_control 与当前严格出证冲突：默认选中 S1 汇总表，官方件未进窗口。",
    "X04": "冻结 ambiguous 与 legacy pass 冲突：S1/S8 发动法相反且无本地实测裁决。",
    "X23": "按用户要求保留 insufficient_source 冻结标签；legacy pass 是文件级权威洗白。",
}


def sha(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def state():
    return {str(p): {"exists": p.is_file(), "size": p.stat().st_size if p.is_file() else None,
                     "mtime_ns": p.stat().st_mtime_ns if p.is_file() else None, "sha256": sha(p)}
            for p in BE._protected_paths()}


def selected(res):
    rows = []
    for h in res.get("selected_evidence") or []:
        rows.append({"chunk_id": h.get("chunk_id"), "locator": h.get("locator"),
                     "source_id": h.get("source_id"), "authority": h.get("authority"),
                     "excerpt": (h.get("fragment_provenance") or {}).get("evidence_excerpt"),
                     "provenance": h.get("fragment_provenance")})
    return rows


def compact(res, grade):
    return {"status": res.get("status"), "grade_v2": grade,
            "selected": selected(res), "retrieval": res.get("retrieval"),
            "retrieval_note": res.get("retrieval_note"), "index_used": res.get("index_used"),
            "refusal": res.get("refusal"), "condition": res.get("condition"),
            "authority_warnings": res.get("authority_warnings")}


def call(q, arm):
    f = q.get("filters", {})
    kw = dict(game=f.get("game"), revision=f.get("revision"),
              platform=f.get("platform"), topk=30, top_window=3)
    if arm.endswith("strict"):
        kw["fragment_policy"] = "strict"
    if arm.startswith("base"):
        kw["index_path"] = K.INDEX_JSON
    else:
        kw["index_path"] = K.hybrid_index_path()
    return K.query(q["q"], **kw)


def run(arms, out):
    before = state()
    questions = json.loads((P1 / "p2_questions_ext.json").read_text(encoding="utf-8"))["questions"]
    probes = json.loads((P1 / "probe_questions_ext.json").read_text(encoding="utf-8"))["questions"]
    probe_ids = {"Q01", "Q02", "Q03", "Q04", "Q05", "Q18", "X03", "X04", "X21", "X23"}
    by_id = {q["id"]: q for q in questions}
    by_id.update({q["id"]: q for q in probes if q["id"] in probe_ids})
    rows = []
    for qid, q in by_id.items():
        row = {"id": qid, "q": q["q"], "frozen_tier": q.get("expect"),
               "frozen_kind": q.get("kind"), "arms": {}}
        for arm in arms:
            started = time.perf_counter()
            res = call(q, arm)
            grade = E.grade_v2(q, res) if q.get("expect") else None
            row["arms"][arm] = {**compact(res, grade),
                                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}
        rows.append(row)
        print(qid, " ".join(f"{a}={row['arms'][a]['status']}" for a in arms), flush=True)
    after = state()
    changed = [p for p in before if before[p] != after[p]]
    result = {"schema": "kb_source_inheritance_regression_partial_v1",
              "taken_at": time.strftime("%Y-%m-%d %H:%M:%S"), "arms": list(arms),
              "rows": rows, "isolation": {"ok": not changed, "changed_paths": changed},
              "production_defaults": {"top_window": 3, "fragment_policy": None,
                                      "fact_selector": None},
              "fingerprints": fingerprints()}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("DONE", out, "isolation", result["isolation"]["ok"], flush=True)
    return 0 if result["isolation"]["ok"] else 1


def fingerprints():
    paths = {"questions": P1 / "p2_questions_ext.json",
             "probes": P1 / "probe_questions_ext.json",
             "corpus_map": K.CORPUS_MAP, "source_registry": S.REG_JSON,
             "base_index": K.INDEX_JSON, "hybrid_index": K.hybrid_index_path(),
             "super_list": ROOT / "_工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md"}
    files = {name: {"path": str(p), "sha256": sha(p), "bytes": p.stat().st_size if p.is_file() else None}
             for name, p in paths.items()}
    for name, p in (("base_dense", KD.npz_path(K.INDEX_JSON)),
                    ("hybrid_dense", KD.npz_path(K.hybrid_index_path()))):
        files[name] = {"path": str(p), "sha256": sha(p), "bytes": p.stat().st_size if p.is_file() else None}
    modules = {name: {"path": m.__file__, "sha256": sha(m.__file__)}
               for name, m in (("kb", K), ("kb_dense", KD), ("kb_provenance", KP),
                               ("kb_selector", KS), ("eval_common", E),
                               ("producer", sys.modules[__name__]))}
    return {"files": files, "modules": modules,
            "models": {"embed": KD.EMBED_MODEL, "embed_rev": KD.EMBED_REV,
                       "rerank": KD.RERANK_MODEL, "rerank_rev": KD.RERANK_REV}}


def source_audit():
    corpus = K.load_map()
    registry = S.load_registry()
    by_source = {s["source_id"]: s for s in registry["sources"]}
    entry = next(e for e in corpus["entries"]
                 if e["path"].endswith("热血足球联盟_必杀全清单.md"))
    resolved = K._citation_authority(entry, corpus, by_source)
    s1 = ROOT / "_工具脚本/taspipe/游戏包/来源库/取证/1ang_热血足球联盟图文攻略_20261118.md"
    s3 = ROOT / "_工具脚本/taspipe/游戏包/来源库/取证/sohu_必杀最强小辫子_20261118.md"
    s8 = ROOT / "_工具脚本/taspipe/游戏包/来源库/取证/urawaza_FC热血足球_20261118.md"
    texts = {name: p.read_text(encoding="utf-8") for name, p in
             (("S1", s1), ("S3", s3), ("S8", s8))}
    return {"entry_authority": entry["authority"], "aliases": resolved,
            "S1_has_23_total": "23 种" in texts["S1"] or "23种" in texts["S1"],
            "S3_has_23_total": "23 种" in texts["S3"] or "23种" in texts["S3"],
            "S1_has_hissatsu_ok": "ひっさつOK" in texts["S1"] or "ひっさつＯＫ" in texts["S1"],
            "S8_has_hissatsu_ok": "ひっさつOK" in texts["S8"] or "ひっさつＯＫ" in texts["S8"],
            "super_list_line257": (ROOT / "_工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md")
            .read_text(encoding="utf-8").splitlines()[256]}


def combine(base_path, hybrid_path, out):
    base = json.loads(base_path.read_text(encoding="utf-8"))
    hybrid = json.loads(hybrid_path.read_text(encoding="utf-8"))
    old = json.loads((OLD / "regression_after_strict_citation_fix_20261124.json")
                     .read_text(encoding="utf-8"))
    old_rows = {r["id"]: r for r in old["rows"]}
    rows = []
    for b in base["rows"]:
        h = next(r for r in hybrid["rows"] if r["id"] == b["id"])
        arms = {**b["arms"], **h["arms"]}
        rows.append({**b, "arms": arms})
    default_changes = []
    for r in rows:
        if r["id"] not in old_rows:
            continue
        o = old_rows[r["id"]]
        now = r["arms"]["base_default"]
        if o["base_status"] != now["status"] or o["base_selected"] != [x["locator"] for x in now["selected"]]:
            default_changes.append(r["id"])
    source = source_audit()
    checks = {
        "old_default_unchanged": not default_changes,
        "old_default_changed_ids": default_changes,
        "base_isolation": base["isolation"]["ok"],
        "hybrid_isolation": hybrid["isolation"]["ok"],
        "question_fingerprints_match_between_arms": sha(P1 / "p2_questions_ext.json") ==
            base["fingerprints"]["files"]["questions"]["sha256"] ==
            hybrid["fingerprints"]["files"]["questions"]["sha256"],
        "probe_fingerprints_match_between_arms": sha(P1 / "probe_questions_ext.json") ==
            base["fingerprints"]["files"]["probes"]["sha256"] ==
            hybrid["fingerprints"]["files"]["probes"]["sha256"],
        "x23_frozen_label_preserved": next(r for r in rows if r["id"] == "X23")["frozen_kind"] ==
            "insufficient_source",
        "q18_source_claim_corrected": not source["S1_has_hissatsu_ok"] and source["S8_has_hissatsu_ok"],
    }
    for qid in ("Q01", "Q02", "Q03", "Q04", "Q05", "Q18", "X03", "X04", "X23"):
        r = next(x for x in rows if x["id"] == qid)
        checks[f"{qid}_default_pass_strict_refused"] = (
            r["arms"]["base_default"]["status"] == "pass" and
            r["arms"]["base_strict"]["status"] != "pass" and
            not r["arms"]["base_strict"]["selected"])
    x21 = next(x for x in rows if x["id"] == "X21")
    checks["X21_authoritative_control_still_passes"] = all(
        x21["arms"][a]["status"] == "pass" for a in ("base_default", "base_strict"))
    grades = {arm: [r["arms"][arm]["grade_v2"] for r in rows if r["id"] in old_rows]
              for arm in ARMS}
    summaries = {arm: E.summarize_v2(g) for arm, g in grades.items()}
    result = {"schema": "kb_source_inheritance_regression_v1",
              "taken_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "production_defaults": base["production_defaults"],
              "fingerprints": base["fingerprints"], "source_audit": source,
              "historical_annotation_conflicts": CONFLICTS, "checks": checks,
              "all_checks_ok": all(v for k, v in checks.items() if isinstance(v, bool)),
              "summary_v2": summaries, "rows": rows,
              "old_delivery": {"path": str(OLD),
                               "regression_sha256": sha(OLD / "regression_after_strict_citation_fix_20261124.json"),
                               "manifest_sha256": sha(OLD / "final_manifest_after_strict_citation_fix_20261124.json"),
                               "inventory_sha256": sha(OLD / "artifact_inventory_after_strict_citation_fix_20261124.json")}}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render(result, out.with_suffix(".md"))
    print(json.dumps({"all_checks_ok": result["all_checks_ok"], "checks": checks,
                      "summary_v2": {a: {"ok": s["ok"], "failed_ids": s["failed_ids"]}
                                     for a, s in summaries.items()}},
                     ensure_ascii=False, indent=2), flush=True)
    return 0 if result["all_checks_ok"] else 1


def render(d, out):
    lines = ["# 来源继承修正生产回归 · 2026-11-24", "",
             f"- 生成时间：{d['taken_at']}",
             "- 生产默认不变：`top_window=3`、`fragment_policy=None`、`fact_selector=None`。",
             "- 题集与探针冻结标签未改；X23 仍为 `insufficient_source`。",
             f"- 全部确定性检查：`{d['all_checks_ok']}`", "",
             "## 26 题 v2 严格出证", "",
             "| 臂 | 通过 | 失败题 |", "|---|---|---|"]
    for arm, s in d["summary_v2"].items():
        lines.append(f"| {arm} | {s['ok']}/26 | {', '.join(s['failed_ids']) or '无'} |")
    lines += ["", "## 来源事实核对", "",
              f"- 《必杀全清单》整件资格：`{d['source_audit']['entry_authority']}`。",
              f"- S1 含 23 种总量：`{d['source_audit']['S1_has_23_total']}`；"
              f"S3 含 23 种总量：`{d['source_audit']['S3_has_23_total']}`。",
              f"- S1 含ひっさつOK：`{d['source_audit']['S1_has_hissatsu_ok']}`；"
              f"S8 含ひっさつＯＫ：`{d['source_audit']['S8_has_hissatsu_ok']}`。",
              "- Q18 原文已改为分别记载 S1 音效与 S8 得分框签名，不再声称两源一致。", "",
              "## 历史标注冲突（不改冻结判据）", ""]
    for qid, reason in d["historical_annotation_conflicts"].items():
        lines.append(f"- {qid}：{reason}")
    lines += ["", "## 重点逐臂", "",
              "| ID | 冻结标签 | base 默认 | base strict | hybrid 默认 | hybrid strict |",
              "|---|---|---|---|---|---|"]
    for r in d["rows"]:
        if r["id"] not in CONFLICTS and r["id"] != "X21":
            continue
        lines.append(f"| {r['id']} | {r['frozen_tier'] or r['frozen_kind']} | " +
                     " | ".join(r["arms"][a]["status"] for a in ARMS) + " |")
    lines += ["", "## 旧交付保护", "",
              "- 旧 strict 交付目录只读；本回归逐格对比旧默认臂状态与出证定位。",
              f"- 旧默认臂变化：`{d['checks']['old_default_changed_ids']}`。", ""]
    out.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", nargs="+", choices=ARMS)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--combine", nargs=2, type=Path, metavar=("BASE_JSON", "HYBRID_JSON"))
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.combine:
        if not args.out:
            ap.error("--combine 需要 --out")
        return combine(*args.combine, args.out)
    if not args.arms or not args.out:
        ap.error("需要 --arms 与 --out")
    return run(args.arms, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
