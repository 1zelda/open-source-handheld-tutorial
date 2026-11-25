# -*- coding: utf-8 -*-
"""核对 strict 裸引用修正前后的探针变化，并保留冻结标注冲突。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124"
PROBES = ROOT / "知识库P1_20261118/probe_questions_ext.json"
OLD_SWEEP = OUT / "selector_sweep_after_provenance.json"
NEW_SWEEP = OUT / "selector_sweep_after_strict_citation_fix_20261124.json"
REGRESSION = OUT / "regression_after_strict_citation_fix_20261124.json"
JSON_PATH = OUT / "strict_probe_change_audit_after_citation_fix_20261124.json"
MD_PATH = OUT / "strict_probe_change_audit_after_citation_fix_20261124.md"

sys.path.insert(0, str(ROOT / "_工具脚本"))
from taspipe import kb as K
from taspipe import kb_blind_eval as BE
from taspipe import kb_provenance as KP


def sha(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def state():
    return {str(p): {"exists": p.is_file(), "size": p.stat().st_size if p.is_file() else None,
                     "mtime_ns": p.stat().st_mtime_ns if p.is_file() else None, "sha256": sha(p)}
            for p in BE._protected_paths()}


def row_by_id(rows, artifact_id):
    return next(row for row in rows if row["id"] == artifact_id)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    old = json.loads(OLD_SWEEP.read_text(encoding="utf-8"))
    new = json.loads(NEW_SWEEP.read_text(encoding="utf-8"))
    regression = json.loads(REGRESSION.read_text(encoding="utf-8"))
    probes = json.loads(PROBES.read_text(encoding="utf-8"))
    if isinstance(probes, dict):
        probes = probes.get("questions", probes.get("probes", []))

    old_ext = {row["id"]: row for row in old["probes_ext"]}
    new_ext = {row["id"]: row for row in new["probes_ext"]}
    frozen_ext = {row["id"]: row for row in probes}
    restored = [row_id for row_id in new_ext
                if old_ext[row_id]["variants"]["strict_fragments"]["status"] != "pass"
                and new_ext[row_id]["variants"]["strict_fragments"]["status"] == "pass"]
    newly_passed = [row_id for row_id in new_ext
                    if new_ext[row_id]["base_status"] != "pass"
                    and new_ext[row_id]["variants"]["strict_fragments"]["status"] == "pass"]

    before = state()
    details = []
    for row_id in ("X03", "X04", "X23"):
        frozen = frozen_ext[row_id]
        filters = frozen.get("filters", {})
        params = dict(game=filters.get("game"), revision=filters.get("revision"),
                      platform=filters.get("platform"), topk=30, top_window=3)
        base = K.query(frozen["q"], **params)
        strict = K.query(frozen["q"], fragment_policy="strict", **params)
        selected = []
        for hit in strict.get("selected_evidence") or []:
            selected.append({
                "chunk_id": hit.get("chunk_id"),
                "locator": hit.get("locator"),
                "heading": hit.get("heading"),
                "fragment_provenance": hit.get("fragment_provenance"),
            })
        details.append({
            "id": row_id,
            "question": frozen["q"],
            "frozen_kind": frozen.get("kind"),
            "frozen_kind_v1": frozen.get("kind_v1"),
            "frozen_kind_note": frozen.get("kind_note"),
            "frozen_evidence": frozen.get("evidence"),
            "old_strict_status": old_ext[row_id]["variants"]["strict_fragments"]["status"],
            "old_strict_class": old_ext[row_id]["variants"]["strict_fragments"]["class"],
            "current_base_status": base["status"],
            "current_strict_status": strict["status"],
            "current_strict_class": new_ext[row_id]["classes"]["strict_fragments"],
            "new_pass_vs_current_base": base["status"] != "pass" and strict["status"] == "pass",
            "selected_evidence": selected,
        })
    after = state()
    changed = [path for path in before if before[path] != after[path]]

    q_rows = []
    for qid in ("Q02", "Q03", "Q04", "Q05"):
        row = row_by_id(regression["rows"], qid)
        q_rows.append({
            "id": qid,
            "base_status": row["base_status"],
            "strict_status": row["strict_status"],
            "base_selected": row["base_selected"],
            "strict_selected": row["strict_selected"],
            "restored_gold_chunk": row["base_selected"] == row["strict_selected"] and bool(row["strict_selected"]),
        })

    result = {
        "schema": "kb_strict_probe_change_audit_after_citation_fix_v1",
        "index": new["index"],
        "code": new["code"],
        "production_defaults": regression["production_defaults"],
        "probe_change_summary": {
            "old_strict_v2_ok": old["summary"]["modes"]["strict_fragments"]["v2_ok"],
            "current_strict_v2_ok": new["summary"]["modes"]["strict_fragments"]["v2_ok"],
            "restored_vs_old_strict": restored,
            "newly_passed_vs_current_base": newly_passed,
            "current_strict_intercepted": new["summary"]["modes"]["strict_fragments"]["intercepted"],
            "frozen_labels_modified": False,
        },
        "restored_questions": q_rows,
        "probe_details": details,
        "x23_disposition": {
            "classification": "frozen_annotation_conflict",
            "decision": "retain_frozen_label_and_keep_strict_shadow_only",
            "reason": (
                "冻结说明把 S1 直接视为二手 reference_only；修正后的规则只把显式转述、"
                "参考段、待核段与撤回段降级，裸来源编号本身不构成二手证据。"
                "X23 与 Q02-Q05 同属该规则变化，不能单独改标签凑满分。"
            ),
            "production_impact": "none; fragment_policy=None remains the production default",
            "follow_up": "如需重审 S1 文件级权威，应统一审计 corpus_map 与来源资格，不得只针对 X23 加特例。",
        },
        "isolation": {"ok": not changed, "changed_paths": changed},
    }
    JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# strict 裸引用修正：探针变化审计（2026-11-24）",
        "",
        f"- 索引：{result['index']['chunks']} 块，`{result['index']['sha16']}…`。",
        "- 生产默认未变：`top_window=3`、`fragment_policy=None`、`fact_selector=None`。",
        "- 冻结探针标签未修改；本件只登记口径变化与冲突，不把历史标签偷偷改成通过。",
        "",
        "## 总结",
        "",
        f"- strict `grade_v2`：{result['probe_change_summary']['old_strict_v2_ok']}/26 → "
        f"{result['probe_change_summary']['current_strict_v2_ok']}/26。",
        f"- 相对旧 strict 恢复：{', '.join(restored)}。",
        f"- 相对当前默认臂新增放行：{', '.join(newly_passed) or '无'}。",
        f"- 当前 strict 仍拦截：{', '.join(result['probe_change_summary']['current_strict_intercepted'])}。",
        "",
        "## Q02–Q05：合法题恢复且金标未换",
        "",
        "| ID | 默认臂 | strict | 金标一致 |",
        "|---|---|---|---|",
    ]
    for row in q_rows:
        lines.append(f"| {row['id']} | {row['base_status']} | {row['strict_status']} | "
                     f"{'是' if row['restored_gold_chunk'] else '否'} |")
    lines.extend([
        "",
        "## X03 / X04 / X23 逐臂对照",
        "",
        "| ID | 冻结 kind | 旧 strict | 当前默认 | 当前 strict | 相对默认新增放行 |",
        "|---|---|---|---|---|---|",
    ])
    for row in details:
        lines.append(f"| {row['id']} | {row['frozen_kind']} | {row['old_strict_status']} | "
                     f"{row['current_base_status']} | {row['current_strict_status']} | "
                     f"{'是' if row['new_pass_vs_current_base'] else '否'} |")
    lines.extend([
        "",
        "## X23 的处置",
        "",
        result["x23_disposition"]["reason"],
        "",
        f"- 判定：`{result['x23_disposition']['classification']}`。",
        f"- 动作：`{result['x23_disposition']['decision']}`。",
        f"- 生产影响：{result['x23_disposition']['production_impact']}。",
        f"- 后续：{result['x23_disposition']['follow_up']}",
        "",
        "## 隔离",
        "",
        f"- 真实状态隔离：{'PASS' if result['isolation']['ok'] else 'FAIL'}；"
        f"变化路径 {len(result['isolation']['changed_paths'])}。",
        "",
    ])
    MD_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "json": str(JSON_PATH), "markdown": str(MD_PATH),
        "restored_vs_old_strict": restored,
        "newly_passed_vs_current_base": newly_passed,
        "isolation": result["isolation"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["isolation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
