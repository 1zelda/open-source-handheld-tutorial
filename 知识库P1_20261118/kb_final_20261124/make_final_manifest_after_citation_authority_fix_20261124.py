# -*- coding: utf-8 -*-
"""生成当前来源别名修正总指纹；不覆盖任何旧 manifest。"""
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124"
INDEX_PATH = ROOT / "_工具脚本/taspipe/游戏包/知识库/index.json"
SNAPSHOT_PATH = ROOT / "选题决策层/kb快照/index.json"
HYBRID_PATH = ROOT / "_工具脚本/taspipe/游戏包/知识库/index_hybrid.json"
REPORT_PATH = ROOT / "知识库改进优化指导_2026-11-24_来源别名修正回填.md"
PROVENANCE_PATH = ROOT / "_工具脚本/taspipe/kb_provenance.py"
KB_PATH = ROOT / "_工具脚本/taspipe/kb.py"
GATES_PATH = ROOT / "_工具脚本/taspipe/kb_selftest_gates.py"
EXPECTED_SHA = "2a93e76d5876c1181e7784a20eca0f4d84888d0292d281fc6eea3564090b9260"
EXPECTED_KB_SHA = "1844d8baceb5ce65f2432908a84425ee1fcb8cb1f6e35e8d10c2f3a25331d08f"
EXPECTED_PROVENANCE_SHA = "4bcf3411ab460320ecff0120458141f44315b6cb0af1713143cc75470a6e7463"
EXPECTED_GATES_SHA = "158409770f627268070075f5859196c26d5b117f1e7e113d0878cd5bb910d068"
PRIOR_DELIVERY_SHA = {
    "知识库改进优化指导_2026-11-24_实施回填.md": "f2c18269c68daa1bcd4c9d5b6c2d8c7ad16c1372e9d6eb2f04d3cd1a06468d94",
    "知识库改进优化指导_2026-11-24_实施回填.pdf": "b3e6c2c427517ef5c77b2f991c8a8d994820fc56c764993e1268253d805e5a50",
    "知识库改进优化指导_2026-11-24_最终加固回填.md": "c8b1b08e912e1d5cf760bde0a56cdb3544f371d70396ae0d166adcc7e9a5b098",
    "知识库改进优化指导_2026-11-24_最终加固回填.pdf": "53b3ab92b9a5fd9806e4fabccbd0165369e8baa187fcb546fde2fe20464ce061",
    "知识库P1_20261118/kb_final_20261124/final_manifest.json": "2fd67d2dc5f771312b5f9eb95f7c497cf1fe89d74f29b1ab3114d3278405b630",
    "知识库P1_20261118/kb_final_20261124/final_manifest_post_provenance_20261124.json": "a4ce75fca15bf82c6e7f244327618544036fd364757f25c1040d431898383745",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def info(path, **extra):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), **extra}


def gate(name, pattern):
    text = (OUT / name).read_text(encoding="utf-8")
    match = re.search(pattern, text)
    assert match, name
    passed, total = map(int, match.groups())
    return {"passed": passed, "total": total, "ok": passed == total, "log": info(OUT / name)}


def esports_counts():
    path = ROOT / "_工具脚本/taspipe/游戏包/电竞事实库/facts_v1.db"
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        return {table: con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in ("series", "membership", "transfer_event", "patch_deployment")}
    finally:
        con.close()


def main():
    index_bytes = INDEX_PATH.read_bytes()
    index = json.loads(index_bytes)
    index_sha = hashlib.sha256(index_bytes).hexdigest()
    assert index_sha == EXPECTED_SHA == sha(SNAPSHOT_PATH)
    assert len(index["chunks"]) == 773
    assert sha(KB_PATH) == EXPECTED_KB_SHA
    assert sha(PROVENANCE_PATH) == EXPECTED_PROVENANCE_SHA
    assert sha(GATES_PATH) == EXPECTED_GATES_SHA

    blind = load("blind_eval_after_citation_authority_fix_20261124.json")
    heldout = load("heldout_eval_after_citation_authority_fix_20261124.json")
    full_domain = load("full_domain_eval_after_citation_authority_fix_20261124.json")
    selector = load("selector_sweep_after_citation_authority_fix_20261124.json")
    regression = load("strict_default_regression_after_citation_authority_fix_20261124.json")
    evolution = load("strict_alias_evolution_audit_after_citation_authority_fix_20261124.json")
    consumer = load("news_snapshot_crosscheck_after_citation_authority_fix_20261124.json")
    identity = load("version_identity_audit_20261124.json")
    megaman = json.loads((OUT.parent / "megaman1_questions_draft_20261124.json").read_text(encoding="utf-8"))

    for item, total in ((blind, 26), (heldout, 16)):
        assert item["index"]["sha256"] == EXPECTED_SHA
        assert item["index"]["chunks"] == 773
        assert item["summary"]["ok"] == item["summary"]["total"] == total
        assert item["summary"]["errors"] == 0
        assert item["summary"]["wrong_evidence_ids"] == []
        assert item["isolation"]["ok"] is True
    assert full_domain["index_sha256"] == EXPECTED_SHA
    assert full_domain["summary"]["ok"] == full_domain["summary"]["total"] == 16
    assert full_domain["code"]["kb_provenance"] == EXPECTED_PROVENANCE_SHA
    assert selector["index"]["chunks"] == 773
    assert selector["index"]["sha16"] == EXPECTED_SHA[:16]
    assert selector["summary"]["base_v2_ok"] == 26
    assert selector["summary"]["modes"]["scoped"]["v2_ok"] == 26
    assert selector["summary"]["modes"]["scoped_beyond"]["v2_ok"] == 26
    assert selector["summary"]["modes"]["replace"]["v2_ok"] == 23
    assert selector["summary"]["modes"]["strict_fragments"]["v2_ok"] == 21
    assert all(v["wrong_evidence"] == [] for v in selector["summary"]["modes"].values())
    assert selector["summary"]["modes"]["strict_fragments"]["newly_passed"] == []
    assert selector["summary"]["modes"]["strict_fragments"]["intercepted"] == [
        "X03", "X04", "X05", "X17", "X19", "X20", "X22", "X23", "X30"]

    assert regression["summary"]["default_raw_pass"] == 13
    assert regression["summary"]["strict_raw_pass"] == 7
    assert regression["summary"]["default_v2_ok"] == 26
    assert regression["summary"]["strict_v2_ok"] == 21
    assert regression["summary"]["strict_intercepted"] == ["Q01", "Q02", "Q03", "Q04", "Q05", "Q18"]
    assert regression["summary"]["strict_v2_regressed"] == ["Q01", "Q02", "Q03", "Q05", "Q18"]
    assert regression["summary"]["wrong_evidence_default"] == []
    assert regression["summary"]["wrong_evidence_strict"] == []
    assert regression["isolation"]["ok"] is True
    assert regression["modes"]["default"] == {
        "topk": 30, "top_window": 3, "fact_selector": None, "fragment_policy": None}

    assert evolution["ok"] is True
    versions = list(evolution["generations"].values())
    assert [v["v2_ok"] for v in versions] == [22, 25, 21]
    assert evolution["frozen_annotations"]["x23_kind"] == "insufficient_source"
    assert evolution["frozen_annotations"]["x23_current_class"] == "intercepted"
    assert consumer["ok"] is True and consumer["news_snapshot"]["synced"] is True
    assert consumer["smoke"]["logged_queries"] == 7
    assert consumer["real_state"]["unchanged"] is True

    assert all(sha(ROOT / name) == expected for name, expected in PRIOR_DELIVERY_SHA.items())
    assert identity["promoted"] == []
    assert identity["summary"]["retained_unverified"] == 6
    assert megaman["status"] == "draft_not_frozen" and len(megaman["questions"]) == 12

    report_text = REPORT_PATH.read_text(encoding="utf-8")
    required = (EXPECTED_SHA, EXPECTED_KB_SHA, EXPECTED_PROVENANCE_SHA, EXPECTED_GATES_SHA,
                "1462/1462", "302/302", "33/33", "166/166", "26/26", "16/16",
                "21/26", "25/26", "22/26", "13/26", "7/26", "来源别名",
                "final_manifest_after_citation_authority_fix_20261124.json",
                "artifact_inventory_after_citation_authority_fix_20261124.md",
                "draft_not_frozen")
    for value in required:
        assert value in report_text, value

    selftest = gate("selftest_after_citation_authority_fix_20261124.log", r"SELFTEST OK (\d+)/(\d+)")
    kb_gates = gate("kb_selftest_after_citation_authority_fix_20261124.log", r"KB_SELFTEST OK (\d+)/(\d+)")
    cross_gates = gate("cross_platform_after_citation_authority_fix_20261124.log",
                       r"CROSS_PLATFORM_SELFTEST OK (\d+)/(\d+)")
    topic_gates = gate("topic_selftest_after_citation_authority_fix_20261124.log",
                       r"自检合计\s*(\d+)\s*格：PASS\s*(\d+)\s*/\s*FAIL\s*0")
    assert (selftest["passed"], kb_gates["passed"], cross_gates["passed"],
            topic_gates["passed"]) == (1462, 302, 33, 166)

    dynamic = esports_counts()
    assert all(v == 0 for v in dynamic.values())
    manifest = {
        "schema": "kb_final_manifest_after_citation_authority_fix_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "BM25 production default unchanged; strict alias qualification shadow-only; zero external generative model or paid API",
        "production_unchanged": {
            "top_window": 3, "fragment_policy": None, "fact_selector": None,
            "strict_shadow_only": True, "megaman_route_enabled": False,
            "commercial_rom_or_bios_ingested": False,
        },
        "index": info(INDEX_PATH, chunks=len(index["chunks"]), built_at=index.get("built_at"),
                      token_version=index.get("token_version"), pipeline=index.get("pipeline")),
        "news_snapshot": info(SNAPSHOT_PATH, chunks=773, synced=sha(SNAPSHOT_PATH) == index_sha),
        "hybrid_excluded": info(HYBRID_PATH, chunks=787, reason="stale/unadopted dense arm; not used for final claims"),
        "corpus_map": info(ROOT / "_工具脚本/taspipe/游戏包/知识库/corpus_map.json"),
        "sources": info(ROOT / "_工具脚本/taspipe/游戏包/来源库/sources.json"),
        "esports_db": info(ROOT / "_工具脚本/taspipe/游戏包/电竞事实库/facts_v1.db", dynamic_counts=dynamic),
        "code": {**blind["code"], **selector["code"], **regression["code"]},
        "delivery_code": {"kb": info(KB_PATH), "kb_provenance": info(PROVENANCE_PATH),
                          "kb_selftest_gates": info(GATES_PATH)},
        "evaluations": {
            "blind": {"passed": blind["summary"]["ok"], "total": blind["summary"]["total"],
                      "errors": blind["summary"]["errors"],
                      "wrong_evidence_ids": blind["summary"]["wrong_evidence_ids"],
                      "isolation_ok": blind["isolation"]["ok"],
                      "artifact": info(OUT / "blind_eval_after_citation_authority_fix_20261124.json")},
            "heldout_blind": {"passed": heldout["summary"]["ok"], "total": heldout["summary"]["total"],
                              "by_tier": heldout["summary"]["by_tier"],
                              "errors": heldout["summary"]["errors"],
                              "wrong_evidence_ids": heldout["summary"]["wrong_evidence_ids"],
                              "isolation_ok": heldout["isolation"]["ok"],
                              "artifact": info(OUT / "heldout_eval_after_citation_authority_fix_20261124.json")},
            "full_domain": {"passed": full_domain["summary"]["ok"], "total": full_domain["summary"]["total"],
                            "by_category": full_domain["summary"]["by_category"],
                            "db_sha256": full_domain["db_sha256"],
                            "artifact": info(OUT / "full_domain_eval_after_citation_authority_fix_20261124.json")},
            "selector": {"base_passed": selector["summary"]["base_v2_ok"], "total": 26,
                         "modes": {key: {"passed": value["v2_ok"],
                                         "wrong_evidence": value["wrong_evidence"],
                                         "intercepted": value["intercepted"],
                                         "newly_passed": value["newly_passed"]}
                                   for key, value in selector["summary"]["modes"].items()},
                         "strict_shadow_only": True,
                         "artifact": info(OUT / "selector_sweep_after_citation_authority_fix_20261124.json")},
            "strict_status_comparison": {"default_status_pass": regression["summary"]["default_raw_pass"],
                                         "strict_status_pass": regression["summary"]["strict_raw_pass"],
                                         "default_v2": regression["summary"]["default_v2_ok"],
                                         "strict_v2": regression["summary"]["strict_v2_ok"],
                                         "intercepted_ids": regression["summary"]["strict_intercepted"],
                                         "v2_regressed_ids": regression["summary"]["strict_v2_regressed"],
                                         "artifact": info(OUT / "strict_default_regression_after_citation_authority_fix_20261124.json")},
            "strict_alias_evolution": {
                "old_v2": 22, "temporary_v2": 25, "current_v2": 21,
                "x23_kind": evolution["frozen_annotations"]["x23_kind"],
                "x23_current_class": evolution["frozen_annotations"]["x23_current_class"],
                "artifact": info(OUT / "strict_alias_evolution_audit_after_citation_authority_fix_20261124.json")},
        },
        "gates": {"project_selftest": selftest, "kb_selftest": kb_gates,
                  "cross_platform_selftest": cross_gates, "topic_selftest": topic_gates},
        "identity_audit": {"retained_unverified": identity["summary"]["retained_unverified"],
                           "promoted": len(identity["promoted"]),
                           "identity_status_counts": identity["summary"]["identity_status_counts"],
                           "artifact": info(OUT / "version_identity_audit_20261124.json")},
        "megaman1": {"draft_status": megaman["status"], "questions": len(megaman["questions"]),
                     "production_activated": False,
                     "draft": info(OUT.parent / "megaman1_questions_draft_20261124.json"),
                     "readiness": info(OUT.parent / "megaman1_corpus_readiness_20261124.md")},
        "news_consumer_smoke": {"ok": consumer["ok"], "logged_queries": consumer["smoke"]["logged_queries"],
                                "golden_path_passes": consumer["smoke"]["golden_path_passes"],
                                "statuses": consumer["smoke"]["statuses"],
                                "real_state_unchanged": consumer["real_state"]["unchanged"],
                                "artifact": info(OUT / "news_snapshot_crosscheck_after_citation_authority_fix_20261124.json")},
        "state_isolation": {"ok": blind["isolation"]["ok"] and heldout["isolation"]["ok"]
                            and regression["isolation"]["ok"] and consumer["real_state"]["unchanged"],
                            "blind_changed_paths": blind["isolation"]["changed_paths"],
                            "heldout_changed_paths": heldout["isolation"]["changed_paths"],
                            "strict_comparison_changed_paths": regression["isolation"]["changed_paths"],
                            "news_smoke_changed_paths": consumer["real_state"]["changed_paths"]},
        "prior_delivery_unchanged": {"ok": True, "artifacts": {
            name: info(ROOT / name, expected_sha256=expected) for name, expected in PRIOR_DELIVERY_SHA.items()}},
        "report_md": info(REPORT_PATH),
        "artifact_inventory": str(OUT / "artifact_inventory_after_citation_authority_fix_20261124.md"),
        "delivery_dir": str(OUT),
        "git": {"commit_created": False, "push_performed": False},
    }
    target = OUT / "final_manifest_after_citation_authority_fix_20261124.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(target), "index_sha256": index_sha,
                      "project_selftest": selftest["passed"], "kb_gates": kb_gates["passed"],
                      "cross_platform": cross_gates["passed"], "topic_selftest": topic_gates["passed"],
                      "blind": blind["summary"]["ok"], "heldout": heldout["summary"]["ok"],
                      "full_domain": full_domain["summary"]["ok"],
                      "strict_v2": selector["summary"]["modes"]["strict_fragments"]["v2_ok"],
                      "strict_status_pass": regression["summary"]["strict_raw_pass"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
