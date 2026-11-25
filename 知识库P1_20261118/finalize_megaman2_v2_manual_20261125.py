import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
TOOLS = ROOT / "_工具脚本"
sys.path.insert(0, str(TOOLS))

from taspipe import kb as K
from taspipe import kb_megaman2 as M
from taspipe import sources as S

BUILD_REPORT = BASE / "megaman2_candidate_v2_manual_build_20261125.json"
ISOLATED_REPORT = BASE / "megaman2_candidate_v2_manual_eval_20261125.json"
PRODUCTION_REPORT = BASE / "megaman2_production_manual_eval_20261125.json"
MANIFEST_OUT = BASE / "megaman2_delivery_manifest_v2_manual_20261125.json"
LIVE_JSON = BASE / "megaman2_final_live_queries_v2_manual_20261125.json"
LIVE_LOG = M.CANDIDATE_DIR / "qc" / "final_live_queries_v2_manual_20261125.jsonl"
CANDIDATE_AUDIT = M.CANDIDATE_DIR / "qc" / "candidate_audit_v2_manual_20261125.json"
LOG_DIR = TOOLS / "_task_logs"
FULL_LOG = LOG_DIR / "mm2_manual_full_selftest_20261125_locked.txt"
KB_LOG = LOG_DIR / "mm2_manual_kb_selftest_20261125_final.txt"
SOURCES_LOG = LOG_DIR / "mm2_manual_sources_selftest_20261125_final.txt"
CROSS_LOG = LOG_DIR / "mm2_manual_cross_platform_selftest_20261125_final.txt"
BASE_AUDIT = LOG_DIR / "mm2_manual_kb_audit_base_20261125_locked.json"
HYBRID_AUDIT = LOG_DIR / "mm2_manual_kb_audit_hybrid_20261125_locked.json"
CODE_BEFORE = LOG_DIR / "mm2_manual_code_before_final_regression_20261125.sha256"
CODE_AFTER = LOG_DIR / "mm2_manual_code_after_final_regression_20261125.sha256"
TEMP_MANUAL = Path("C:/Users/Administrator/.qoder/tmp/megaman2_manual_20261125")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(path):
    p = Path(path)
    if not p.is_file():
        return {"present": False}
    st = p.stat()
    return {"present": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": sha(p)}


def atomic_text(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def artifact(path):
    p = Path(path).resolve()
    return {"path": str(p), "bytes": p.stat().st_size, "sha256": sha(p)}


def gate_count(path, pattern):
    match = re.search(pattern, Path(path).read_text(encoding="utf-8", errors="replace"))
    if not match:
        raise RuntimeError(f"missing gate count: {path}")
    return {"pass": int(match.group(1)), "total": int(match.group(2))}


def parse_code_hashes(path):
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([0-9a-f]{64}) [ *](.+)$", line)
        if not match:
            raise RuntimeError(f"invalid sha256 line: {line!r}")
        out[match.group(2)] = match.group(1)
    return out


def current_code_hashes():
    return {f"taspipe/{p.name}": sha(p) for p in sorted(TOOLS.glob("taspipe/*.py"))}


def compact(result):
    return {
        "status": result.get("status"),
        "refusal": result.get("refusal"),
        "reason_code": result.get("reason_code"),
        "backend": result.get("backend"),
        "index_used": result.get("index_used"),
        "index_sha256": result.get("index_sha256"),
        "answer_text": result.get("answer_text", ""),
        "selected_evidence": result.get("selected_evidence") or [],
        "candidate_only": result.get("candidate_only"),
        "whole_game_knowledge_base": result.get("whole_game_knowledge_base"),
        "production_route_wired": result.get("production_route_wired"),
    }


def audit_summary(report):
    return {
        "status": report["status"],
        "counts": report["counts"],
        "checks": [{"check_id": c["check_id"], "verdict": c["verdict"],
                    "reason": c["reason"], "detail_count": len(c["detail"])}
                   for c in report["checks"]],
    }


def main():
    build = load(BUILD_REPORT)
    isolated = load(ISOLATED_REPORT)
    production = load(PRODUCTION_REPORT)
    frozen = load(M.FROZEN_QUESTIONS)
    manual = load(M.CANDIDATE_DIR / "manual_source.json")
    contract = load(M.CONTRACT_PATH)
    scope = load(M.CANDIDATE_DIR / "scope.json")
    index = K.load_index(M.INDEX_PATH)
    chunks = {c["chunk_id"]: c for c in index["chunks"]}
    production_registry = S.load_registry(S.REG_JSON)
    production_source = next(s for s in production_registry["sources"]
                             if s["source_id"] == M.PRODUCTION_SOURCE_ID)
    production_evidence = [Path(p).as_posix() for p in production_source["evidence"]]
    protected = [Path(p) for p in production["isolation"]["after"]]
    before = {str(p): snapshot(p) for p in protected}
    checks = {}
    counts = {
        "total": len(frozen["questions"]),
        "strict_pass": sum(q["expect"] == "strict_pass" for q in frozen["questions"]),
        "weak": sum(q["expect"] == "weak" for q in frozen["questions"]),
        "refuse": sum(q["expect"] == "refuse" for q in frozen["questions"]),
    }

    checks["candidate_hash_matches"] = (
        sha(M.INDEX_PATH) == contract["index_sha256"] == M.expected_index_sha256()
        == frozen["candidate_index_sha256"])
    checks["frozen_counts_match"] = (
        frozen.get("status") == "frozen" and counts == frozen["expected_counts"]
        and len({q["id"] for q in frozen["questions"]}) == counts["total"])
    checks["frozen_gold_chunks_valid"] = all(
        q.get("gold") is None if q["expect"] == "refuse" else
        q["gold"]["anchor_chunk"] in chunks
        and q["gold"]["path_contains"] in chunks[q["gold"]["anchor_chunk"]]["path"]
        and chunks[q["gold"]["anchor_chunk"]]["line_start"] <= q["gold"]["line_end"]
        and chunks[q["gold"]["anchor_chunk"]]["line_end"] >= q["gold"]["line_start"]
        and chunks[q["gold"]["anchor_chunk"]]["source_id"] == q["source_id"]
        and chunks[q["gold"]["anchor_chunk"]]["revision"] == q["revision"]
        for q in frozen["questions"])
    checks["manual_gold_chunks_valid"] = all(
        chunks[q["gold"]["anchor_chunk"]]["source_id"] == M.MANUAL_SOURCE_ID
        and chunks[q["gold"]["anchor_chunk"]]["revision"] == M.MANUAL_REVISION
        for q in frozen["questions"] if q.get("manual_pages"))
    checks["manual_metadata_valid"] = (
        manual.get("full_manual_stored_in_candidate") is False
        and manual.get("pdf_pages") == 20
        and len(manual.get("excerpts") or []) == 8
        and all(e.get("scan_visually_read") is True for e in manual["excerpts"]))
    checks["manual_excerpt_hashes_valid"] = all(
        sha(ROOT / e["target"]) == e["target_sha256"] for e in manual["excerpts"])
    checks["no_full_manual_in_candidate"] = not list(M.CANDIDATE_DIR.rglob("*.pdf"))
    checks["candidate_counts_match_build"] = (
        len(index["chunks"]) == build["index_chunks"] == 24
        and len({c["path"] for c in index["chunks"]}) == build["build"]["files_indexed"] == 18
        and build["revision_counts"][M.MANUAL_REVISION] == 9)
    checks["candidate_scope_is_not_whole_game"] = (
        scope.get("production_route_wired") is True
        and scope.get("production_defaults_unchanged") is True
        and "整款游戏内容知识库" in scope.get("not_covered", []))

    candidate_audit = K.audit(map_path=M.MAP_PATH, index_path=M.INDEX_PATH,
                              reg=S.load_registry(M.REGISTRY_PATH))
    atomic_text(CANDIDATE_AUDIT, json.dumps(candidate_audit, ensure_ascii=False, indent=2) + "\n")
    base_audit = load(BASE_AUDIT)
    hybrid_audit = load(HYBRID_AUDIT)
    checks["candidate_audit_no_fail"] = (
        candidate_audit["counts"]["fail"] == 0
        and {c["check_id"] for c in candidate_audit["checks"] if c["verdict"] == "inconclusive"}
        == {"authoritative_ready"})
    checks["base_audit_no_fail"] = (
        base_audit["counts"]["fail"] == 0 and base_audit["counts"]["inconclusive"] == 3)
    checks["hybrid_audit_no_fail"] = (
        hybrid_audit["counts"]["fail"] == 0 and hybrid_audit["counts"]["inconclusive"] == 3)

    gates = {
        "project": gate_count(FULL_LOG, r"SELFTEST OK (\d+)/(\d+)"),
        "kb": gate_count(KB_LOG, r"KB_SELFTEST OK (\d+)/(\d+)"),
        "sources": gate_count(SOURCES_LOG, r"SOURCES_SELFTEST OK (\d+)/(\d+)"),
        "cross_platform": gate_count(CROSS_LOG, r"CROSS_PLATFORM_SELFTEST OK (\d+)/(\d+)"),
    }
    checks["all_regression_gates_green"] = all(g["pass"] == g["total"] for g in gates.values())
    kb_log_text = KB_LOG.read_text(encoding="utf-8", errors="replace")
    checks["new_visible_gates_present"] = all(
        f"知识库 [{n}]" in kb_log_text for n in (290, 291, 292))
    expected_code = parse_code_hashes(CODE_AFTER)
    checks["locked_regression_code_stable"] = (
        CODE_BEFORE.read_bytes() == CODE_AFTER.read_bytes()
        and current_code_hashes() == expected_code)

    checks["isolated_evaluation_all_ok"] = (
        isolated.get("all_ok") is True and isolated.get("isolation", {}).get("ok") is True
        and all(v["ok"] == v["total"] for v in isolated["summary"].values()))
    checks["production_evaluation_all_ok"] = (
        production.get("status") == "pass"
        and production.get("production_all_ok") is True
        and production.get("failure_close_all_ok") is True
        and production.get("legacy_candidate_regression", {}).get("ok") is True
        and production.get("isolation", {}).get("ok") is True
        and all(v["ok"] == v["total"] for v in production["summary"].values()))
    checks["evaluation_used_no_external_model"] = (
        isolated.get("external_generative_model_calls") == 0
        and isolated.get("paid_api_calls") == 0
        and production.get("external_generative_model_calls") == 0
        and production.get("paid_api_calls") == 0)

    live_rows = []
    probes = []
    manual_specs = [
        ("controls", "洛克人2美版官方说明书里跳跃和射击：A 键和 B 键分别控制什么？",
         "mm2_manual_controls_20261125.txt"),
        ("energy", "洛克人2官方说明书里 energy crystal 有什么作用，怎么使用？",
         "mm2_manual_energy_20261125.txt"),
        ("metal_blade", "洛克人2官方说明书里 Metal Blade 的投掷方向、数量和用途是什么？",
         "mm2_manual_weapons_20261125.txt"),
        ("crash_bomber", "洛克人2官方说明书里 Crash Bomber 有什么用途？",
         "mm2_manual_weapons_20261125.txt"),
    ]
    for name, question, expected_path in manual_specs:
        result = K.query_auto(question, topk=8, fragment_policy="strict",
                              log_sink=live_rows.append,
                              log_context={"entry_point": "mm2-v2-manual-final-live"})
        selected = result.get("selected_evidence") or []
        ok = (
            result.get("status") == "pass"
            and result.get("backend") == "megaman2"
            and result.get("index_used") == "index.json"
            and result.get("index_sha256") == M.expected_index_sha256()
            and result.get("candidate_only") is True
            and result.get("whole_game_knowledge_base") is False
            and result.get("production_route_wired") is True
            and len(selected) == 1
            and selected[0].get("source_id") == M.MANUAL_SOURCE_ID
            and selected[0].get("revision") == M.MANUAL_REVISION
            and selected[0].get("status") == "verified_read"
            and selected[0].get("authority") == "authoritative"
            and expected_path in selected[0].get("locator", "")
            and (selected[0].get("fragment_provenance") or {}).get("eligible") is True)
        checks[f"live_manual_{name}"] = ok
        probes.append({"id": f"manual_{name}", "q": question, "ok": ok,
                       "result": compact(result)})

    technical_q = "洛克人2 的 walking speed 是什么？"
    technical = K.query_auto(technical_q, topk=8, fragment_policy="strict",
                             log_sink=live_rows.append,
                             log_context={"entry_point": "mm2-v2-manual-final-live"})
    technical_selected = technical.get("selected_evidence") or []
    technical_ok = (
        technical.get("status") == "pass"
        and technical.get("backend") == "megaman2"
        and technical.get("index_sha256") == production["production_index_sha256"]
        and technical.get("candidate_only") is False
        and technical.get("whole_game_knowledge_base") is False
        and technical.get("production_route_wired") is True
        and len(technical_selected) == 1
        and technical_selected[0].get("source_id") == M.PRODUCTION_SOURCE_ID
        and technical_selected[0].get("revision") == M.TECHNICAL_REVISION
        and technical_selected[0].get("status") == "verified_read"
        and technical_selected[0].get("authority") == "authoritative"
        and any(p in technical_selected[0].get("locator", "") for p in production_evidence)
        and "01.60" in technical.get("answer_text", ""))
    checks["live_technical_production"] = technical_ok
    probes.append({"id": "technical_production", "q": technical_q, "ok": technical_ok,
                   "result": compact(technical)})

    refused_q = "洛克人2 日版官方说明书里 Crash Bomber 有什么用途？"
    refused = K.query_auto(refused_q, topk=8, fragment_policy="strict",
                           log_sink=live_rows.append,
                           log_context={"entry_point": "mm2-v2-manual-final-live"})
    refused_ok = (
        refused.get("status") != "pass"
        and refused.get("refusal") == "version_not_collected"
        and not refused.get("hits") and not refused.get("selected_evidence"))
    checks["live_jp_manual_refused"] = refused_ok
    probes.append({"id": "jp_manual_refused", "q": refused_q, "ok": refused_ok,
                   "result": compact(refused)})

    multi_q = next(q["q"] for q in frozen["questions"] if q["id"] == "MM406")
    multi = K.query_auto(multi_q, topk=8, fragment_policy="strict",
                         log_sink=live_rows.append,
                         log_context={"entry_point": "mm2-v2-manual-final-live"})
    domain = next((d for d in multi.get("domain_results") or []
                   if d.get("domain") == "megaman2"), {})
    domain_selected = domain.get("selected_evidence") or []
    multi_ok = (
        multi.get("status") == "inconclusive"
        and multi.get("refusal") == "multi_domain_needs_split"
        and not multi.get("selected_evidence")
        and domain.get("status") == "pass"
        and len(domain_selected) == 1
        and domain_selected[0].get("source_id") == M.PRODUCTION_SOURCE_ID
        and domain_selected[0].get("revision") == M.TECHNICAL_REVISION
        and domain.get("candidate_only") is False
        and domain.get("production_route_wired") is True
        and domain.get("whole_game_knowledge_base") is False)
    checks["live_multi_domain_not_merged"] = multi_ok
    probes.append({"id": "multi_domain_not_merged", "q": multi_q, "ok": multi_ok,
                   "result": compact(multi), "megaman2_domain": compact(domain)})

    atomic_text(LIVE_LOG, "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
                                  for r in live_rows))
    atomic_text(LIVE_JSON, json.dumps({"all_ok": all(p["ok"] for p in probes),
                                      "probes": probes}, ensure_ascii=False, indent=2) + "\n")
    after = {str(p): snapshot(p) for p in protected}
    changed_since_production = [p for p in before
                                if before[p] != production["isolation"]["after"].get(p)]
    changed_during_finalization = [p for p in before if before[p] != after[p]]
    checks["shared_state_unchanged_since_production_eval"] = not changed_since_production
    checks["shared_state_unchanged_during_finalization"] = not changed_during_finalization
    checks["code_unchanged_during_finalization"] = current_code_hashes() == expected_code

    if not all(checks.values()):
        atomic_text(MANIFEST_OUT, json.dumps({
            "schema_version": 2, "status": "finalization_failed", "all_ok": False,
            "checks": checks, "gates": gates,
            "changed_since_production_eval": changed_since_production,
            "changed_during_finalization": changed_during_finalization,
        }, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"all_ok": False, "checks": checks, "gates": gates,
                          "changed_since_production_eval": changed_since_production,
                          "changed_during_finalization": changed_during_finalization},
                         ensure_ascii=False, indent=2))
        return 1

    cleanup = {"removed": False, "already_absent": False, "path": str(TEMP_MANUAL),
               "file_count": 0, "total_bytes": 0, "exists_after": TEMP_MANUAL.exists()}
    if TEMP_MANUAL.exists():
        expected_temp = Path("C:/Users/Administrator/.qoder/tmp/megaman2_manual_20261125").resolve()
        if TEMP_MANUAL.resolve() != expected_temp or not TEMP_MANUAL.is_dir():
            raise RuntimeError("temporary manual path changed; refusing cleanup")
        official = TEMP_MANUAL / "nintendo_CLV-P-NABBE.pdf"
        archive = TEMP_MANUAL / "archive_Mega-Man-2-Game-Manual.pdf"
        if sha(official) != manual["downloaded_pdf_sha256"]:
            raise RuntimeError("temporary official manual PDF hash mismatch; refusing cleanup")
        if sha(archive) != manual["archive_pdf_sha256"]:
            raise RuntimeError("temporary archive manual PDF hash mismatch; refusing cleanup")
        expected_names = {"nintendo_CLV-P-NABBE.pdf", "archive_Mega-Man-2-Game-Manual.pdf",
                          "nintendo_contact_sheet.png"}
        expected_names.update(f"nintendo_page_{n:02d}.png" for n in range(1, 21))
        files = [p for p in TEMP_MANUAL.rglob("*") if p.is_file()]
        if {p.name for p in files} != expected_names or len(files) != len(expected_names):
            raise RuntimeError("temporary manual inventory changed; refusing cleanup")
        cleanup.update({"removed": True, "file_count": len(files),
                        "total_bytes": sum(p.stat().st_size for p in files),
                        "official_pdf_sha256_verified": True,
                        "archive_pdf_sha256_verified": True})
        shutil.rmtree(TEMP_MANUAL)
    else:
        cleanup["already_absent"] = True
    cleanup["exists_after"] = TEMP_MANUAL.exists()
    checks["temporary_manual_removed"] = not cleanup["exists_after"]
    checks["code_still_unchanged_after_cleanup"] = current_code_hashes() == expected_code

    artifact_paths = [
        M.INDEX_PATH, M.MAP_PATH, M.REGISTRY_PATH, M.CONTRACT_PATH,
        M.CANDIDATE_DIR / "scope.json", M.CANDIDATE_DIR / "manual_source.json",
        M.FROZEN_QUESTIONS, BUILD_REPORT, ISOLATED_REPORT,
        BASE / "megaman2_candidate_v2_manual_eval_20261125.md", PRODUCTION_REPORT,
        CANDIDATE_AUDIT, LIVE_JSON, LIVE_LOG,
        M.CANDIDATE_DIR / "qc" / "isolated_eval_query_log_20261125.jsonl",
        M.CANDIDATE_DIR / "qc" / "production_route_query_log_20261125.jsonl",
        M.CANDIDATE_DIR / "qc" / "legacy_candidate_regression_query_log_20261125.jsonl",
        BASE / "eval_megaman2_candidate_v2_manual_20261125.py",
        BASE / "eval_megaman2_production_manual_20261125.py", Path(__file__).resolve(),
        FULL_LOG, KB_LOG, SOURCES_LOG, CROSS_LOG, BASE_AUDIT, HYBRID_AUDIT,
        CODE_BEFORE, CODE_AFTER,
    ]
    artifact_paths += sorted((M.CANDIDATE_DIR / "evidence").glob("*.txt"))
    artifact_paths += [BASE / "megaman2_candidate_20261125" / name for name in (
        "index.json", "corpus_map.json", "sources.json", "contract.json",
        "selftest_eval_megaman2_20261125.py")]
    artifacts = {str(Path(p).relative_to(ROOT).as_posix()): artifact(p)
                 for p in sorted(set(artifact_paths), key=lambda x: str(x))}
    code_paths = {
        "kb": TOOLS / "taspipe" / "kb.py",
        "kb_route": TOOLS / "taspipe" / "kb_route.py",
        "kb_megaman2": TOOLS / "taspipe" / "kb_megaman2.py",
        "kb_answer": TOOLS / "taspipe" / "kb_answer.py",
        "schema": TOOLS / "taspipe" / "schema.py",
        "kb_selftest_gates": TOOLS / "taspipe" / "kb_selftest_gates.py",
        "sources_selftest_gates": TOOLS / "taspipe" / "sources_selftest_gates.py",
        "cross_platform_selftest_gates": TOOLS / "taspipe" / "cross_platform_selftest_gates.py",
        "selftest": TOOLS / "taspipe" / "selftest.py",
        "finalizer": Path(__file__).resolve(),
    }
    all_ok = all(checks.values())
    manifest = {
        "schema_version": 2,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task": "megaman2_official_manual_candidate_v2",
        "status": "pass" if all_ok else "fail",
        "all_ok": all_ok,
        "checks": checks,
        "candidate_only": True,
        "whole_game_knowledge_base": False,
        "candidate": {
            "domain": M.DOMAIN,
            "production_domain": M.PRODUCTION_DOMAIN,
            "backend": "megaman2",
            "revision": M.MANUAL_REVISION,
            "index": str(M.INDEX_PATH),
            "index_sha256": M.expected_index_sha256(),
            "chunks": len(index["chunks"]),
            "indexed_files": len({c["path"] for c in index["chunks"]}),
            "manual_excerpt_files": len(manual["excerpts"]),
            "manual_chunks": build["revision_counts"][M.MANUAL_REVISION],
            "frozen_questions": str(M.FROZEN_QUESTIONS),
            "frozen_questions_sha256": sha(M.FROZEN_QUESTIONS),
            "question_counts": counts,
        },
        "manual_provenance": {
            "source_id": M.MANUAL_SOURCE_ID,
            "official_pdf": manual["official_pdf"],
            "archive_item": manual["archive_item"],
            "archive_pdf": manual["archive_pdf"],
            "official_pdf_sha1": manual["official_pdf_sha1"],
            "downloaded_pdf_sha256": manual["downloaded_pdf_sha256"],
            "downloaded_pdf_bytes": manual["downloaded_pdf_bytes"],
            "archive_pdf_sha256": manual["archive_pdf_sha256"],
            "archive_pdf_bytes": manual["archive_pdf_bytes"],
            "pdf_pages": manual["pdf_pages"],
            "short_excerpts": len(manual["excerpts"]),
            "full_manual_stored_in_candidate": False,
            "verification": manual["verification"],
            "typed_transcription_role": manual["typed_transcription_role"],
        },
        "isolated_evaluation": {
            "all_ok": isolated["all_ok"], "summary": isolated["summary"],
            "query_count": isolated["query_count"], "report": str(ISOLATED_REPORT),
            "isolation": {k: v for k, v in isolated["isolation"].items()
                          if k not in ("before", "after")},
        },
        "production_evaluation": {
            "all_ok": production["production_all_ok"],
            "summary": production["summary"],
            "production_query_count": production["production_query_count"],
            "failure_close_query_count": production["failure_close_query_count"],
            "failure_close_all_ok": production["failure_close_all_ok"],
            "legacy_candidate_regression": production["legacy_candidate_regression"],
            "report": str(PRODUCTION_REPORT),
            "query_logs": production["query_logs"],
        },
        "regression": {
            "gates": gates,
            "locked_code_hash_stable": checks["locked_regression_code_stable"],
            "new_visible_gates": [290, 291, 292],
        },
        "audits": {
            "candidate": audit_summary(candidate_audit),
            "base": audit_summary(base_audit),
            "hybrid": audit_summary(hybrid_audit),
            "note": "0 fail；inconclusive 是未覆盖版本、二手继承、撤回片段或 reference-only 分区没有权威正文，不冒充权威全覆盖。",
        },
        "shared_state_after_all_regressions": {
            "unchanged_since_production_eval": not changed_since_production,
            "unchanged_during_finalization": not changed_during_finalization,
            "changed_paths": changed_since_production,
            "snapshots": after,
        },
        "final_live_queries": {
            "all_ok": all(p["ok"] for p in probes), "json": str(LIVE_JSON),
            "log": str(LIVE_LOG), "log_lines": len(live_rows), "probes": probes,
        },
        "temporary_research_cleanup": cleanup,
        "code_sha256": {name: sha(path) for name, path in code_paths.items()},
        "artifacts": artifacts,
        "remaining": [
            "这只是洛克人2候选子域，不是整款游戏知识库",
            "官方说明书只保存8个带页码短摘录，完整手册未进入候选或交付目录",
            "PAL、日版、韩版及JP版本未验证，不能跨版照用",
            "美版ROM技术题仍走生产索引；说明书证据不能冒充ROM身份证明",
            "全部敌人、关卡、隐藏要素与出招表尚未完整覆盖",
            "本地内存字典、标题目录和TAS出版物仍是reference_only",
        ],
        "external_generative_model_calls": 0,
        "paid_api_calls": 0,
    }
    atomic_text(MANIFEST_OUT, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"all_ok": all_ok, "gates": gates,
                      "live_queries": manifest["final_live_queries"]["all_ok"],
                      "cleanup": cleanup, "manifest": str(MANIFEST_OUT)},
                     ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
