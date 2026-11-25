import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT / "_工具脚本"))

from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import kb_megaman2 as M
from taspipe import sources as S

CANDIDATE = BASE / "megaman2_candidate_v2_manual_20261125"
OLD_CANDIDATE = BASE / "megaman2_candidate_20261125"
FROZEN = BASE / "megaman2_questions_frozen_v2_manual_20261125.json"
OLD_SCRIPT = OLD_CANDIDATE / "selftest_eval_megaman2_20261125.py"
OUT = BASE / "megaman2_production_manual_eval_20261125.json"
PRODUCTION_LOG = CANDIDATE / "qc" / "production_route_query_log_20261125.jsonl"
LEGACY_LOG = CANDIDATE / "qc" / "legacy_candidate_regression_query_log_20261125.jsonl"
REAL_PATHS = [
    K.INDEX_JSON,
    K.CORPUS_MAP,
    S.REG_JSON,
    K.KB_DIR / "query_log.jsonl",
    K.KB_DIR / "index_hybrid.json",
    KE.DB_PATH,
    ROOT / "选题决策层" / "kb快照" / "index.json",
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(path):
    path = Path(path)
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {"present": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": sha(path)}


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def input_paths(candidate, frozen=None):
    paths = [candidate / name for name in (
        "index.json", "corpus_map.json", "sources.json", "contract.json",
        "provenance.json", "scope.json", "manual_source.json")]
    corpus_map = json.loads((candidate / "corpus_map.json").read_text(encoding="utf-8"))
    paths.extend(ROOT / entry["path"] for entry in corpus_map["entries"])
    if frozen is not None:
        paths.append(frozen)
    return list(dict.fromkeys(Path(p) for p in paths))


def locator_lines(locator):
    try:
        start, end = locator.rsplit("#L", 1)[1].split("-L", 1)
        return int(start), int(end)
    except (AttributeError, ValueError, IndexError):
        return 0, 0


def grade(item, entry, mode, result, candidate_sha, production_sha, production_evidence):
    checks = []

    def check(name, value):
        checks.append({"name": name, "ok": bool(value)})

    selected = result.get("selected_evidence") or []
    route = result.get("candidate_route") or result.get("route") or {}
    expected_revision = item.get("revision")
    multi_auto = item["id"] == "MM406" and entry == "auto"
    if entry == "auto" and item["expect"] in {"strict_pass", "weak"}:
        check("backend", result.get("backend") == "megaman2")
    if not multi_auto:
        check("production_wired", result.get("production_route_wired") is True)
        check("not_whole_game", result.get("whole_game_knowledge_base") is False)

    if item["expect"] == "strict_pass":
        manual = expected_revision == M.MANUAL_REVISION
        expected_sha = candidate_sha if manual else production_sha
        check("route_revision", route.get("revision") == expected_revision)
        check("status_pass", result.get("status") == "pass")
        check("one_selected", len(selected) == 1)
        check("index_identity", result.get("index_used") == "index.json"
              and result.get("index_sha256") == expected_sha)
        check("candidate_boundary", result.get("candidate_only") is manual)
        if selected:
            hit = selected[0]
            answer_text = result.get("answer_text") or (result.get("answer") or {}).get("text", "")
            check("source", hit.get("source_id") == item["source_id"])
            check("revision", hit.get("revision") == expected_revision)
            check("qualified", hit.get("status") == "verified_read"
                  and hit.get("authority") == "authoritative")
            check("answer_excerpt", bool(answer_text))
            if manual:
                gold = item["gold"]
                start, end = locator_lines(hit.get("locator"))
                check("gold_chunk", hit.get("chunk_id") == gold["anchor_chunk"])
                check("gold_locator", gold["path_contains"] in hit.get("locator", ""))
                check("gold_overlap", start <= gold["line_end"] and end >= gold["line_start"])
            else:
                fact = {"MM101": "01.60", "MM102": "$460:$480", "MM103": "04.DF",
                        "MM104": "00.C0", "MM105": "01.60"}[item["id"]]
                check("production_evidence_path", any(path in hit.get("locator", "")
                                                      for path in production_evidence))
                check("technical_fact", fact in answer_text)
            if mode == "strict":
                check("strict_fragment", (hit.get("fragment_provenance") or {}).get("eligible") is True)
    elif item["expect"] == "weak":
        check("route_revision", route.get("revision") == expected_revision)
        check("status_inconclusive", result.get("status") == "inconclusive")
        check("revision_not_produced", result.get("refusal") == "revision_not_produced")
        check("no_retrieval", not result.get("hits"))
        check("no_evidence", not selected)
    else:
        check("not_pass", result.get("status") != "pass")
        check("no_evidence", not selected)
        if item["id"] == "MM406" and entry == "auto":
            check("outer_split", result.get("status") == "inconclusive"
                  and result.get("refusal") == "multi_domain_needs_split")
            domain = next((d for d in result.get("domain_results") or []
                           if d.get("domain") == "megaman2"), {})
            domain_selected = domain.get("selected_evidence") or []
            check("domain_evidence", domain.get("status") == "pass"
                  and len(domain_selected) == 1
                  and domain_selected[0].get("source_id") == M.PRODUCTION_SOURCE_ID
                  and domain_selected[0].get("revision") == M.TECHNICAL_REVISION)
            check("domain_boundary", domain.get("candidate_only") is False
                  and domain.get("production_route_wired") is True
                  and domain.get("whole_game_knowledge_base") is False)
        elif item.get("reason_code"):
            check("reason_code", result.get("refusal") == item["reason_code"])
            check("no_retrieval", not result.get("hits"))

    return {"id": item["id"], "q": item["q"], "entry": entry, "mode": mode,
            "expect": item["expect"], "ok": all(c["ok"] for c in checks),
            "checks": checks, "status": result.get("status"),
            "refusal": result.get("refusal"), "route": route,
            "index_used": result.get("index_used"), "index_sha256": result.get("index_sha256"),
            "candidate_only": result.get("candidate_only"),
            "selected_locator": selected[0].get("locator") if selected else None,
            "hit_count": len(result.get("hits") or [])}


def run_production_queries(questions, candidate_sha, production_sha, production_evidence, log_rows):
    grades = []
    for item in questions:
        for mode in ("default", "strict"):
            policy = "strict" if mode == "strict" else None
            direct = M.ask(item["q"], mode=mode, production=True, topk=8,
                           log_path=PRODUCTION_LOG)
            grades.append(grade(item, "direct", mode, direct, candidate_sha, production_sha,
                                production_evidence))
            auto = K.query_auto(item["q"], topk=8, fragment_policy=policy,
                                log_sink=log_rows.append,
                                log_context={"entry_point": "mm2-v2-manual-production-eval-auto"})
            grades.append(grade(item, "auto", mode, auto, candidate_sha, production_sha,
                                production_evidence))
    return grades


def run_failure_close(log_rows):
    question = "洛克人2官方说明书里 Crash Bomber 有什么用途？"
    rows = []
    with patch.object(M, "expected_index_sha256", lambda: "0" * 64):
        for mode in ("default", "strict"):
            policy = "strict" if mode == "strict" else None
            direct = M.ask(question, mode=mode, production=True, log_path=PRODUCTION_LOG)
            auto = K.query_auto(question, fragment_policy=policy, log_sink=log_rows.append,
                                log_context={"entry_point": "mm2-v2-manual-production-eval-hash-fail"})
            for entry, result in (("direct", direct), ("auto", auto)):
                rows.append({"probe": "candidate_hash_mismatch", "entry": entry, "mode": mode,
                             "ok": result.get("status") == "inconclusive"
                             and result.get("refusal") == "candidate_hash_mismatch"
                             and not result.get("hits") and not result.get("selected_evidence")})
    with tempfile.TemporaryDirectory(prefix="mm2-manual-missing-") as tmp:
        missing = Path(tmp) / "missing.index.json"
        with patch.object(M, "INDEX_PATH", missing):
            for mode in ("default", "strict"):
                policy = "strict" if mode == "strict" else None
                direct = M.ask(question, mode=mode, production=True, log_path=PRODUCTION_LOG)
                auto = K.query_auto(question, fragment_policy=policy, log_sink=log_rows.append,
                                    log_context={"entry_point": "mm2-v2-manual-production-eval-missing-fail"})
                for entry, result in (("direct", direct), ("auto", auto)):
                    rows.append({"probe": "candidate_unavailable", "entry": entry, "mode": mode,
                                 "ok": result.get("status") == "inconclusive"
                                 and result.get("refusal") == "candidate_unavailable"
                                 and not result.get("hits") and not result.get("selected_evidence")})
    return rows


def run_legacy_regression():
    spec = importlib.util.spec_from_file_location("mm2_legacy_eval", OLD_SCRIPT)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    fd, name = tempfile.mkstemp(prefix=".mm2_legacy_regression_", suffix=".jsonl", dir=OLD_CANDIDATE)
    os.close(fd)
    Path(name).unlink()
    temp_log = Path(name)
    legacy.LOG = temp_log
    try:
        with patch.multiple(M, CANDIDATE_DIR=OLD_CANDIDATE,
                            INDEX_PATH=OLD_CANDIDATE / "index.json",
                            MAP_PATH=OLD_CANDIDATE / "corpus_map.json",
                            REGISTRY_PATH=OLD_CANDIDATE / "sources.json",
                            CONTRACT_PATH=OLD_CANDIDATE / "contract.json"):
            report = legacy.evaluate()
        legacy_log_text = temp_log.read_text(encoding="utf-8")
        atomic_text(LEGACY_LOG, legacy_log_text)
    finally:
        temp_log.unlink(missing_ok=True)
        Path(str(temp_log) + ".tmp").unlink(missing_ok=True)
    summary = report["summary"]
    ok = (summary["route_ok"] == summary["route_total"]
          and summary["default_ok"] == summary["default_total"]
          and summary["strict_ok"] == summary["strict_total"]
          and summary["failure_close_ok"] == summary["failure_close_total"]
          and report["evidence_validation"]["ok"]
          and report["audit_required_ok"])
    return {"ok": ok, "summary": summary, "route_cases": report["route_cases"],
            "ask_cases": report["ask_cases"], "failure_close": report["failure_close"],
            "evidence_validation": report["evidence_validation"],
            "audit_required_ok": report["audit_required_ok"],
            "obsolete_production_assertions_not_used": [
                "lm2_domain_absent", "megaman2_in_domains"],
            "query_log": {"path": str(LEGACY_LOG),
                          "lines": len(legacy_log_text.splitlines()),
                          "sha256": sha(LEGACY_LOG)}}


def summarize(grades):
    out = {}
    for entry in ("direct", "auto"):
        for mode in ("default", "strict"):
            rows = [g for g in grades if g["entry"] == entry and g["mode"] == mode]
            out[f"{entry}_{mode}"] = {
                "total": len(rows), "ok": sum(g["ok"] for g in rows),
                "strict_pass": {"total": sum(g["expect"] == "strict_pass" for g in rows),
                                "ok": sum(g["expect"] == "strict_pass" and g["ok"] for g in rows)},
                "weak": {"total": sum(g["expect"] == "weak" for g in rows),
                         "ok": sum(g["expect"] == "weak" and g["ok"] for g in rows)},
                "refuse": {"total": sum(g["expect"] == "refuse" for g in rows),
                           "ok": sum(g["expect"] == "refuse" and g["ok"] for g in rows)},
                "failed_ids": sorted({g["id"] for g in rows if not g["ok"]}),
            }
    return out


def main():
    v2_inputs = input_paths(CANDIDATE, FROZEN)
    old_inputs = input_paths(OLD_CANDIDATE)
    guarded = REAL_PATHS + v2_inputs + old_inputs
    before = {str(p): snapshot(p) for p in guarded}
    candidate_sha = sha(CANDIDATE / "index.json")
    production_sha = sha(K.INDEX_JSON)
    production_registry = S.load_registry(S.REG_JSON)
    production_source = next(s for s in production_registry["sources"]
                             if s["source_id"] == M.PRODUCTION_SOURCE_ID)
    production_evidence = [Path(path).as_posix() for path in production_source["evidence"]]
    if candidate_sha != M.expected_index_sha256():
        raise RuntimeError("v2 candidate hash does not match production contract")
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    questions = list(frozen["questions"])
    by_id = {q["id"]: q for q in questions}
    extra = [
        {"id": "X01", "q": "洛克人2 NTSC 美版官方说明书里 Crash Bomber 有什么用途？",
         "expect": "strict_pass", "revision": M.MANUAL_REVISION,
         "source_id": M.MANUAL_SOURCE_ID, "gold": by_id["MM210"]["gold"]},
        {"id": "X02", "q": "洛克人2 NTSC 官方说明书里 Crash Bomber 有什么用途？",
         "expect": "refuse", "reason_code": "version_not_collected"},
        {"id": "X03", "q": "洛克人2 日版官方说明书里 Crash Bomber 有什么用途？",
         "expect": "refuse", "reason_code": "version_not_collected"},
        {"id": "X04", "q": "MM2 JP ROM 的 walking speed 是什么？",
         "expect": "refuse", "reason_code": "version_not_collected"},
    ]
    questions.extend(extra)
    atomic_text(PRODUCTION_LOG, "")
    auto_log_rows = []
    grades = run_production_queries(questions, candidate_sha, production_sha,
                                    production_evidence, auto_log_rows)
    failure_rows = run_failure_close(auto_log_rows)
    direct_log_rows = [json.loads(line) for line in PRODUCTION_LOG.read_text(encoding="utf-8").splitlines()
                       if line.strip()]
    production_log_rows = direct_log_rows + auto_log_rows
    atomic_text(PRODUCTION_LOG, "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in production_log_rows))
    legacy = run_legacy_regression()
    after = {str(p): snapshot(p) for p in guarded}
    changed = [p for p in before if before[p] != after[p]]
    summary = summarize(grades)
    production_ok = all(v["ok"] == v["total"] for v in summary.values())
    failure_ok = all(row["ok"] for row in failure_rows)
    isolation_ok = not changed
    all_ok = production_ok and failure_ok and legacy["ok"] and isolation_ok
    report = {
        "schema_version": 1,
        "status": "pass" if all_ok else "fail",
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "洛克人2候选子域；不是整款游戏知识库",
        "candidate_index_sha256": candidate_sha,
        "production_index_sha256": production_sha,
        "question_counts": {"total": len(questions),
                            "strict_pass": sum(q["expect"] == "strict_pass" for q in questions),
                            "weak": sum(q["expect"] == "weak" for q in questions),
                            "refuse": sum(q["expect"] == "refuse" for q in questions)},
        "production_query_count": len(grades),
        "failure_close_query_count": len(failure_rows),
        "summary": summary,
        "production_all_ok": production_ok,
        "failure_close_all_ok": failure_ok,
        "questions": grades,
        "failure_close": failure_rows,
        "legacy_candidate_regression": legacy,
        "isolation": {"ok": isolation_ok, "changed_paths": changed,
                      "real_state_unchanged": all(before[str(p)] == after[str(p)] for p in REAL_PATHS),
                      "v2_inputs_unchanged": all(before[str(p)] == after[str(p)] for p in v2_inputs),
                      "old_inputs_unchanged": all(before[str(p)] == after[str(p)] for p in old_inputs),
                      "before": before, "after": after},
        "query_logs": {
            "production_route": {"path": str(PRODUCTION_LOG), "lines": len(production_log_rows),
                                 "sha256": sha(PRODUCTION_LOG)},
            "legacy_candidate": legacy["query_log"],
        },
        "external_generative_model_calls": 0,
        "paid_api_calls": 0,
    }
    atomic_text(OUT, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "summary": summary,
                      "failure_close_all_ok": failure_ok,
                      "legacy_all_ok": legacy["ok"], "legacy_summary": legacy["summary"],
                      "changed_paths": changed, "report": str(OUT)},
                     ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
