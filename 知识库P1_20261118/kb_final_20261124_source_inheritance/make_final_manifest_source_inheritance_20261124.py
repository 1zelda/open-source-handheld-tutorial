# -*- coding: utf-8 -*-
"""生成来源继承修正最终总指纹；仅校验本轮串行产物，不覆盖旧交付。"""
import hashlib
import json
import re
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124_source_inheritance"
P1 = ROOT / "知识库P1_20261118"
KB_DIR = ROOT / "_工具脚本/taspipe/游戏包/知识库"
REPORT = ROOT / "知识库改进优化指导_2026-11-24_来源继承修正回填.md"
PRIOR = {
    "知识库改进优化指导_2026-11-24_strict片段修正回填.md": "66c1bdeb0f3cde492751cbfbea237c6ff3083eb4218927481b5a833139635657",
    "知识库P1_20261118/kb_final_20261124/final_manifest_after_strict_citation_fix_20261124.json": "7855b800e0862ce551e3aeb211f362c931f27ba067869f4de3b532f30ba2d934",
    "知识库P1_20261118/kb_final_20261124/artifact_inventory_after_strict_citation_fix_20261124.json": "e728670c4aea20544a0bc719432435b1d7efc34bbce52e80d88ea99e8ac8b9fd",
}


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def info(path, **extra):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), **extra}


def gate(name, pattern):
    text = (OUT / name).read_text(encoding="utf-8")
    match = re.search(pattern, text)
    assert match, f"缺少闸门结果：{name}"
    passed, total = map(int, match.groups())
    return {"passed": passed, "total": total, "ok": passed == total,
            "log": info(OUT / name)}


def main():
    base_path = KB_DIR / "index.json"
    hybrid_path = KB_DIR / "index_hybrid.json"
    base = json.loads(base_path.read_text(encoding="utf-8"))
    hybrid = json.loads(hybrid_path.read_text(encoding="utf-8"))
    regression = load("regression_source_inheritance_20261124.json")
    audit = load("source_inheritance_arm_audit_20261124.json")
    selector = load("selector_source_inheritance_20261124.json")
    blind = load("blind_eval_source_inheritance_20261124.json")
    heldout = load("heldout_eval_source_inheritance_20261124.json")
    full = load("full_domain_eval_source_inheritance_20261124.json")
    isolation = load("dense_isolation_verification_20261124.json")
    kb_audit = load("kb_audit_base_source_inheritance_20261124.json")
    hybrid_audit = load("kb_audit_hybrid_source_inheritance_20261124.json")
    sources_audit = load("sources_audit_source_inheritance_20261124.json")
    index_sha = hashlib.sha256(base_path.read_bytes()).hexdigest()
    hybrid_sha = hashlib.sha256(hybrid_path.read_bytes()).hexdigest()

    assert regression["all_checks_ok"] is True
    assert regression["checks"]["old_default_unchanged"] is True
    assert regression["production_defaults"] == {"top_window": 3, "fragment_policy": None, "fact_selector": None}
    assert regression["summary_v2"]["base_default"]["ok"] == 26
    assert regression["summary_v2"]["base_strict"]["failed_ids"] == ["Q01", "Q02", "Q03", "Q05", "Q18"]
    assert audit["old_default_unchanged"] is True
    assert audit["x23_frozen_label_preserved"] is True
    assert audit["dense_isolation_ok"] is True
    assert selector["summary"]["base_v2_ok"] == 26
    assert selector["summary"]["modes"]["strict_fragments"]["v2_ok"] == 21
    assert selector["summary"]["modes"]["strict_fragments"]["newly_passed"] == []
    assert all(mode["wrong_evidence"] == [] for mode in selector["summary"]["modes"].values())
    for data in (blind, heldout, full):
        assert data["summary"]["ok"] == data["summary"]["total"]
    assert blind["summary"]["total"] == 26
    assert heldout["summary"]["total"] == full["summary"]["total"] == 16
    assert blind["index"]["sha256"] == heldout["index"]["sha256"] == full["index_sha256"] == index_sha
    assert blind["isolation"]["ok"] and heldout["isolation"]["ok"]
    assert isolation["all_checks_ok"] is True
    assert isolation["auto_index_is_base"] is True
    assert isolation["base_queries_unchanged"] is True
    assert isolation["old_delivery_hashes_ok"] is True
    assert kb_audit["counts"]["fail"] == hybrid_audit["counts"]["fail"] == 0
    assert sources_audit["counts"] == {"pass": 7, "fail": 1, "inconclusive": 1,
                                      "sources": 90, "packs": 23,
                                      "elements_checked": 87, "elements_supported": 87}
    wild = next(check for check in sources_audit["checks"] if check["check_id"] == "no_wild_sources")
    assert wild["verdict"] == "fail" and wild["detail"] == [
        "gba_aria_of_sorrow_souls.showcase.json: 来源字段未知 ['evidence_report']"]
    assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
               for name, expected in PRIOR.items())

    gates = {
        "project_selftest": gate("selftest_source_inheritance_20261124.log", r"SELFTEST OK (\d+)/(\d+)"),
        "kb_selftest": gate("kb_selftest_source_inheritance_20261124.log", r"KB_SELFTEST OK (\d+)/(\d+)"),
        "cross_platform_selftest": gate("cross_platform_source_inheritance_20261124.log", r"CROSS_PLATFORM_SELFTEST OK (\d+)/(\d+)"),
        "topic_selftest": gate("topic_selftest_source_inheritance_20261124.log", r"自检合计\s*(\d+)\s*格：PASS\s*(\d+)\s*/\s*FAIL\s*0"),
    }
    assert all(item["ok"] for item in gates.values())
    topic = (OUT / "topic_selftest_source_inheritance_20261124.log").read_text(encoding="utf-8")
    assert all(f"PASS  T15{x}" in topic for x in "abcdefgh")

    report_text = REPORT.read_text(encoding="utf-8")
    for token in (index_sha, hybrid_sha, "26/26", "21/26", "insufficient_source",
                  "frozen_annotation_conflict", "draft_not_frozen",
                  "final_manifest_source_inheritance_20261124.json"):
        assert token in report_text, token

    manifest = {
        "schema": "kb_final_manifest_source_inheritance_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "来源资格继承统一修正；BM25 生产默认；strict 显式影子臂；稠密层未批准且已隔离；冻结标签未改；无外部生成或付费 API。",
        "production_unchanged": {"top_window": 3, "fragment_policy": None, "fact_selector": None,
                                 "strict_production_default": False, "dense_production_default": False,
                                 "megaman_route_enabled": False, "megaman_entries_indexed": 0,
                                 "commercial_rom_or_bios_ingested": False},
        "index": info(base_path, chunks=len(base["chunks"]), stats=base["stats"],
                      pipeline=base.get("pipeline"), built_at=base.get("built_at")),
        "hybrid_probe_index": info(hybrid_path, chunks=len(hybrid["chunks"]), stats=hybrid["stats"],
                                   pipeline=hybrid.get("pipeline"), production_approved=False),
        "corpus_map": info(KB_DIR / "corpus_map.json"),
        "source_registry": info(ROOT / "_工具脚本/taspipe/游戏包/来源库/sources.json"),
        "source_claim": info(ROOT / "_工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md"),
        "ledger": info(ROOT / "测试问题与闸门说明书.md", appended_section="53"),
        "code": {**blind["code"], "kb_provenance": info(ROOT / "_工具脚本/taspipe/kb_provenance.py"),
                 "kb_selftest_gates": info(ROOT / "_工具脚本/taspipe/kb_selftest_gates.py"),
                 "sources_audit": info(ROOT / "_工具脚本/taspipe/sources.py")},
        "evaluations": {
            "blind": {"passed": blind["summary"]["ok"], "total": blind["summary"]["total"],
                      "wrong_evidence_ids": blind["summary"]["wrong_evidence_ids"],
                      "missed_answer_ids": blind["summary"]["missed_answer_ids"],
                      "isolation_ok": blind["isolation"]["ok"], "rerun_after_ledger_append": True,
                      "artifact": info(OUT / "blind_eval_source_inheritance_20261124.json")},
            "heldout_blind": {"passed": heldout["summary"]["ok"], "total": heldout["summary"]["total"],
                              "wrong_evidence_ids": heldout["summary"]["wrong_evidence_ids"],
                              "isolation_ok": heldout["isolation"]["ok"], "rerun_after_ledger_append": True,
                              "artifact": info(OUT / "heldout_eval_source_inheritance_20261124.json")},
            "full_domain": {"passed": full["summary"]["ok"], "total": full["summary"]["total"],
                            "rerun_after_ledger_append": True,
                            "artifact": info(OUT / "full_domain_eval_source_inheritance_20261124.json")},
            "selector": {"base": selector["summary"]["base_v2_ok"],
                         "modes": {name: {key: value[key] for key in
                                          ("v2_ok", "wrong_evidence", "newly_passed", "intercepted")}
                                   for name, value in selector["summary"]["modes"].items()},
                         "artifact": info(OUT / "selector_source_inheritance_20261124.json")},
            "four_arm_audit": {"summaries": audit["summaries"],
                               "x23_frozen_label_preserved": audit["x23_frozen_label_preserved"],
                               "old_default_unchanged": audit["old_default_unchanged"],
                               "artifact": info(OUT / "source_inheritance_arm_audit_20261124.json")},
            "regression": {"all_checks_ok": regression["all_checks_ok"],
                           "checks": regression["checks"],
                           "historical_annotation_conflicts": regression["historical_annotation_conflicts"],
                           "artifact": info(OUT / "regression_source_inheritance_20261124.json")},
        },
        "gates": gates,
        "audits": {"base": {"status": kb_audit["status"], "counts": kb_audit["counts"],
                            "artifact": info(OUT / "kb_audit_base_source_inheritance_20261124.json")},
                   "hybrid": {"status": hybrid_audit["status"], "counts": hybrid_audit["counts"],
                              "artifact": info(OUT / "kb_audit_hybrid_source_inheritance_20261124.json")},
                   "sources": {"status": sources_audit["status"], "counts": sources_audit["counts"],
                               "artifact": info(OUT / "sources_audit_source_inheritance_20261124.json")}},
        "dense_isolation": isolation,
        "dense_probe_files": [info(path) for path in sorted((OUT / "dense_probe").glob("*.npz"))],
        "builds": {"base": info(OUT / "build_base_final_20261124.log"),
                   "hybrid": info(OUT / "build_hybrid_final_20261124.log"),
                   "dense_base": info(OUT / "dense_base_final_20261124.log"),
                   "dense_hybrid": info(OUT / "dense_hybrid_final_20261124.log")},
        "prior_delivery_unchanged": {"ok": True,
                                     "artifacts": {name: info(ROOT / name, expected_sha256=expected)
                                                   for name, expected in PRIOR.items()}},
        "open_items": {"unverified_versions": 6, "megaman1": "draft_not_frozen",
                       "dynamic_esports_records": 0, "real_user_query_samples": "insufficient",
                       "hybrid_production": "not approved", "strict_production": "not approved",
                       "sources_audit": "fail=1: gba_aria_of_sorrow_souls.showcase.json evidence_report 未登记"},
        "report_md": info(REPORT),
        "artifact_inventory": str(OUT / "artifact_inventory_source_inheritance_20261124.md"),
        "delivery_dir": str(OUT),
        "git": {"commit_created": False, "push_performed": False},
    }
    target = OUT / "final_manifest_source_inheritance_20261124.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(target), "base_chunks": len(base["chunks"]),
                      "base_sha256": index_sha, "hybrid_chunks": len(hybrid["chunks"]),
                      "hybrid_sha256": hybrid_sha, "gates": {k: v["passed"] for k, v in gates.items()},
                      "blind": blind["summary"]["ok"], "heldout": heldout["summary"]["ok"],
                      "full_domain": full["summary"]["ok"], "all_checks_ok": True},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
