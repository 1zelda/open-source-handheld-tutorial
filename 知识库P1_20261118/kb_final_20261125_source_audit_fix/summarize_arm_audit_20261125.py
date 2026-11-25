# -*- coding: utf-8 -*-
"""汇总四臂逐题审计，单列错误出证与历史标注冲突。"""
import json
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261125_source_audit_fix"
ARMS = ("base_default", "base_strict", "hybrid_default", "hybrid_strict")


def main():
    merged = json.loads((OUT / "regression_source_inheritance_20261125.json")
                        .read_text(encoding="utf-8"))
    isolation = json.loads((OUT / "dense_isolation_verification_20261125.json")
                           .read_text(encoding="utf-8"))
    base_rows = [r for r in merged["rows"] if not r["id"].startswith("X")]
    probe_rows = [r for r in merged["rows"] if r["id"].startswith("X")]
    summaries = {}
    details = []
    for arm in ARMS:
        arm_rows = [r["arms"][arm] for r in base_rows]
        summaries[arm] = {
            "status_pass": sum(r["status"] == "pass" for r in arm_rows),
            "status_inconclusive": sum(r["status"] == "inconclusive" for r in arm_rows),
            "status_miss": sum(r["status"] == "miss" for r in arm_rows),
            "v2_ok": sum(r["grade_v2"]["ok"] for r in arm_rows),
            "v2_failed_ids": [r["id"] for r, a in zip(base_rows, arm_rows)
                              if not a["grade_v2"]["ok"]],
            "wrong_evidence_ids": [r["id"] for r, a in zip(base_rows, arm_rows)
                                   if a["grade_v2"].get("wrong_evidence")],
            "missed_answer_ids": [r["id"] for r, a in zip(base_rows, arm_rows)
                                  if a["grade_v2"].get("missed_answer")],
        }
    for row in base_rows:
        for arm in ARMS:
            a = row["arms"][arm]
            g = a["grade_v2"]
            if g.get("wrong_evidence") or g.get("missed_answer"):
                details.append({
                    "id": row["id"], "arm": arm, "question": row["q"],
                    "frozen_tier": row["frozen_tier"], "status": a["status"],
                    "v2_ok": g["ok"], "correct_evidence": g.get("correct_evidence"),
                    "wrong_evidence": g.get("wrong_evidence"),
                    "missed_answer": g.get("missed_answer"),
                    "selected": a["selected"], "condition": a.get("condition"),
                })
    result = {
        "schema": "kb_source_inheritance_arm_audit_v1",
        "production_defaults": merged["production_defaults"],
        "summaries": summaries,
        "details": details,
        "probes": [{
            "id": r["id"], "question": r["q"],
            "frozen_tier": r["frozen_tier"], "frozen_kind": r["frozen_kind"],
            "arms": {arm: {
                "status": r["arms"][arm]["status"],
                "selected": r["arms"][arm]["selected"],
                "grade": r["arms"][arm].get("grade_v2"),
            } for arm in ARMS},
        } for r in probe_rows],
        "source_audit": merged["source_audit"],
        "historical_annotation_conflicts": merged["historical_annotation_conflicts"],
        "x23_frozen_label_preserved": merged["checks"]["x23_frozen_label_preserved"],
        "old_default_unchanged": merged["checks"]["old_default_unchanged"],
        "dense_isolation_ok": isolation["all_checks_ok"],
    }
    target = OUT / "source_inheritance_arm_audit_20261125.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 来源继承修正逐臂审计 · 2026-11-24", "",
        "- 冻结金标未改；X23 保留 `insufficient_source`。",
        "- strict 仍为显式影子臂；默认 `fragment_policy=None`。",
        "- hybrid 仅用于探针，未获批准投产；稠密件已移出生产自动选臂路径。",
        "", "## 四臂汇总", "",
        "| 臂 | status=pass | status=inconclusive | status=miss | v2 通过 | v2 失败 | 错误出证 | 漏答 |",
        "|---|---:|---:|---:|---:|---|---|---|",
    ]
    for arm, s in summaries.items():
        lines.append(f"| {arm} | {s['status_pass']} | {s['status_inconclusive']} | "
                     f"{s['status_miss']} | {s['v2_ok']}/26 | "
                     f"{', '.join(s['v2_failed_ids']) or '无'} | "
                     f"{', '.join(s['wrong_evidence_ids']) or '无'} | "
                     f"{', '.join(s['missed_answer_ids']) or '无'} |")
    lines += [
        "", "v2 的 `gold_in_topk` 档只要求金标进入候选并检查召回，不能把 `status=pass` 或正确出证混为一谈；Q04 即为 strict 状态 `inconclusive` 但 v2 仍通过的例子。",
        "", "## 错误出证与漏答明细", "",
        "| 题 | 臂 | 状态 | v2 | 正确证据 | 错误证据 | 漏答 | 选中定位 |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    for d in details:
        locs = "; ".join(x.get("locator") or "-" for x in d["selected"]) or "无"
        lines.append(f"| {d['id']} | {d['arm']} | {d['status']} | {d['v2_ok']} | "
                     f"{d['correct_evidence']} | {d['wrong_evidence']} | {d['missed_answer']} | {locs} |")
    lines += [
        "", "## 重点探针", "",
        "| ID | 冻结标签 | base 默认 | base strict | hybrid 默认 | hybrid strict |",
        "|---|---|---|---|---|---|",
    ]
    for p in result["probes"]:
        lines.append(f"| {p['id']} | {p['frozen_kind'] or p['frozen_tier']} | "
                     + " | ".join(p["arms"][arm]["status"] for arm in ARMS) + " |")
    lines += [
        "", "## 来源事实", "",
        f"- 《必杀全清单》整件仍为 `{merged['source_audit']['entry_authority']}`；S1/S3/S8 别名均解析为 `reference_only`。",
        f"- S1 含 23 种总量：`{merged['source_audit']['S1_has_23_total']}`；S3：`{merged['source_audit']['S3_has_23_total']}`。",
        f"- S1 含 `ひっさつOK`：`{merged['source_audit']['S1_has_hissatsu_ok']}`；S8：`{merged['source_audit']['S8_has_hissatsu_ok']}`。",
        "- Q18 源文已改为分别记载 S1 发动音效与 S8 得分框签名；不声称两源一致。",
        "", "## 判定", "",
        "- 基础默认臂 v2 26/26，且相对旧交付的状态与出证定位逐格不变。",
        "- 基础 strict v2 21/26，撤销 Q01/Q02/Q03/Q05/Q18 的二手假放行；不是为评分改金标。",
        "- hybrid 默认 22/26、strict 19/26；Q02/Q08/Q10/Q18 漂移与全部错误出证逐题入账，错误出证集合以汇总表为准。",
        "- X23 的 legacy pass 归为文件级权威洗白；冻结标签不改。",
        "",
    ]
    md = OUT / "source_inheritance_arm_audit_20261125.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"json": str(target), "md": str(md), "summaries": summaries,
                      "detail_count": len(details), "probe_count": len(result["probes"])},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
