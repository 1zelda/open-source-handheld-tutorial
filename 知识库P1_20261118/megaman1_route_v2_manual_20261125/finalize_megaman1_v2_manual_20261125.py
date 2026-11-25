# -*- coding: utf-8 -*-
"""洛克人1 v2 手册候选最终收口：真实查询、回归核账、隔离与临时件清理。"""
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT / "_工具脚本"))
sys.path.insert(0, str(ROOT))

from taspipe import kb as K
from taspipe import kb_megaman1 as M

ROUTE_REPORT = HERE / "eval_report.json"
ISOLATED_REPORT = BASE / "megaman1_candidate_v2_manual_eval_20261125.json"
FULL_DOMAIN_REPORT = HERE / "full_domain_v2_manual_20261125.json"
BLIND_REPORT = HERE / "blind_eval_v2_manual_20261125.json"
SCOPE_OUT = HERE / "scope_production_v2_manual_20261125.json"
MANIFEST_OUT = HERE / "final_manifest_v2_manual_20261125.json"
LIVE_JSON = HERE / "final_live_queries_v2_manual_20261125.json"
LIVE_LOG = HERE / "final_live_queries_v2_manual_20261125.jsonl"
TEMP_MANUAL = Path("C:/Users/Administrator/.qoder/tmp/megaman1_manual_20261125")
MANUAL_SOURCE_ID = "archive_mega_man_nes_us_manual"


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
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def candidate_part(result):
    if result.get("backend") == "megaman1_candidate":
        return result
    for row in result.get("domain_results") or []:
        if row.get("domain") == M.PRODUCTION_DOMAIN:
            return row
    return {}


def compact(result):
    candidate = candidate_part(result)
    selected = candidate.get("selected_evidence") or result.get("selected_evidence") or []
    return {
        "status": result.get("status"),
        "refusal": result.get("refusal"),
        "reason_code": result.get("reason_code"),
        "reason": result.get("reason"),
        "backend": result.get("backend"),
        "index_used": result.get("index_used"),
        "index_sha256": result.get("index_sha256"),
        "answer_text": result.get("answer_text", ""),
        "selected_evidence": selected,
        "candidate_only": result.get("candidate_only"),
        "whole_game_knowledge_base": result.get("whole_game_knowledge_base"),
        "production_route_wired": result.get("production_route_wired"),
    }


def gate_count(log_path, pattern):
    text = Path(log_path).read_text(encoding="utf-8")
    match = re.search(pattern, text)
    if not match:
        raise RuntimeError(f"missing gate count: {log_path}")
    return {"pass": int(match.group(1)), "total": int(match.group(2))}


def topic_gate_count(log_path):
    text = Path(log_path).read_text(encoding="utf-8")
    total = re.search(r"自检合计 (\d+) 格", text)
    passed = re.search(r"PASS (\d+) / FAIL 0", text)
    if not total or not passed:
        raise RuntimeError(f"missing topic gate count: {log_path}")
    return {"pass": int(passed.group(1)), "total": int(total.group(1))}


def artifact(path):
    p = Path(path)
    return {"path": str(p.resolve()), "bytes": p.stat().st_size, "sha256": sha(p)}


def main():
    route = load(ROUTE_REPORT)
    isolated = load(ISOLATED_REPORT)
    full_domain = load(FULL_DOMAIN_REPORT)
    blind = load(BLIND_REPORT)
    frozen = load(M.FROZEN_QUESTIONS)
    manual = load(M.CANDIDATE_DIR / "manual_source.json")
    index = K.load_index(M.INDEX_PATH)
    chunks = {c["chunk_id"]: c for c in index["chunks"]}
    checks = {}

    checks["route_acceptance_all_ok"] = route.get("all_ok") is True and all(route["checks"].values())
    checks["isolated_evaluation_all_ok"] = isolated.get("all_ok") is True
    checks["frozen_counts_match"] = {
        "total": len(frozen["questions"]),
        "strict_pass": sum(q["expect"] == "strict_pass" for q in frozen["questions"]),
        "refuse": sum(q["expect"] == "refuse" for q in frozen["questions"]),
    } == frozen["expected_counts"]
    checks["candidate_hash_matches"] = sha(M.INDEX_PATH) == M.expected_index_sha256()
    checks["manual_gold_chunks_valid"] = all(
        q["gold"]["anchor_chunk"] in chunks
        and chunks[q["gold"]["anchor_chunk"]]["source_id"] == MANUAL_SOURCE_ID
        for q in frozen["questions"] if q.get("manual_pages"))
    checks["manual_metadata_valid"] = (
        manual.get("full_manual_stored_in_candidate") is False
        and manual.get("pdf_pages") == 10
        and len(manual.get("excerpts") or []) == 8
        and all(e.get("scan_visually_read") is True for e in manual["excerpts"]))
    checks["manual_excerpt_hashes_valid"] = all(
        sha(ROOT / e["target"]) == e["target_sha256"] for e in manual["excerpts"])
    checks["no_full_manual_in_delivery"] = (
        not list(M.CANDIDATE_DIR.rglob("*.pdf")) and not list(HERE.rglob("*.pdf")))

    gates = {
        "kb": gate_count(HERE / "kb_selftest_v2_manual_20261125.log", r"KB_SELFTEST OK (\d+)/(\d+)"),
        "topic": topic_gate_count(HERE / "topic_selftest_v2_manual_20261125.log"),
        "p1_route_intent": gate_count(HERE / "p1_selftest_v2_manual_20261125.log", r"SELFTEST (\d+)/(\d+)"),
        "full_domain": {"pass": full_domain["summary"]["ok"], "total": full_domain["summary"]["total"]},
        "blind_26": {"pass": blind["summary"]["ok"], "total": blind["summary"]["total"]},
        "project": gate_count(HERE / "project_selftest_v2_manual_20261125.log", r"SELFTEST OK (\d+)/(\d+)"),
    }
    checks["all_regression_gates_green"] = all(g["pass"] == g["total"] for g in gates.values())
    checks["new_visible_gates_present"] = all(
        label in (HERE / "kb_selftest_v2_manual_20261125.log").read_text(encoding="utf-8")
        for label in ("知识库 [287]", "知识库 [288]", "知识库 [289]"))
    checks["blind_isolation_ok"] = blind["isolation"]["ok"] is True

    protected_after = route["isolation"]["after"]
    before_live = {p: snapshot(p) for p in protected_after}
    live_rows = []
    probes = []
    specs = [
        ("controls", "洛克人1官方说明书里 A 键和 B 键分别控制什么动作？", "mm1_manual_controls_20261125.txt"),
        ("energy", "洛克人1 Energy Meter 监测的能量水平，受击与能量胶囊分别有什么影响？", "mm1_manual_energy_20261125.txt"),
        ("magnet_beam", "洛克人1官方说明书里 Magnet Beam 在哪个关卡出现，取得后能做什么？", "mm1_manual_magnet_beam_20261125.txt"),
        ("robot_masters", "洛克人1官方说明书里六名 Robot Master 各自的设计用途或专长是什么？", "mm1_manual_robot_masters_20261125.txt"),
    ]
    for name, q, expected_path in specs:
        result = K.query_auto(q, topk=5, fragment_policy="strict", log_sink=live_rows.append,
                              log_context={"entry_point": "mm1-v2-manual-final-live"})
        selected = candidate_part(result).get("selected_evidence") or []
        ok = (result.get("status") == "pass"
              and result.get("backend") == "megaman1_candidate"
              and result.get("index_sha256") == M.expected_index_sha256()
              and result.get("candidate_only") is True
              and result.get("whole_game_knowledge_base") is False
              and len(selected) == 1
              and selected[0].get("source_id") == MANUAL_SOURCE_ID
              and selected[0].get("status") == "verified_read"
              and selected[0].get("authority") == "authoritative"
              and expected_path in selected[0].get("locator", "")
              and (selected[0].get("fragment_provenance") or {}).get("eligible") is True)
        checks[f"live_{name}"] = ok
        probes.append({"id": name, "q": q, "ok": ok, "result": compact(result)})
    refused = K.query_auto("洛克人1 PAL-B 版的坐标表是否可以直接当作 NTSC 美版结论？",
                           topk=5, log_sink=live_rows.append,
                           log_context={"entry_point": "mm1-v2-manual-final-live"})
    checks["live_pal_refused"] = (
        refused.get("status") != "pass"
        and refused.get("reason_code") == "version_not_collected"
        and not refused.get("selected_evidence")
        and not candidate_part(refused).get("selected_evidence"))
    probes.append({"id": "pal_refused", "q": "洛克人1 PAL-B 版的坐标表是否可以直接当作 NTSC 美版结论？",
                   "ok": checks["live_pal_refused"], "result": compact(refused)})
    atomic_text(LIVE_LOG, "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
                                  for r in live_rows))
    atomic_text(LIVE_JSON, json.dumps({"all_ok": all(p["ok"] for p in probes), "probes": probes},
                                      ensure_ascii=False, indent=2) + "\n")
    after_live = {p: snapshot(p) for p in protected_after}
    changed_since_route = [p for p in before_live if before_live[p] != protected_after[p]]
    changed_during_live = [p for p in before_live if before_live[p] != after_live[p]]
    checks["shared_state_unchanged_since_route_acceptance"] = not changed_since_route
    checks["shared_state_unchanged_during_final_live_queries"] = not changed_during_live

    if not all(checks.values()):
        atomic_text(MANIFEST_OUT, json.dumps({
            "schema_version": 2, "status": "finalization_failed", "all_ok": False,
            "checks": checks, "gates": gates, "changed_since_route": changed_since_route,
            "changed_during_live": changed_during_live,
        }, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"all_ok": False, "checks": checks, "gates": gates,
                          "changed_since_route": changed_since_route,
                          "changed_during_live": changed_during_live}, ensure_ascii=False, indent=2))
        return 1

    cleanup = {"removed": False, "path": str(TEMP_MANUAL), "file_count": 0, "total_bytes": 0}
    if TEMP_MANUAL.exists():
        expected_temp = Path("C:/Users/Administrator/.qoder/tmp/megaman1_manual_20261125").resolve()
        if TEMP_MANUAL.resolve() != expected_temp or not TEMP_MANUAL.is_dir():
            raise RuntimeError("temporary manual path changed; refusing cleanup")
        pdf = TEMP_MANUAL / "Mega-Man-Game-Manual.pdf"
        if not pdf.is_file() or sha(pdf) != manual["downloaded_pdf_sha256"]:
            raise RuntimeError("temporary manual PDF hash mismatch; refusing cleanup")
        files = [p for p in TEMP_MANUAL.rglob("*") if p.is_file()]
        cleanup.update({"removed": True, "file_count": len(files),
                        "total_bytes": sum(p.stat().st_size for p in files),
                        "pdf_sha256_verified": True})
        shutil.rmtree(TEMP_MANUAL)
    cleanup["exists_after"] = TEMP_MANUAL.exists()
    checks["temporary_manual_removed"] = cleanup["removed"] and not cleanup["exists_after"]

    scope = {
        "status": "production_candidate_route_wired_v2_manual",
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "revision": M.REVISION,
        "production_domain": M.PRODUCTION_DOMAIN,
        "backend": "megaman1_candidate",
        "production_entry_point": "taspipe.kb.query_auto",
        "candidate_only": True,
        "whole_game_knowledge_base": False,
        "candidate_index": str(M.INDEX_PATH.relative_to(ROOT).as_posix()),
        "candidate_index_sha256": M.expected_index_sha256(),
        "frozen_questions": str(M.FROZEN_QUESTIONS.relative_to(ROOT).as_posix()),
        "frozen_questions_sha256": sha(M.FROZEN_QUESTIONS),
        "question_counts": frozen["expected_counts"],
        "coverage": [
            "对象RAM表", "坐标轴与小数位置", "BizHawk内存写机制", "本机武器RAM实测", "本机对象表定位实测",
            "官方说明书操作按键", "官方说明书选关流程", "官方说明书能量与奖励道具",
            "官方说明书Magnet Beam", "官方说明书Robot Master身份", "官方说明书进度奖励与得分",
        ],
        "reference_only_coverage": ["FM2导入社区流程", "segmented TAS通用术语"],
        "not_covered": [
            "整款游戏内容知识库", "全部敌人、关卡与隐藏要素", "PAL-B与其他版本跨版等价",
            "目标时刻存档点与续作流程", "角色创建系统（官方说明书无证，拒答）",
        ],
        "manual_source": {
            "source_id": MANUAL_SOURCE_ID,
            "archive_item": manual["archive_item"],
            "original_pdf_sha1": manual["original_pdf_sha1"],
            "downloaded_pdf_sha256": manual["downloaded_pdf_sha256"],
            "pdf_pages": manual["pdf_pages"],
            "short_excerpts": len(manual["excerpts"]),
            "full_manual_stored_in_candidate": False,
            "typed_transcription_role": manual["typed_transcription_role"],
        },
        "route_boundaries": {
            "explicit_alias": "candidate",
            "explicit_revision_without_alias": "candidate",
            "series_generic_without_installment": "ambiguous_series",
            "other_installment": "not_borrowed",
            "pal_or_european_version": "version_not_collected",
            "multi_domain": "domain_local_evidence_only; outer inconclusive without evidence",
            "missing_or_invalid_candidate_index": "fail_closed_without_production_fallback",
        },
        "production_defaults_unchanged": True,
        "external_generative_model_calls": 0,
        "paid_api_calls": 0,
    }
    atomic_text(SCOPE_OUT, json.dumps(scope, ensure_ascii=False, indent=2) + "\n")

    artifact_paths = [p for p in HERE.iterdir() if p.is_file() and p.name != MANIFEST_OUT.name]
    artifact_paths += [M.INDEX_PATH, M.MAP_PATH, M.REGISTRY_PATH,
                       M.CANDIDATE_DIR / "manual_source.json", M.CANDIDATE_DIR / "scope.json",
                       M.FROZEN_QUESTIONS, ISOLATED_REPORT,
                       BASE / "megaman1_candidate_v2_manual_eval_20261125.md",
                       M.CANDIDATE_DIR / "qc" / "isolated_eval_query_log_20261125.jsonl",
                       M.CANDIDATE_DIR / "qc" / "production_route_v2_query_log_20261125.jsonl"]
    artifact_paths += sorted((M.CANDIDATE_DIR / "evidence").glob("*.txt"))
    artifact_paths += [BASE / "megaman1_candidate_20261125" / name
                       for name in ("index.json", "corpus_map.json", "sources.json")]
    artifacts = {str(Path(p).relative_to(ROOT).as_posix()): artifact(p)
                 for p in sorted(set(artifact_paths), key=lambda x: str(x))}
    code_paths = {
        "kb": ROOT / "_工具脚本" / "taspipe" / "kb.py",
        "kb_route": ROOT / "_工具脚本" / "taspipe" / "kb_route.py",
        "kb_megaman1": ROOT / "_工具脚本" / "taspipe" / "kb_megaman1.py",
        "kb_selftest_gates": ROOT / "_工具脚本" / "taspipe" / "kb_selftest_gates.py",
        "movie_converters": ROOT / "_工具脚本" / "taspipe" / "movie_converters.py",
        "selftest": ROOT / "_工具脚本" / "taspipe" / "selftest.py",
        "finalizer": Path(__file__).resolve(),
    }
    manifest = {
        "schema_version": 2,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task": "megaman1_official_manual_candidate_v2",
        "all_ok": all(checks.values()),
        "checks": checks,
        "candidate_only": True,
        "whole_game_knowledge_base": False,
        "scope": str(SCOPE_OUT),
        "candidate": {
            "revision": M.REVISION, "domain": M.PRODUCTION_DOMAIN, "backend": "megaman1_candidate",
            "index": str(M.INDEX_PATH), "index_sha256": M.expected_index_sha256(),
            "chunks": len(index["chunks"]), "indexed_files": len({c["path"] for c in index["chunks"]}),
            "frozen_questions": str(M.FROZEN_QUESTIONS), "frozen_questions_sha256": sha(M.FROZEN_QUESTIONS),
            "question_counts": frozen["expected_counts"],
        },
        "manual_provenance": scope["manual_source"],
        "route_acceptance": {"all_ok": route["all_ok"], "summary": route["summary"],
                             "report": str(ROUTE_REPORT)},
        "isolated_evaluation": {"all_ok": isolated["all_ok"], "summary": isolated["summary"],
                                "report": str(ISOLATED_REPORT)},
        "regression": {
            "gates": gates,
            "full_domain_summary": full_domain["summary"],
            "blind_summary": blind["summary"],
            "blind_isolation": blind["isolation"],
            "targeted_rerun_after_final_copy": {"kb": gates["kb"], "production_route": route["all_ok"]},
        },
        "shared_state_after_all_regressions": {
            "unchanged_since_route_acceptance": not changed_since_route,
            "unchanged_during_final_live_queries": not changed_during_live,
            "changed_paths": changed_since_route,
            "snapshots": after_live,
        },
        "final_live_queries": {"all_ok": all(p["ok"] for p in probes),
                               "json": str(LIVE_JSON), "log": str(LIVE_LOG),
                               "log_lines": len(live_rows), "probes": probes},
        "temporary_research_cleanup": cleanup,
        "external_generative_model_calls": 0,
        "paid_api_calls": 0,
        "code_sha256": {name: sha(path) for name, path in code_paths.items()},
        "artifacts": artifacts,
        "remaining": [
            "候选不是整款游戏知识库，官方说明书只收8个短摘录",
            "PAL-B与其他版本跨版等价未验证",
            "FM2导入与segmented TAS仍为reference_only，不能证明目标时刻续作流程",
            "全部敌人、关卡与隐藏要素尚未形成完整覆盖",
        ],
    }
    atomic_text(MANIFEST_OUT, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"all_ok": manifest["all_ok"], "gates": gates,
                      "live_queries": manifest["final_live_queries"]["all_ok"],
                      "cleanup": cleanup, "manifest": str(MANIFEST_OUT)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
