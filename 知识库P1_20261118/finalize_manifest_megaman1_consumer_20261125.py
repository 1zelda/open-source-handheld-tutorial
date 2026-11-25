# -*- coding: utf-8 -*-
"""最终校验并生成洛克人1候选消费方交付清单。"""
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
TOOLS = ROOT / "_工具脚本"
sys.path.insert(0, str(TOOLS))
from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import kb_route as KR
from taspipe import sources as S

EVAL = BASE / "megaman1_candidate_consumer_eval_20261125.json"
READINESS = BASE / "megaman1_candidate_consumer_readiness_20261125.json"
RENDER_QA = BASE / "megaman1_candidate_20261125/qc/consumer/render_qa.json"
QC_DIR = BASE / "megaman1_candidate_20261125/qc/consumer"
MANIFEST = BASE / "megaman1_consumer_delivery_manifest_20261125.json"
ARTIFACTS = [
    ROOT / "_工具脚本/taspipe/kb_megaman1.py",
    BASE / "eval_megaman1_candidate_consumer_20261125.py",
    BASE / "finalize_megaman1_consumer_20261125.py",
    BASE / "render_qc_megaman1_consumer_20261125.py",
    BASE / "megaman1_candidate_consumer_eval_20261125.json",
    BASE / "megaman1_candidate_consumer_eval_20261125.md",
    BASE / "megaman1_candidate_20261125/qc/consumer_query_log_20261125.jsonl",
    READINESS,
    BASE / "megaman1_candidate_20261125/index.json",
    ROOT / "洛克人1候选路由与问答消费方交付_2026-11-25.md",
    ROOT / "洛克人1候选路由与问答消费方交付_2026-11-25.pdf",
    RENDER_QA,
    QC_DIR / "report.html",
    QC_DIR / "contact_sheet.png",
    QC_DIR / "page_01.png",
    QC_DIR / "page_02.png",
    QC_DIR / "page_03.png",
]
REAL_PATHS = [K.INDEX_JSON, K.CORPUS_MAP, S.REG_JSON, S.LEDGER_JSON,
              K.KB_DIR / "query_log.jsonl", KE.DB_PATH,
              ROOT / "选题决策层/kb快照/index.json",
              K.KB_DIR / "index_hybrid.json"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(path):
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {"present": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha(path)}


def main():
    before = {str(p): snapshot(p) for p in REAL_PATHS}
    e = json.loads(EVAL.read_text(encoding="utf-8"))
    r = json.loads(READINESS.read_text(encoding="utf-8"))
    q = json.loads(RENDER_QA.read_text(encoding="utf-8"))
    corpus = json.loads(K.CORPUS_MAP.read_text(encoding="utf-8"))
    mm1_entries = [x for x in corpus["entries"] if x.get("revision") == "megaman1_nes_us"]
    artifacts = []
    for path in ARTIFACTS:
        if not path.is_file():
            raise RuntimeError(f"artifact missing: {path}")
        artifacts.append({"path": path.relative_to(ROOT).as_posix(),
                          "bytes": path.stat().st_size, "sha256": sha(path)})
    artifacts.sort(key=lambda x: x["path"])
    canonical = "\n".join(f"{x['path']}\0{x['sha256']}\0{x['bytes']}" for x in artifacts)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    checks = {
        "route_cases_13": e["summary"]["route_ok"] == e["summary"]["route_total"] == 13,
        "default_12": e["summary"]["default_ok"] == 12,
        "strict_12": e["summary"]["strict_ok"] == 12,
        "wrong_zero": e["summary"]["default_wrong"] == e["summary"]["strict_wrong"] == 0,
        "missed_zero": e["summary"]["default_missed"] == e["summary"]["strict_missed"] == 0,
        "failure_close_4": e["failure_close"]["ok"] == e["failure_close"]["total"] == 4,
        "consumer_logs_24": e["query_log"]["lines"] == 24,
        "consumer_log_hash": sha(BASE / "megaman1_candidate_20261125/qc/consumer_query_log_20261125.jsonl") == e["query_log"]["sha256"],
        "candidate_index_hash": sha(BASE / "megaman1_candidate_20261125/index.json") == e["candidate_index_sha256"],
        "readiness_status": r["status"] == "isolated_candidate_consumer_ready_for_ram_tooling_only",
        "production_not_ready": not r["production_ready"] and not r["whole_game_knowledge_base"],
        "production_not_wired": not r["production_route_wired"] and not r["production_consumer_wired"],
        "production_domain_absent": not any("megaman" in x for x in KR.DOMAINS),
        "production_mm1_entries_disabled": bool(mm1_entries) and all(x.get("index") is False for x in mm1_entries),
        "render_checks_green": q["check_count"] == 23 and all(q["checks"].values()),
        "render_pages_3": q["pages"] == 3 and q["snapshot_pages"] == [1, 2, 3],
        "render_links_resolve": q["checks"]["delivery_links_resolve"],
        "artifacts_17": len(artifacts) == 17,
        "eval_isolation_green": e["isolation"]["ok"] and not e["isolation"]["changed_paths"],
    }
    after = {str(p): snapshot(p) for p in REAL_PATHS}
    changed = [p for p in before if before[p] != after[p]]
    checks["finalizer_real_state_unchanged"] = not changed
    manifest = {
        "status": "finalized_isolated_candidate_consumer",
        "date": "2026-11-25",
        "candidate_revision": e["candidate_revision"],
        "candidate_index_sha256": e["candidate_index_sha256"],
        "consumer": e["consumer"],
        "summary": e["summary"],
        "checks": checks,
        "check_passed": sum(checks.values()),
        "check_total": len(checks),
        "artifact_count": len(artifacts),
        "total_bytes": sum(x["bytes"] for x in artifacts),
        "total_fingerprint_sha256": fingerprint,
        "fingerprint_rule": "sha256 of lines: relative_path\\0sha256\\0bytes, sorted by relative_path; manifest itself excluded",
        "artifacts": artifacts,
        "production_defaults_unchanged": True,
        "production_route_wired": False,
        "production_consumer_wired": False,
        "production_ready": False,
        "whole_game_knowledge_base": False,
        "external_generative_model_calls": 0,
        "paid_api_calls": 0,
        "finalizer_isolation": {"ok": not changed, "changed_paths": changed,
                                "real_state_before": before, "real_state_after": after},
        "remaining": r["remaining_gates"],
    }
    tmp = MANIFEST.with_name(MANIFEST.name + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(MANIFEST)
    print(f"FINAL_OK checks={manifest['check_passed']}/{len(checks)} artifacts={len(artifacts)} "
          f"bytes={manifest['total_bytes']} fingerprint={fingerprint} unchanged={not changed}")
    print(str(MANIFEST))
    print(f"MANIFEST_SHA256 {sha(MANIFEST)} bytes={MANIFEST.stat().st_size}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
