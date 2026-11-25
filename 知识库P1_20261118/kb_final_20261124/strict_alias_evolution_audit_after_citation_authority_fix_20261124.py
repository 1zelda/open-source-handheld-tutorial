# -*- coding: utf-8 -*-
"""strict三代探针演变审计：冻结标签不变，只比较生产结果。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124"
P2 = ROOT / "知识库P1_20261118"
JSON_PATH = OUT / "strict_alias_evolution_audit_after_citation_authority_fix_20261124.json"
MD_PATH = OUT / "strict_alias_evolution_audit_after_citation_authority_fix_20261124.md"
GENERATIONS = [
    ("旧strict_裸编号连坐", "selector_sweep_after_provenance.json"),
    ("临时strict_未知与已知编号全部不降级", "selector_sweep_after_strict_citation_fix_20261124.json"),
    ("当前strict_来源别名资格", "selector_sweep_after_citation_authority_fix_20261124.json"),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def map_by(items, key="id"):
    return {item[key]: item for item in items}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    data = {name: json.loads((OUT / filename).read_text(encoding="utf-8"))
            for name, filename in GENERATIONS}
    old_name, temp_name, current_name = [n for n, _ in GENERATIONS]
    all_ids = sorted(set().union(*(set(map_by(d["probes_ext"])) | set(map_by(d["probes_base"]))
                                    for d in data.values())))
    rows = []
    for pid in all_ids:
        row = {"id": pid}
        for name in data:
            ext = map_by(data[name]["probes_ext"]).get(pid)
            base = map_by(data[name]["probes_base"]).get(pid)
            source = ext or base
            row.update({f"{name}_kind": source.get("kind"),
                        f"{name}_class": (source or {}).get("classes", {}).get("strict_fragments")})
        rows.append(row)
    transitions = {}
    for a, b, label in ((old_name, temp_name, "旧strict→临时"),
                        (temp_name, current_name, "临时→当前"),
                        (old_name, current_name, "旧strict→当前")):
        transitions[label] = [
            {"id": r["id"], "from": r[f"{a}_class"], "to": r[f"{b}_class"],
             "kind": r[f"{current_name}_kind"]}
            for r in rows if r[f"{a}_class"] != r[f"{b}_class"]
        ]
    summaries = {}
    for name, d in data.items():
        s = d["summary"]["modes"]["strict_fragments"]
        summaries[name] = {
            "source": dict(GENERATIONS)[name], "source_sha256": sha(OUT / dict(GENERATIONS)[name]),
            "index": d["index"], "taken_at": d["taken_at"], "v2_ok": s["v2_ok"],
            "classes": s["classes"], "wrong_evidence": s["wrong_evidence"],
            "newly_passed": s["newly_passed"], "intercepted": s["intercepted"],
        }
    current = data[current_name]
    current_qs = map_by(current["questions"])
    q23 = map_by(current["probes_ext"])["X23"]
    frozen = {
        "p2_questions_sha256": sha(P2 / "p2_questions_ext.json"),
        "probe_questions_sha256": sha(P2 / "probe_questions_ext.json"),
        "probe_questions_base_sha256": sha(P2 / "probe_questions.json"),
        "x23_kind": q23["kind"], "x23_note": next(q for q in json.loads(
            (P2 / "probe_questions_ext.json").read_text(encoding="utf-8"))["questions"]
            if q["id"] == "X23")["kind_note"],
        "x23_current_class": q23["classes"]["strict_fragments"],
    }
    q_rows = []
    for qid, qr in current_qs.items():
        q_rows.append({"id": qid, "q": qr["q"], "tier": qr["tier"],
                       "base_status": qr["base"]["status"],
                       "strict_status": qr["variants"]["strict_fragments"]["status"],
                       "class": qr["classes"]["strict_fragments"],
                       "base_selected": qr["base"]["selected_locator"],
                       "strict_selected": qr["variants"]["strict_fragments"]["selected_locator"]})
    payload = {
        "schema": "strict_alias_evolution_audit_after_citation_authority_fix_v1",
        "generations": summaries, "frozen_annotations": frozen,
        "probe_transitions": transitions, "probe_rows": rows,
        "current_strict_question_regressions": [r for r in q_rows if r["class"] == "regressed"],
        "interpretation": [
            "旧strict把所有裸S编号连坐降级，误拦正常汇总件；X03/X04/X23是其中可定位的误拦样例。",
            "临时方案取消裸编号连坐后恢复25/26，但也把已知二手S1升成权威，X23重新放行。",
            "当前方案按chunk.citation_authority解析来源别名：未知S99不连坐，已知二手/未核验/版本不符别名继承reference_only，本机实测标题可解除继承。",
            "因此当前strict回到21/26；5题回归是已知二手别名被正确拦截的代价，不是通过改金标得到的假通过。",
            "X23冻结标签为insufficient_source，当前strict=intercepted，与冻结语义一致；临时strict=still_passed属于假放行。",
        ],
    }
    payload["ok"] = (
        summaries[old_name]["v2_ok"] == 22 and summaries[temp_name]["v2_ok"] == 25
        and summaries[current_name]["v2_ok"] == 21
        and set(summaries[current_name]["intercepted"])
        == {"X03", "X04", "X05", "X17", "X19", "X20", "X22", "X23", "X30"}
        and q23["classes"]["strict_fragments"] == "intercepted"
        and not summaries[current_name]["newly_passed"]
        and not summaries[current_name]["wrong_evidence"])
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    L = ["# strict 来源别名资格演变审计", "", f"- 冻结金标 SHA：P2 `{frozen['p2_questions_sha256']}`", ""]
    L += ["| 代 | strict v2 | 修好 | 打坏 | 索引 |", "|---|---|---|---|---|"]
    for name in data:
        s = summaries[name]
        L.append(f"| {name} | {s['v2_ok']}/26 | {s['classes'].get('fixed', 0)} | "
                 f"{s['classes'].get('regressed', 0)} | {s['index']['chunks']}块/{s['index']['sha16']} |")
    L += ["", "## 探针状态变化", "", "| 探针 | 类型 | 旧strict | 临时 | 当前 |", "|---|---|---|---|---|"]
    for r in rows:
        if len({r[f"{name}_class"] for name in data}) > 1:
            L.append(f"| {r['id']} | {r[f'{current_name}_kind']} | {r[f'{old_name}_class']} | "
                     f"{r[f'{temp_name}_class']} | {r[f'{current_name}_class']} |")
    L += ["", "## 当前 strict 的 5 题回归", "", "| 题 | 默认 | strict | 默认出证 | strict出证 |",
          "|---|---|---|---|---|"]
    for r in payload["current_strict_question_regressions"]:
        L.append(f"| {r['id']} | {r['base_status']} | {r['strict_status']} | "
                 f"{r['base_selected']} | {r['strict_selected'] or '无'} |")
    L += ["", "## 结论", ""] + [f"- {x}" for x in payload["interpretation"]]
    L += ["", f"- 本次审计 `ok={payload['ok']}`。"]
    MD_PATH.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(JSON_PATH), "md": str(MD_PATH), "ok": payload["ok"],
                      "v2": {k: v["v2_ok"] for k, v in summaries.items()},
                      "current_intercepted": summaries[current_name]["intercepted"]},
                     ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
