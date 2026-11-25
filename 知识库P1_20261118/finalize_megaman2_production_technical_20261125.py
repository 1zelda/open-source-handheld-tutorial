import hashlib
import json
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
TOOLS = ROOT / "_工具脚本"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

from taspipe import detector_promotion as DP
from taspipe import detector_promotion_selftest as DPT
from taspipe import kb as K
from taspipe import kb_megaman2 as M
from taspipe import sources as S

PACKAGE = BASE / "megaman2_production_technical_20261125"
REPORT = PACKAGE / "eval_report.json"
MANIFEST_OUT = BASE / "megaman2_production_technical_delivery_manifest_20261125.json"
MD_PATH = ROOT / "洛克人2生产技术域交付_2026-11-25.md"
PDF_PATH = ROOT / "洛克人2生产技术域交付_2026-11-25.pdf"
RENDER_QA = PACKAGE / "qc/render_qa.json"
RENDER_SCRIPT = BASE / "render_qc_megaman2_production_technical_20261125.py"
LOG_DIR = TOOLS / "_task_logs"
FULL_LOG = LOG_DIR / "mm2_production_technical_full_selftest_20261125_final.txt"
KB_LOG = LOG_DIR / "mm2_production_technical_kb_selftest_20261125_final.txt"
SOURCES_LOG = LOG_DIR / "mm2_production_technical_sources_selftest_20261125_final.txt"
EVAL_LOG = LOG_DIR / "mm2_production_technical_eval_20261125_final.txt"
PDF_QC_LOG = LOG_DIR / "mm2_production_technical_pdf_qc_20261125_final.txt"
ARIA_PACK = TOOLS / "taspipe/游戏包/gba_aria_of_sorrow_souls.detectors.showcase.json"
ARIA_PACKS = sorted((TOOLS / "taspipe/游戏包").glob("gba_aria_of_sorrow_souls.detectors*.showcase.json"))
DRIFT_EVIDENCE = PACKAGE / "qc/aria_shared_state_drift_20261125.json"
ACTION_DRIFT_EVIDENCE = PACKAGE / "qc/aria_action_window_drift_20261125.json"
RECIPE_PATHS = [
    TOOLS / "taspipe/校准配方/castlevania_aria_gba.soul_detector_promotion.json",
    TOOLS / "taspipe/校准配方/castlevania_aria_gba.soul_detector_promotion.r20261125T223657.json",
    TOOLS / "taspipe/校准配方/castlevania_aria_gba.soul_detector_promotion_action_window_20261125.json",
    TOOLS / "taspipe/校准配方/castlevania_aria_gba.soul_detector_promotion_tri_acceptance_20261125.json",
]

CODE_PATHS = {
    "detector_promotion": TOOLS / "taspipe/detector_promotion.py",
    "detector_promotion_selftest": TOOLS / "taspipe/detector_promotion_selftest.py",
    "kb": TOOLS / "taspipe/kb.py",
    "kb_route": TOOLS / "taspipe/kb_route.py",
    "kb_megaman2": TOOLS / "taspipe/kb_megaman2.py",
    "kb_answer": TOOLS / "taspipe/kb_answer.py",
    "sources": TOOLS / "taspipe/sources.py",
    "kb_selftest_gates": TOOLS / "taspipe/kb_selftest_gates.py",
    "sources_selftest_gates": TOOLS / "taspipe/sources_selftest_gates.py",
    "selftest": TOOLS / "taspipe/selftest.py",
    "知识对照": ROOT / "选题决策层/知识对照.py",
    "选题卡": ROOT / "选题决策层/选题卡.py",
    "evaluator": PACKAGE / "eval_production_technical.py",
    "render_qc": RENDER_SCRIPT,
    "finalizer": Path(__file__).resolve(),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def snapshot(path):
    path = Path(path)
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {"present": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha(path)}


def artifact(path):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def gate_count(path, pattern):
    match = re.search(pattern, Path(path).read_text(encoding="utf-8", errors="replace"))
    if not match:
        raise RuntimeError(f"missing gate count: {path}")
    return {"pass": int(match.group(1)), "total": int(match.group(2))}


def main():
    report = load(REPORT)
    contract = load(PACKAGE / "contract.json")
    scope = load(PACKAGE / "scope.json")
    render_qa = load(RENDER_QA)
    registry = S.load_registry(S.REG_JSON)
    aria_packs = [load(path) for path in ARIA_PACKS]
    checks = {}

    checks["evaluation_all_green"] = (
        report.get("status") == "pass"
        and all(report.get("checks", {}).values())
        and report["summary"]["positive_ok"] == report["summary"]["positive_total"]
        and report["summary"]["negative_ok"] == report["summary"]["negative_total"]
        and report["consumer"]["crosscheck_ok"] == report["consumer"]["cards_ok"] == 8
        and report["evidence_coverage"]["missing_files"] == []
        and report["isolation"]["ok"] is True)
    checks["production_contract_boundaries"] = (
        contract["production_route_wired"] is True
        and contract["production_consumer_wired"] is True
        and contract["candidate_only"] is False
        and contract["whole_game_knowledge_base"] is False
        and contract["regional_identity"]["pal_us_jp_equivalence_verified"] is False
        and contract["retrieval_defaults"]["fragment_policy"] is None
        and contract["retrieval_defaults"]["dense_default"] is False
        and contract["retrieval_defaults"]["nli_default"] is False
        and scope["backend_restart_required"] is False)
    final_audits = {"base": K.audit(index_path=K.INDEX_JSON),
                    "hybrid": K.audit(index_path=K.hybrid_index_path()),
                    "sources": S.audit()}
    checks["all_audits_no_fail"] = all(row["counts"]["fail"] == 0 for row in final_audits.values())
    checks["final_audits_match_evaluation"] = all(
        final_audits[name]["counts"] == report["audits"][name]["counts"]
        for name in final_audits)
    checks["all_supported_elements_counted"] = (
        final_audits["sources"]["counts"]["elements_checked"]
        == final_audits["sources"]["counts"]["elements_supported"])

    gates = {
        "project": gate_count(FULL_LOG, r"SELFTEST OK (\d+)/(\d+)"),
        "kb": gate_count(KB_LOG, r"KB_SELFTEST OK (\d+)/(\d+)"),
        "sources": gate_count(SOURCES_LOG, r"SOURCES_SELFTEST OK (\d+)/(\d+)"),
    }
    checks["all_regression_gates_green"] = all(row["pass"] == row["total"] for row in gates.values())
    checks["production_eval_log_reports_pass"] = '"status": "pass"' in EVAL_LOG.read_text(encoding="utf-8")
    checks["core_code_matches_evaluation"] = all(
        sha(CODE_PATHS[name]) == digest for name, digest in report["code_sha256"].items())

    production_source = next(row for row in registry["sources"]
                             if row["source_id"] == M.PRODUCTION_SOURCE_ID)
    checks["single_production_source_registered"] = (
        production_source["status"] == "verified_read"
        and len(production_source["evidence"]) == 7
        and all(row["result"]["selected_evidence"][0]["authority"] == "authoritative"
                for row in report["positive"] if row["ok"]))
    checks["production_evidence_hashes_match"] = all(
        sha(S.resolve_path(row["path"])) == row["sha256"]
        for row in report["evidence_coverage"]["evidence"])
    checks["index_hashes_match_evaluation"] = (
        sha(K.INDEX_JSON) == report["indexes"]["base"]["sha256"]
        and sha(K.hybrid_index_path()) == report["indexes"]["hybrid"]["sha256"])

    aria_ids = {"local_aria_menu_catalog_20261125", "aria_detector_separated_acceptance_20261125"}
    aria_registry = {row["source_id"]: row for row in registry["sources"] if row["source_id"] in aria_ids}
    aria_catalogs = [{row["source_id"]: row for row in pack["catalog"]["sources"]}
                     for pack in aria_packs]
    checks["aria_shared_pack_still_candidate_only"] = (
        bool(aria_catalogs)
        and set(aria_registry) == aria_ids
        and all(set(catalog) == aria_ids for catalog in aria_catalogs)
        and all(row.get("status") == "candidate" and row.get("verified_date") is None
                for catalog in aria_catalogs for row in catalog.values())
        and all(row.get("status") == "candidate" for row in aria_registry.values()))
    drift_incident = load(DRIFT_EVIDENCE) if DRIFT_EVIDENCE.is_file() else None
    checks["aria_drift_incident_recorded"] = (
        drift_incident is not None
        and drift_incident.get("status") == "fail"
        and drift_incident.get("checks", {}).get("aria_shared_pack_still_candidate_only") is False
        and drift_incident.get("shared_state", {}).get("changed_paths") == [str(ARIA_PACK)])
    action_drift = load(ACTION_DRIFT_EVIDENCE) if ACTION_DRIFT_EVIDENCE.is_file() else None
    checks["aria_action_window_drift_incident_recorded"] = (
        action_drift is not None
        and action_drift.get("status") == "fail"
        and action_drift.get("checks", {}).get("all_audits_no_fail") is False
        and action_drift.get("checks", {}).get("aria_shared_pack_still_candidate_only") is False)

    protected = [Path(path) for path in report["isolation"]["after"]]
    after = {str(path): snapshot(path) for path in protected}
    changed = [path for path in report["isolation"]["after"]
               if report["isolation"]["after"][path] != after[path]]
    checks["shared_state_unchanged_since_evaluation"] = not changed
    checks["human_delivery_exists"] = MD_PATH.is_file() and PDF_PATH.is_file()
    checks["pdf_visual_qc_all_green"] = render_qa.get("all_ok") is True and all(render_qa["checks"].values())
    checks["pdf_and_markdown_hashes_match_qc"] = (
        sha(PDF_PATH) == render_qa["pdf_sha256"]
        and sha(MD_PATH) == render_qa["markdown_sha256"])
    checks["no_external_generation_or_restart"] = (
        report["external_generative_model_calls"] == 0
        and report["paid_api_calls"] == 0
        and report["backend_restart_performed"] is False)

    artifact_paths = set(CODE_PATHS.values())
    artifact_paths.update(RECIPE_PATHS)
    artifact_paths.update({MANIFEST_OUT, MD_PATH, PDF_PATH, RENDER_QA, S.MD_PATH,
                           K.INDEX_JSON, K.hybrid_index_path(), K.CORPUS_MAP, S.REG_JSON,
                           FULL_LOG, KB_LOG, SOURCES_LOG, EVAL_LOG, PDF_QC_LOG})
    artifact_paths.update(ARIA_PACKS)
    artifact_paths.update(path for path in PACKAGE.rglob("*") if path.is_file())
    artifact_paths.update(S.resolve_path(path) for path in production_source["evidence"])
    artifacts = {str(path.relative_to(ROOT).as_posix()): artifact(path)
                 for path in sorted(artifact_paths, key=lambda item: str(item))
                 if path.resolve() != MANIFEST_OUT.resolve()}
    fingerprint_lines = [f"{rel}\0{row['sha256']}\0{row['bytes']}"
                         for rel, row in sorted(artifacts.items())]
    fingerprint = hashlib.sha256("\n".join(fingerprint_lines).encode("utf-8")).hexdigest()

    manifest = {
        "schema_version": 1,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task": "megaman2_production_technical_subdomain",
        "status": "pass" if all(checks.values()) else "fail",
        "all_ok": all(checks.values()),
        "checks": checks,
        "production": {
            "domain": M.PRODUCTION_DOMAIN,
            "revision": M.TECHNICAL_REVISION,
            "source_id": M.PRODUCTION_SOURCE_ID,
            "candidate_only": False,
            "whole_game_knowledge_base": False,
            "production_route_wired": True,
            "production_consumer_wired": True,
            "selected_evidence_rule": contract["selected_evidence_rule"],
            "regional_rom_equivalence_verified": False,
            "retrieval_defaults": contract["retrieval_defaults"],
        },
        "evaluation": {
            "report": str(REPORT),
            "summary": report["summary"],
            "seven_file_coverage": len(report["evidence_coverage"]["covered_files"]),
            "query_log_lines": report["summary"]["query_log_lines"],
            "crosscheck_unanchored_downgraded": report["consumer"]["unanchored_downgraded"],
        },
        "regression": {"gates": gates, "logs": {"project": str(FULL_LOG), "kb": str(KB_LOG),
                                                  "sources": str(SOURCES_LOG), "evaluation": str(EVAL_LOG)}},
        "audits": {name: {"status": row["status"], "counts": row["counts"]}
                   for name, row in final_audits.items()},
        "audit_interpretation": "fail=0 只表示已登记文本与来源关系未触发失败；inconclusive 仍是未覆盖、候选、继承或参考材料，不等于权威全覆盖。",
        "indexes": report["indexes"],
        "shared_state": {"unchanged_since_evaluation": not changed, "changed_paths": changed,
                         "snapshots": after, "aria_candidate_only": checks["aria_shared_pack_still_candidate_only"],
                         "aria_pack_count": len(ARIA_PACKS),
                         "aria_drift_incidents": [
                             {"recorded": drift_incident is not None,
                              "evidence": str(DRIFT_EVIDENCE),
                              "failed_at": drift_incident.get("finished_at") if drift_incident else None,
                              "changed_paths": drift_incident.get("shared_state", {}).get("changed_paths") if drift_incident else []},
                             {"recorded": action_drift is not None,
                              "evidence": str(ACTION_DRIFT_EVIDENCE),
                              "failed_at": action_drift.get("finished_at") if action_drift else None,
                              "changed_paths": action_drift.get("shared_state", {}).get("changed_paths") if action_drift else []},
                         ]},
        "pdf_qc": {"all_ok": render_qa["all_ok"], "pages": render_qa["pages"],
                   "check_count": render_qa["check_count"], "report": str(RENDER_QA),
                   "pdf": str(PDF_PATH), "markdown": str(MD_PATH),
                   "pdf_sha256": render_qa["pdf_sha256"], "markdown_sha256": render_qa["markdown_sha256"]},
        "code_sha256": {name: sha(path) for name, path in CODE_PATHS.items()},
        "artifacts": artifacts,
        "delivery_fingerprint": {
            "algorithm": "SHA-256 over UTF-8 lines: relative_path NUL sha256 NUL bytes; sorted by relative_path; manifest excludes itself",
            "sha256": fingerprint,
            "artifact_count": len(artifacts),
            "excludes_self": True,
        },
        "remaining": scope["not_covered"],
        "next_actions": [
            "继续用真实查询回流抽查开放问题，不用冻结样本宣称永久零错误",
            "只有取得可核验地区 ROM 身份后，才建立对应地区版本并验证跨版关系",
            "后续新增武器、敌人、关卡等资料时逐项登记来源与资格，不将候选材料自动升格",
            "dense 与 NLI 仍待正确性和授权数据稳定后单独评估，当前默认保持 BM25",
        ],
        "external_generative_model_calls": 0,
        "paid_api_calls": 0,
        "backend_restart_performed": False,
        "commit_or_push_performed": False,
    }
    atomic_text(MANIFEST_OUT, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"all_ok": manifest["all_ok"], "checks": checks, "gates": gates,
                      "artifact_count": len(artifacts), "fingerprint": fingerprint,
                      "manifest": str(MANIFEST_OUT)}, ensure_ascii=True, indent=2))
    return 0 if manifest["all_ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
