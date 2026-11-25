# -*- coding: utf-8 -*-
"""生成来源审计修正最终总指纹；校验本轮串行产物，不覆盖旧交付。"""
import hashlib
import json
import re
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261125_source_audit_fix"
KB_DIR = ROOT / "_工具脚本/taspipe/游戏包/知识库"
REPORT = ROOT / "知识库改进优化指导_2026-11-25_来源审计修正回填.md"
PRIOR = {
    "知识库改进优化指导_2026-11-24_strict片段修正回填.md": "66c1bdeb0f3cde492751cbfbea237c6ff3083eb4218927481b5a833139635657",
    "知识库P1_20261118/kb_final_20261124/final_manifest_after_strict_citation_fix_20261124.json": "7855b800e0862ce551e3aeb211f362c931f27ba067869f4de3b532f30ba2d934",
    "知识库P1_20261118/kb_final_20261124/artifact_inventory_after_strict_citation_fix_20261124.json": "e728670c4aea20544a0bc719432435b1d7efc34bbce52e80d88ea99e8ac8b9fd",
    "知识库改进优化指导_2026-11-24_来源继承修正回填.md": "ca1894547caf36f7f53a0c7ee26703823b89e856007d064b4e993806710cf728",
    "知识库P1_20261118/kb_final_20261124_source_inheritance/final_manifest_source_inheritance_20261124.json": "7bbcce947e1fe0afdeb90836eecbe52390090e284ada8516d6897ff69ce8a4d7",
    "知识库P1_20261118/kb_final_20261124_source_inheritance/artifact_inventory_source_inheritance_20261124.json": "256484703f4cf1cba8df3163c025d01e175aa1c4b901a7f98e0a912a56d3a5c9",
}
DENSE_EXPECTED = {
    "embeddings_fe56dc542741.npz": "887e75623662c8c3d90b6bfbb6d70c7b119254e69e29f191208cf6c6c8c0f69c",
    "embeddings_fa3c4bfe7788.npz": "faf874ec71c00979975483ded68cf0adba3cacda800e9b820a2fe581a452b189",
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
    assert passed == total, name
    return {"passed": passed, "total": total, "ok": True, "log": info(OUT / name)}


def main():
    base_path = KB_DIR / "index.json"
    hybrid_path = KB_DIR / "index_hybrid.json"
    base = json.loads(base_path.read_text(encoding="utf-8"))
    hybrid = json.loads(hybrid_path.read_text(encoding="utf-8"))
    regression = load("regression_source_inheritance_20261125.json")
    audit = load("source_inheritance_arm_audit_20261125.json")
    selector = load("selector_source_audit_fix_20261125.json")
    blind = load("blind_eval_source_audit_fix_20261125.json")
    heldout = load("heldout_eval_source_audit_fix_20261125.json")
    full = load("full_domain_eval_source_audit_fix_20261125.json")
    isolation = load("dense_isolation_verification_20261125.json")
    kb_audit = load("kb_audit_base_source_audit_fix_20261125.json")
    hybrid_audit = load("kb_audit_hybrid_source_audit_fix_20261125.json")
    sources_audit = load("sources_audit_source_audit_fix_20261125.json")
    index_sha = hashlib.sha256(base_path.read_bytes()).hexdigest()
    hybrid_sha = hashlib.sha256(hybrid_path.read_bytes()).hexdigest()

    assert regression["all_checks_ok"] is True
    assert regression["checks"]["old_default_unchanged"] is True
    assert regression["checks"]["x23_frozen_label_preserved"] is True
    assert regression["production_defaults"] == {"top_window": 3, "fragment_policy": None, "fact_selector": None}
    assert regression["summary_v2"]["base_default"]["ok"] == 26
    assert regression["summary_v2"]["base_strict"]["failed_ids"] == ["Q01", "Q02", "Q03", "Q05", "Q18"]
    assert regression["summary_v2"]["hybrid_default"]["ok"] == 22
    assert regression["summary_v2"]["hybrid_strict"]["ok"] == 19
    assert audit["old_default_unchanged"] is True
    assert audit["x23_frozen_label_preserved"] is True
    assert audit["dense_isolation_ok"] is True
    assert selector["summary"]["base_v2_ok"] == 26
    strict_mode = selector["summary"]["modes"]["strict_fragments"]
    assert strict_mode["v2_ok"] == 21 and strict_mode["newly_passed"] == []
    assert all(mode["wrong_evidence"] == [] for mode in selector["summary"]["modes"].values())
    for data in (blind, heldout, full):
        assert data["summary"]["ok"] == data["summary"]["total"]
        assert data["summary"].get("wrong_evidence_ids", []) == []
    assert blind["summary"]["total"] == 26
    assert heldout["summary"]["total"] == full["summary"]["total"] == 16
    assert blind["index"]["sha256"] == heldout["index"]["sha256"] == full["index_sha256"] == index_sha
    assert blind["isolation"]["ok"] and heldout["isolation"]["ok"]
    assert isolation["all_checks_ok"] is True
    assert isolation["auto_index_is_base"] is True
    assert isolation["base_queries_unchanged"] is True
    assert isolation["old_delivery_hashes_ok"] is True
    assert isolation["old_delivery_state_changed"] == []
    assert isolation["production_dense_present"] == {"base": False, "hybrid": False}
    assert kb_audit["counts"] == {"pass": 6, "fail": 0, "inconclusive": 3,
                                  "entries": 41, "revisions": 14, "chunks": 802}
    assert hybrid_audit["counts"] == {"pass": 6, "fail": 0, "inconclusive": 3,
                                      "entries": 41, "revisions": 14, "chunks": 816}
    assert sources_audit["counts"] == {"pass": 8, "fail": 0, "inconclusive": 1,
                                       "sources": 95, "packs": 23,
                                       "elements_checked": 88, "elements_supported": 88}
    wild = next(check for check in sources_audit["checks"] if check["check_id"] == "no_wild_sources")
    assert wild["verdict"] == "pass" and wild["detail"] == []
    support = next(check for check in sources_audit["checks"] if check["check_id"] == "verified_support")
    assert support["verdict"] == "inconclusive" and len(support["detail"]) == 40
    for name, expected in PRIOR.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    dense_files = sorted((OUT / "dense_probe").glob("*.npz"))
    assert {path.name for path in dense_files} == set(DENSE_EXPECTED)
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == DENSE_EXPECTED[path.name]
               for path in dense_files)
    assert len(base["chunks"]) == 802 and len(hybrid["chunks"]) == 816

    gates = {
        "project_selftest": gate("selftest_source_audit_fix_20261125.log", r"SELFTEST OK (\d+)/(\d+)"),
        "kb_selftest": gate("kb_selftest_source_audit_fix_20261125.log", r"KB_SELFTEST OK (\d+)/(\d+)"),
        "cross_platform_selftest": gate("cross_platform_source_audit_fix_20261125.log", r"CROSS_PLATFORM_SELFTEST OK (\d+)/(\d+)"),
        "sources_selftest": gate("sources_selftest_source_audit_fix_20261125.log", r"SOURCES_SELFTEST OK (\d+)/(\d+)"),
        "topic_selftest": gate("topic_selftest_source_audit_fix_20261125.log", r"自检合计\s*(\d+)\s*格：PASS\s*(\d+)\s*/\s*FAIL\s*0"),
    }
    assert gates["project_selftest"]["passed"] == 1465
    assert gates["kb_selftest"]["passed"] == 302
    assert gates["cross_platform_selftest"]["passed"] == 33
    assert gates["sources_selftest"]["passed"] == 69
    topic = (OUT / "topic_selftest_source_audit_fix_20261125.log").read_text(encoding="utf-8")
    assert all(f"PASS  T15{x}" in topic for x in "abcdefgh")

    report_text = REPORT.read_text(encoding="utf-8")
    for token in (index_sha, hybrid_sha, "26/26", "21/26", "22/26", "19/26",
                  "pass8/fail0/inconclusive1", "evidence_report", "insufficient_source",
                  "frozen_annotation_conflict", "两源并不一致", "1465/1465", "69/69",
                  "final_manifest_source_audit_fix_20261125.json"):
        assert token in report_text, token
    ledger = (ROOT / "测试问题与闸门说明书.md").read_text(encoding="utf-8")
    assert "## 54. 来源审计未登记字段闭环与 GBA 证据分级（11-25）" in ledger

    manifest = {
        "schema": "kb_final_manifest_source_audit_fix_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "来源审计字段与状态一致性修正、GBA 证据分级、并发取证纳册；BM25 生产默认；strict 与稠密层未批准；旧交付不变。",
        "production_unchanged": {"top_window": 3, "fragment_policy": None, "fact_selector": None,
                                 "strict_production_default": False, "dense_production_default": False,
                                 "gba_route_enabled": False, "gba_platform_gate": False,
                                 "megaman_route_enabled": False, "megaman_entries_indexed": 0,
                                 "commercial_rom_or_bios_ingested": False},
        "index": info(base_path, chunks=len(base["chunks"]), stats=base["stats"],
                      pipeline=base.get("pipeline"), built_at=base.get("built_at")),
        "hybrid_probe_index": info(hybrid_path, chunks=len(hybrid["chunks"]), stats=hybrid["stats"],
                                   pipeline=hybrid.get("pipeline"), production_approved=False),
        "corpus_map": info(KB_DIR / "corpus_map.json", entries=41, revisions=14),
        "source_registry": info(ROOT / "_工具脚本/taspipe/游戏包/来源库/sources.json",
                                sources=95, packs=23, elements_checked=88, elements_supported=88),
        "gba_showcase": info(ROOT / "_工具脚本/taspipe/游戏包/gba_aria_of_sorrow_souls.showcase.json",
                             verification_status="showcase_detection_verified_menu_gameplay_pending_platform_gate_pending"),
        "source_claim": info(ROOT / "_工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md"),
        "ledger": info(ROOT / "测试问题与闸门说明书.md", appended_section="54"),
        "code": {**blind["code"], "kb_provenance": info(ROOT / "_工具脚本/taspipe/kb_provenance.py"),
                 "kb_selftest_gates": info(ROOT / "_工具脚本/taspipe/kb_selftest_gates.py"),
                 "sources_audit": info(ROOT / "_工具脚本/taspipe/sources.py"),
                 "sources_selftest_gates": info(ROOT / "_工具脚本/taspipe/sources_selftest_gates.py")},
        "evaluations": {
            "blind": {"passed": blind["summary"]["ok"], "total": blind["summary"]["total"],
                      "wrong_evidence_ids": blind["summary"]["wrong_evidence_ids"],
                      "missed_answer_ids": blind["summary"]["missed_answer_ids"],
                      "isolation_ok": blind["isolation"]["ok"], "rerun_after_ledger_append": True,
                      "artifact": info(OUT / "blind_eval_source_audit_fix_20261125.json")},
            "heldout_blind": {"passed": heldout["summary"]["ok"], "total": heldout["summary"]["total"],
                              "wrong_evidence_ids": heldout["summary"]["wrong_evidence_ids"],
                              "isolation_ok": heldout["isolation"]["ok"], "rerun_after_ledger_append": True,
                              "artifact": info(OUT / "heldout_eval_source_audit_fix_20261125.json")},
            "full_domain": {"passed": full["summary"]["ok"], "total": full["summary"]["total"],
                            "rerun_after_ledger_append": True,
                            "artifact": info(OUT / "full_domain_eval_source_audit_fix_20261125.json")},
            "selector": {"base": selector["summary"]["base_v2_ok"],
                         "modes": {name: {key: value[key] for key in
                                          ("v2_ok", "wrong_evidence", "newly_passed", "intercepted")}
                                   for name, value in selector["summary"]["modes"].items()},
                         "artifact": info(OUT / "selector_source_audit_fix_20261125.json")},
            "four_arm_audit": {"summaries": audit["summaries"],
                               "x23_frozen_label_preserved": audit["x23_frozen_label_preserved"],
                               "old_default_unchanged": audit["old_default_unchanged"],
                               "artifact": info(OUT / "source_inheritance_arm_audit_20261125.json")},
            "regression": {"all_checks_ok": regression["all_checks_ok"],
                           "checks": regression["checks"],
                           "historical_annotation_conflicts": regression["historical_annotation_conflicts"],
                           "artifact": info(OUT / "regression_source_inheritance_20261125.json")},
        },
        "gates": gates,
        "audits": {"base": {"status": kb_audit["status"], "counts": kb_audit["counts"],
                            "artifact": info(OUT / "kb_audit_base_source_audit_fix_20261125.json")},
                   "hybrid": {"status": hybrid_audit["status"], "counts": hybrid_audit["counts"],
                              "artifact": info(OUT / "kb_audit_hybrid_source_audit_fix_20261125.json")},
                   "sources": {"status": sources_audit["status"], "counts": sources_audit["counts"],
                               "no_wild_sources": "pass", "verified_support_elements": 40,
                               "artifact": info(OUT / "sources_audit_source_audit_fix_20261125.json")}},
        "dense_isolation": isolation,
        "dense_probe_files": [info(path) for path in dense_files],
        "builds": {"base": info(OUT / "build_base_20261125.log"),
                   "hybrid": info(OUT / "build_hybrid_20261125.log"),
                   "dense_base": info(OUT / "dense_base_20261125.log"),
                   "dense_hybrid": info(OUT / "dense_hybrid_20261125.log")},
        "prior_delivery_unchanged": {"ok": True,
                                     "artifacts": {name: info(ROOT / name, expected_sha256=expected)
                                                   for name, expected in PRIOR.items()}},
        "open_items": {"unverified_versions": 6, "megaman1": "draft_not_frozen",
                       "dynamic_esports_records": 0, "real_user_query_samples": "insufficient",
                       "hybrid_production": "not approved", "strict_production": "not approved",
                       "gba_platform_gate": False, "aria_soul_gameplay4": "candidate",
                       "sources_verified_support": "40 elements remain inconclusive"},
        "report_md": info(REPORT),
        "artifact_inventory": str(OUT / "artifact_inventory_source_audit_fix_20261125.md"),
        "delivery_dir": str(OUT),
        "git": {"commit_created": False, "push_performed": False},
    }
    target = OUT / "final_manifest_source_audit_fix_20261125.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(target), "base_chunks": len(base["chunks"]),
                      "base_sha256": index_sha, "hybrid_chunks": len(hybrid["chunks"]),
                      "hybrid_sha256": hybrid_sha, "gates": {k: v["passed"] for k, v in gates.items()},
                      "blind": blind["summary"]["ok"], "heldout": heldout["summary"]["ok"],
                      "full_domain": full["summary"]["ok"], "source_audit": sources_audit["counts"],
                      "all_checks_ok": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
