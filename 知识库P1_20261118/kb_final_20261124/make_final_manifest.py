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
REPORT_PATH = ROOT / "知识库改进优化指导_2026-11-24_实施回填.md"
EXPECTED_SHA = "01ba5d9cd9e0e5c18d47531d81bdee09d3fa027da021c67173e9465222de9d47"


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def info(path, **extra):
    path = Path(path)
    data = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        **extra,
    }


def gate(name, pattern):
    text = (OUT / name).read_text(encoding="utf-8")
    match = re.search(pattern, text)
    assert match, name
    passed, total = map(int, match.groups())
    return {
        "passed": passed,
        "total": total,
        "ok": passed == total,
        "log": info(OUT / name),
    }


def main():
    index_bytes = INDEX_PATH.read_bytes()
    index = json.loads(index_bytes)
    index_sha = hashlib.sha256(index_bytes).hexdigest()
    snapshot_sha = hashlib.sha256(SNAPSHOT_PATH.read_bytes()).hexdigest()
    assert index_sha == snapshot_sha == EXPECTED_SHA
    assert len(index["chunks"]) == 770

    blind = load("blind_eval_final.json")
    heldout = load("heldout_eval_final.json")
    selector = load("selector_sweep_final.json")
    full_domain = load("full_domain_eval_final.json")
    coverage = load("kb_coverage_final.json")
    kb_audit = load("audit_final.json")
    sources_audit = load("sources_audit_final.json")
    inventory = load("unverified_source_inventory_20261124.json")
    state = load("state_isolation_final.json")
    consumer = load("news_snapshot_crosscheck.json")

    for item in (blind, heldout):
        assert item["index"]["sha256"] == EXPECTED_SHA
        assert item["summary"]["ok"] == item["summary"]["total"]
        assert item["summary"]["errors"] == 0
        assert item["summary"]["wrong_evidence_ids"] == []
        assert item["isolation"]["ok"] is True
    assert full_domain["index_sha256"] == EXPECTED_SHA
    assert full_domain["summary"]["ok"] == full_domain["summary"]["total"] == 16
    assert selector["index"]["chunks"] == 770
    assert selector["index"]["sha16"] == EXPECTED_SHA[:16]
    assert kb_audit["counts"]["fail"] == sources_audit["counts"]["fail"] == 0
    assert coverage["text"]["index_sha256"] == EXPECTED_SHA
    assert coverage["errors"] == []
    assert state["ok"] is True
    assert consumer["ok"] is True and consumer["news_snapshot"]["synced"] is True
    assert inventory["promoted"] == [] and len(inventory["kept_unverified"]) == 6
    report_text = REPORT_PATH.read_text(encoding="utf-8")
    assert EXPECTED_SHA in report_text and "1409/1409" in report_text and "16/16" in report_text

    selftest = gate("selftest_final.log", r"SELFTEST OK (\d+)/(\d+)")
    kb_gates = gate("kb_selftest_final.log", r"KB_SELFTEST OK (\d+)/(\d+)")
    cross_gates = gate("cross_platform_final.log", r"CROSS_PLATFORM_SELFTEST OK (\d+)/(\d+)")

    manifest = {
        "schema": "kb_final_manifest_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "BM25 base only; hybrid/dense excluded; no external generative model or paid API",
        "index": info(
            INDEX_PATH,
            chunks=len(index["chunks"]),
            built_at=index.get("built_at"),
            token_version=index.get("token_version"),
            pipeline=index.get("pipeline"),
        ),
        "news_snapshot": info(SNAPSHOT_PATH, chunks=770, synced=snapshot_sha == index_sha),
        "hybrid_excluded": info(
            HYBRID_PATH,
            chunks=767,
            reason="stale dense arm; not used for final claims",
        ),
        "corpus_map": info(ROOT / "_工具脚本/taspipe/游戏包/知识库/corpus_map.json"),
        "sources": info(ROOT / "_工具脚本/taspipe/游戏包/来源库/sources.json"),
        "esports_db": info(ROOT / "_工具脚本/taspipe/游戏包/电竞事实库/facts_v1.db", schema="v3"),
        "code": blind["code"],
        "build": info(OUT / "build.final.log"),
        "evaluations": {
            "legacy_blind": {
                "passed": blind["summary"]["ok"],
                "total": blind["summary"]["total"],
                "errors": blind["summary"]["errors"],
                "wrong_evidence_ids": blind["summary"]["wrong_evidence_ids"],
                "isolation_ok": blind["isolation"]["ok"],
                "artifact": info(OUT / "blind_eval_final.json"),
            },
            "heldout_blind": {
                "passed": heldout["summary"]["ok"],
                "total": heldout["summary"]["total"],
                "by_tier": heldout["summary"]["by_tier"],
                "errors": heldout["summary"]["errors"],
                "wrong_evidence_ids": heldout["summary"]["wrong_evidence_ids"],
                "isolation_ok": heldout["isolation"]["ok"],
                "artifact": info(OUT / "heldout_eval_final.json"),
            },
            "selector": {
                "base_passed": selector["summary"]["base_v2_ok"],
                "total": 26,
                "modes": {
                    key: {"passed": value["v2_ok"], "wrong_evidence": value["wrong_evidence"]}
                    for key, value in selector["summary"]["modes"].items()
                },
                "artifact": info(OUT / "selector_sweep_final.json"),
            },
            "full_domain": {
                "passed": full_domain["summary"]["ok"],
                "total": full_domain["summary"]["total"],
                "by_category": full_domain["summary"]["by_category"],
                "artifact": info(OUT / "full_domain_eval_final.json"),
            },
        },
        "gates": {
            "project_selftest": selftest,
            "kb_selftest": kb_gates,
            "cross_platform_selftest": cross_gates,
        },
        "audits": {
            "kb": {
                "status": kb_audit["status"],
                "counts": kb_audit["counts"],
                "artifact": info(OUT / "audit_final.json"),
            },
            "sources": {
                "status": sources_audit["status"],
                "counts": sources_audit["counts"],
                "artifact": info(OUT / "sources_audit_final.json"),
            },
        },
        "coverage": {
            "state_counts": coverage["state_counts"],
            "registered_domains": coverage["registered_domains"],
            "query_log_summary": coverage["query_log"]["summary"],
            "esports": {
                "schema": coverage["esports"]["schema"],
                "entities": sum(coverage["esports"]["entity_types"].values()),
                "evidence": coverage["esports"]["evidence"],
                "snapshots": coverage["esports"]["snapshots"],
                "dynamic_tables": coverage["esports"]["dynamic_tables"],
                "foreign_key_violations": coverage["esports"]["foreign_key_violations"],
            },
            "errors": coverage["errors"],
            "artifact": info(OUT / "kb_coverage_final.json"),
        },
        "unverified_source_inventory": {
            "promoted": inventory["promoted"],
            "kept_unverified": len(inventory["kept_unverified"]),
            "artifact": info(OUT / "unverified_source_inventory_20261124.json"),
        },
        "news_consumer_smoke": {
            "ok": consumer["ok"],
            "logged_queries": consumer["smoke"]["logged_queries"],
            "golden_path_passes": consumer["smoke"]["golden_path_passes"],
            "statuses": consumer["smoke"]["statuses"],
            "real_query_log_unchanged": consumer["real_query_log"]["unchanged"],
            "artifact": info(OUT / "news_snapshot_crosscheck.json"),
        },
        "state_isolation": {
            "ok": state["ok"],
            "changed_paths": state["changed_paths"],
            "esports_db_unchanged": state["esports_db_unchanged_vs_eval_isolation"],
            "artifact": info(OUT / "state_isolation_final.json"),
        },
        "report_md": info(REPORT_PATH),
        "delivery_dir": str(OUT),
    }
    (OUT / "final_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "manifest": str(OUT / "final_manifest.json"),
                "index_sha256": index_sha,
                "selftest": selftest["passed"],
                "kb_gates": kb_gates["passed"],
                "cross_platform": cross_gates["passed"],
                "heldout": heldout["summary"]["ok"],
                "snapshot_synced": snapshot_sha == index_sha,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
