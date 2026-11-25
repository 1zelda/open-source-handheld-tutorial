# -*- coding: utf-8 -*-
"""生成 strict 片段修正副本总指纹；不覆盖旧 manifest。"""
import hashlib
import json
import re
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124"
INDEX_PATH = ROOT / "_工具脚本/taspipe/游戏包/知识库/index.json"
SNAPSHOT_PATH = ROOT / "选题决策层/kb快照/index.json"
HYBRID_PATH = ROOT / "_工具脚本/taspipe/游戏包/知识库/index_hybrid.json"
REPORT_PATH = ROOT / "知识库改进优化指导_2026-11-24_strict片段修正回填.md"
PROVENANCE_PATH = ROOT / "_工具脚本/taspipe/kb_provenance.py"
GATES_PATH = ROOT / "_工具脚本/taspipe/kb_selftest_gates.py"
EXPECTED_SHA = "01ba5d9cd9e0e5c18d47531d81bdee09d3fa027da021c67173e9465222de9d47"
EXPECTED_PROVENANCE_SHA = "12babf001ddb13543a987f962139eb79688bc5e89f4128b71a0682e720ddbc83"
EXPECTED_GATES_SHA = "691c0354f3f33fa2722dfc349e501ae11150f8591dbaeb6410644c86c0366f16"
PRIOR_DELIVERY_SHA = {
    "知识库改进优化指导_2026-11-24_实施回填.md": "f2c18269c68daa1bcd4c9d5b6c2d8c7ad16c1372e9d6eb2f04d3cd1a06468d94",
    "知识库改进优化指导_2026-11-24_实施回填.pdf": "b3e6c2c427517ef5c77b2f991c8a8d994820fc56c764993e1268253d805e5a50",
    "知识库改进优化指导_2026-11-24_最终加固回填.md": "c8b1b08e912e1d5cf760bde0a56cdb3544f371d70396ae0d166adcc7e9a5b098",
    "知识库改进优化指导_2026-11-24_最终加固回填.pdf": "53b3ab92b9a5fd9806e4fabccbd0165369e8baa187fcb546fde2fe20464ce061",
    "知识库P1_20261118/kb_final_20261124/final_manifest.json": "2fd67d2dc5f771312b5f9eb95f7c497cf1fe89d74f29b1ab3114d3278405b630",
    "知识库P1_20261118/kb_final_20261124/final_manifest_post_provenance_20261124.json": "a4ce75fca15bf82c6e7f244327618544036fd364757f25c1040d431898383745",
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
    assert match, name
    passed, total = map(int, match.groups())
    return {"passed": passed, "total": total, "ok": passed == total,
            "log": info(OUT / name)}


def main():
    index_bytes = INDEX_PATH.read_bytes()
    index = json.loads(index_bytes)
    index_sha = hashlib.sha256(index_bytes).hexdigest()
    snapshot_sha = hashlib.sha256(SNAPSHOT_PATH.read_bytes()).hexdigest()
    assert index_sha == snapshot_sha == EXPECTED_SHA
    assert len(index["chunks"]) == 770

    blind = load("blind_eval_after_strict_citation_fix_20261124.json")
    heldout = load("heldout_eval_post_provenance_20261124.json")
    selector = load("selector_sweep_after_strict_citation_fix_20261124.json")
    full_domain = load("full_domain_eval_post_provenance_20261124.json")
    regression = load("regression_after_strict_citation_fix_20261124.json")
    strict_audit = load("strict_probe_change_audit_after_citation_fix_20261124.json")
    kb_audit = load("audit_post_provenance_20261124.json")
    sources_audit = load("sources_audit_final.json")
    inventory = load("unverified_source_inventory_20261124.json")
    identity = load("version_identity_audit_20261124.json")
    megaman = json.loads((OUT.parent / "megaman1_questions_draft_20261124.json").read_text(encoding="utf-8"))
    coverage = load("kb_coverage_final.json")
    consumer = load("news_snapshot_crosscheck.json")

    for item in (blind, heldout):
        assert item["index"]["sha256"] == EXPECTED_SHA
        assert item["summary"]["ok"] == item["summary"]["total"]
        assert item["summary"]["errors"] == 0
        assert item["summary"]["wrong_evidence_ids"] == []
        assert item["isolation"]["ok"] is True
    assert full_domain["index_sha256"] == EXPECTED_SHA
    assert full_domain["summary"]["ok"] == full_domain["summary"]["total"] == 16
    assert full_domain["db_sha256"] == load("full_domain_eval_final.json")["db_sha256"]
    assert selector["index"]["chunks"] == 770
    assert selector["index"]["sha16"] == EXPECTED_SHA[:16]
    assert selector["summary"]["base_v2_ok"] == 26
    assert selector["summary"]["modes"]["scoped"]["v2_ok"] == 26
    assert selector["summary"]["modes"]["scoped_beyond"]["v2_ok"] == 26
    assert selector["summary"]["modes"]["replace"]["v2_ok"] == 23
    assert selector["summary"]["modes"]["strict_fragments"]["v2_ok"] == 25
    assert all(v["wrong_evidence"] == [] for v in selector["summary"]["modes"].values())
    assert selector["summary"]["modes"]["strict_fragments"]["newly_passed"] == []
    assert regression["base_total"] == 26 and regression["base_pass"] == 13
    assert regression["strict_pass"] == 12
    assert regression["strict_intercepted_ids"] == ["Q01"]
    assert regression["strict_newly_passed_ids"] == []
    assert regression["isolation"]["ok"] is True
    assert regression["production_defaults"] == {
        "top_window": 3, "fragment_policy": None, "fact_selector": None}
    assert strict_audit["index"]["chunks"] == 770
    assert strict_audit["index"]["sha16"] == EXPECTED_SHA[:16]
    assert strict_audit["production_defaults"] == regression["production_defaults"]
    assert strict_audit["probe_change_summary"] == {
        "old_strict_v2_ok": 22,
        "current_strict_v2_ok": 25,
        "restored_vs_old_strict": ["X03", "X04", "X23"],
        "newly_passed_vs_current_base": [],
        "current_strict_intercepted": ["X05", "X17", "X19", "X20", "X22", "X30"],
        "frozen_labels_modified": False,
    }
    assert [row["id"] for row in strict_audit["restored_questions"]] == ["Q02", "Q03", "Q04", "Q05"]
    assert all(row["base_status"] == row["strict_status"] == "pass"
               and row["restored_gold_chunk"] for row in strict_audit["restored_questions"])
    x23 = next(row for row in strict_audit["probe_details"] if row["id"] == "X23")
    assert x23["frozen_kind"] == "insufficient_source"
    assert x23["current_base_status"] == x23["current_strict_status"] == "pass"
    assert not x23["new_pass_vs_current_base"]
    assert strict_audit["x23_disposition"]["classification"] == "frozen_annotation_conflict"
    assert strict_audit["isolation"]["ok"] is True
    assert hashlib.sha256(PROVENANCE_PATH.read_bytes()).hexdigest() == EXPECTED_PROVENANCE_SHA
    assert hashlib.sha256(GATES_PATH.read_bytes()).hexdigest() == EXPECTED_GATES_SHA
    assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
               for name, expected in PRIOR_DELIVERY_SHA.items())
    assert kb_audit["counts"]["fail"] == sources_audit["counts"]["fail"] == 0
    assert coverage["text"]["index_sha256"] == EXPECTED_SHA
    assert coverage["errors"] == []
    assert consumer["ok"] is True and consumer["news_snapshot"]["synced"] is True
    assert inventory["promoted"] == [] and len(inventory["kept_unverified"]) == 6
    assert identity["promoted"] == []
    assert identity["summary"]["retained_unverified"] == 6
    assert identity["summary"]["promoted"] == 0
    assert sum(identity["summary"]["identity_status_counts"].values()) == 6
    assert all(v["mechanism_authority_available"] is False and v["promoted"] is False
               for v in identity["revisions"].values())
    assert megaman["status"] == "draft_not_frozen" and len(megaman["questions"]) == 12

    report_text = REPORT_PATH.read_text(encoding="utf-8")
    for required in (EXPECTED_SHA, EXPECTED_PROVENANCE_SHA, EXPECTED_GATES_SHA,
                     "1447/1447", "292/292", "33/33", "166/166", "26/26", "16/16",
                     "25/26", "frozen_annotation_conflict", "15. 2026-11-24 strict",
                     "final_manifest_after_strict_citation_fix_20261124.json",
                     "artifact_inventory_after_strict_citation_fix_20261124.md",
                     "draft_not_frozen"):
        assert required in report_text, required

    selftest = gate("selftest_after_strict_citation_fix_20261124.log", r"SELFTEST OK (\d+)/(\d+)")
    kb_gates = gate("kb_selftest_after_strict_citation_fix_20261124.log", r"KB_SELFTEST OK (\d+)/(\d+)")
    cross_gates = gate("cross_platform_after_strict_citation_fix_20261124.log",
                       r"CROSS_PLATFORM_SELFTEST OK (\d+)/(\d+)")
    topic_gates = gate("topic_selftest_after_strict_citation_fix_20261124.log",
                       r"自检合计\s*(\d+)\s*格：PASS\s*(\d+)\s*/\s*FAIL\s*0")
    assert (selftest["passed"], kb_gates["passed"], cross_gates["passed"],
            topic_gates["passed"]) == (1447, 292, 33, 166)
    topic_text = (OUT / "topic_selftest_after_strict_citation_fix_20261124.log").read_text(encoding="utf-8")
    assert all(f"PASS  T15{x}" in topic_text for x in "abcdefgh")

    manifest = {
        "schema": "kb_final_manifest_after_strict_citation_fix_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "BM25 base only; hybrid/dense excluded; strict fragments shadow-only; X23 frozen annotation conflict retained; zero external generative model or paid API",
        "production_unchanged": {
            "top_window": 3, "fragment_policy": None, "fact_selector": None,
            "megaman_route_enabled": False, "megaman_entries_indexed": 0,
            "commercial_rom_or_bios_ingested": False,
        },
        "index": info(INDEX_PATH, chunks=len(index["chunks"]),
                      built_at=index.get("built_at"), token_version=index.get("token_version"),
                      pipeline=index.get("pipeline")),
        "news_snapshot": info(SNAPSHOT_PATH, chunks=770, synced=snapshot_sha == index_sha),
        "hybrid_excluded": info(HYBRID_PATH, chunks=767,
                                reason="stale dense arm; not used for final claims"),
        "corpus_map": info(ROOT / "_工具脚本/taspipe/游戏包/知识库/corpus_map.json"),
        "sources": info(ROOT / "_工具脚本/taspipe/游戏包/来源库/sources.json"),
        "esports_db": info(ROOT / "_工具脚本/taspipe/游戏包/电竞事实库/facts_v1.db", schema="v3"),
        "code": {**blind["code"], **selector["code"], **regression["code"]},
        "delivery_code": {"kb_provenance": info(PROVENANCE_PATH),
                          "kb_selftest_gates": info(GATES_PATH)},
        "evaluations": {
            "blind": {"passed": blind["summary"]["ok"],
                      "total": blind["summary"]["total"],
                      "errors": blind["summary"]["errors"],
                      "wrong_evidence_ids": blind["summary"]["wrong_evidence_ids"],
                      "isolation_ok": blind["isolation"]["ok"],
                      "rerun_after_strict_fix": True,
                      "artifact": info(OUT / "blind_eval_after_strict_citation_fix_20261124.json")},
            "heldout_blind": {"passed": heldout["summary"]["ok"],
                              "total": heldout["summary"]["total"],
                              "by_tier": heldout["summary"]["by_tier"],
                              "errors": heldout["summary"]["errors"],
                              "wrong_evidence_ids": heldout["summary"]["wrong_evidence_ids"],
                              "isolation_ok": heldout["isolation"]["ok"],
                              "rerun_after_strict_fix": False,
                              "reuse_basis": "production default fragment_policy=None unchanged",
                              "artifact": info(OUT / "heldout_eval_post_provenance_20261124.json")},
            "selector": {"base_passed": selector["summary"]["base_v2_ok"], "total": 26,
                         "modes": {key: {"passed": value["v2_ok"],
                                         "wrong_evidence": value["wrong_evidence"],
                                         "intercepted": value["intercepted"],
                                         "newly_passed": value["newly_passed"]}
                                   for key, value in selector["summary"]["modes"].items()},
                         "strict_shadow_only": True,
                         "artifact": info(OUT / "selector_sweep_after_strict_citation_fix_20261124.json")},
            "strict_status_comparison": {"base_status_pass": regression["base_pass"],
                                         "strict_status_pass": regression["strict_pass"],
                                         "intercepted_ids": regression["strict_intercepted_ids"],
                                         "newly_passed_ids": regression["strict_newly_passed_ids"],
                                         "artifact": info(OUT / "regression_after_strict_citation_fix_20261124.json")},
            "strict_probe_change_audit": {
                "old_strict_v2_ok": strict_audit["probe_change_summary"]["old_strict_v2_ok"],
                "current_strict_v2_ok": strict_audit["probe_change_summary"]["current_strict_v2_ok"],
                "restored_vs_old_strict": strict_audit["probe_change_summary"]["restored_vs_old_strict"],
                "newly_passed_vs_current_base": strict_audit["probe_change_summary"]["newly_passed_vs_current_base"],
                "x23_disposition": strict_audit["x23_disposition"],
                "frozen_labels_modified": strict_audit["probe_change_summary"]["frozen_labels_modified"],
                "artifact": info(OUT / "strict_probe_change_audit_after_citation_fix_20261124.json")},
            "full_domain": {"passed": full_domain["summary"]["ok"],
                            "total": full_domain["summary"]["total"],
                            "by_category": full_domain["summary"]["by_category"],
                            "rerun_after_strict_fix": False,
                            "reuse_basis": "production default fragment_policy=None unchanged",
                            "artifact": info(OUT / "full_domain_eval_post_provenance_20261124.json")},
        },
        "gates": {"project_selftest": selftest, "kb_selftest": kb_gates,
                  "cross_platform_selftest": cross_gates, "topic_selftest": topic_gates},
        "audits": {
            "kb": {"status": kb_audit["status"], "counts": kb_audit["counts"],
                   "artifact": info(OUT / "audit_post_provenance_20261124.json")},
            "sources": {"status": sources_audit["status"], "counts": sources_audit["counts"],
                        "artifact": info(OUT / "sources_audit_final.json")},
        },
        "identity_audit": {"retained_unverified": identity["summary"]["retained_unverified"],
                           "promoted": len(identity["promoted"]),
                           "identity_status_counts": identity["summary"]["identity_status_counts"],
                           "exact_rom_hash_hits": identity["rom_exact_hash_hits"],
                           "artifact": info(OUT / "version_identity_audit_20261124.json")},
        "megaman1": {"draft_status": megaman["status"], "questions": len(megaman["questions"]),
                     "candidate_revision": megaman["candidate_revision"],
                     "rom_sha1": megaman["rom_identity"]["sha1"],
                     "production_activated": False,
                     "draft": info(ROOT / "知识库P1_20261118/megaman1_questions_draft_20261124.json"),
                     "readiness": info(ROOT / "知识库P1_20261118/megaman1_corpus_readiness_20261124.md")},
        "coverage": {"state_counts": coverage["state_counts"],
                     "registered_domains": coverage["registered_domains"],
                     "query_log_summary": coverage["query_log"]["summary"],
                     "esports": {"schema": coverage["esports"]["schema"],
                                 "entities": sum(coverage["esports"]["entity_types"].values()),
                                 "evidence": coverage["esports"]["evidence"],
                                 "snapshots": coverage["esports"]["snapshots"],
                                 "dynamic_tables": coverage["esports"]["dynamic_tables"],
                                 "foreign_key_violations": coverage["esports"]["foreign_key_violations"]},
                     "errors": coverage["errors"],
                     "artifact": info(OUT / "kb_coverage_final.json")},
        "news_consumer_smoke": {"ok": consumer["ok"],
                                "logged_queries": consumer["smoke"]["logged_queries"],
                                "golden_path_passes": consumer["smoke"]["golden_path_passes"],
                                "statuses": consumer["smoke"]["statuses"],
                                "real_query_log_unchanged": consumer["real_query_log"]["unchanged"],
                                "artifact": info(OUT / "news_snapshot_crosscheck.json")},
        "state_isolation": {"ok": blind["isolation"]["ok"] and heldout["isolation"]["ok"]
                            and regression["isolation"]["ok"] and strict_audit["isolation"]["ok"],
                            "blind_changed_paths": blind["isolation"]["changed_paths"],
                            "heldout_changed_paths": heldout["isolation"]["changed_paths"],
                            "strict_comparison_changed_paths": regression["isolation"]["changed_paths"],
                            "strict_probe_audit_changed_paths": strict_audit["isolation"]["changed_paths"],
                            "topic_real_state_checks": "T15a-T15h all PASS",
                            "esports_db_unchanged_vs_prior_full_domain": True},
        "operational_note": "首个并行回归批因 F 盘临时写入高峰 Errno 28 失败；失败临时输出已清理，最终数字只取串行重跑。",
        "prior_delivery_unchanged": {
            "ok": True,
            "artifacts": {name: info(ROOT / name, expected_sha256=expected)
                          for name, expected in PRIOR_DELIVERY_SHA.items()},
        },
        "report_md": info(REPORT_PATH),
        "artifact_inventory": str(OUT / "artifact_inventory_after_strict_citation_fix_20261124.md"),
        "delivery_dir": str(OUT),
        "git": {"commit_created": False, "push_performed": False},
    }
    target = OUT / "final_manifest_after_strict_citation_fix_20261124.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(target), "index_sha256": index_sha,
                      "project_selftest": selftest["passed"], "kb_gates": kb_gates["passed"],
                      "cross_platform": cross_gates["passed"], "topic_selftest": topic_gates["passed"],
                      "blind": blind["summary"]["ok"], "heldout": heldout["summary"]["ok"],
                      "full_domain": full_domain["summary"]["ok"],
                      "strict_v2": selector["summary"]["modes"]["strict_fragments"]["v2_ok"],
                      "strict_status_pass": regression["strict_pass"],
                      "strict_newly_passed": regression["strict_newly_passed_ids"],
                      "identity_promoted": len(identity["promoted"])},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
