# -*- coding: utf-8 -*-
"""洛克人2候选生产路由验收：复用冻结题与生产 query_auto，不写共享知识库。"""
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "megaman2_candidate_20261125"
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "_工具脚本"))
sys.path.insert(0, str(ROOT))

from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import kb_megaman2 as M
from taspipe import kb_route as KR
from taspipe import sources as S

spec = importlib.util.spec_from_file_location(
    "mm2_isolated_eval", BASE / "selftest_eval_megaman2_20261125.py")
ISOLATED = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ISOLATED)
KC = importlib.import_module("选题决策层.知识对照")
LOG = BASE / "qc" / "production_route_query_log_20261125.jsonl"
REPORT = HERE / "eval_report.json"


def snapshot(path):
    p = Path(path)
    if not p.is_file():
        return {"exists": False}
    return {"exists": True, "size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def compact(result):
    domain_results = []
    for row in result.get("domain_results") or []:
        domain_results.append({
            "domain": row.get("domain"), "status": row.get("status"),
            "refusal": row.get("refusal"), "reason_code": row.get("reason_code"),
            "backend": row.get("backend"), "index_used": row.get("index_used"),
            "index_sha256": row.get("index_sha256"),
            "selected_evidence": row.get("selected_evidence") or [],
            "candidate_only": row.get("candidate_only"),
            "whole_game_knowledge_base": row.get("whole_game_knowledge_base"),
            "production_route_wired": row.get("production_route_wired")})
    return {"status": result.get("status"), "refusal": result.get("refusal"),
            "reason_code": result.get("reason_code"), "reason": result.get("reason"),
            "backend": result.get("backend"), "retrieval": result.get("retrieval"),
            "index_used": result.get("index_used"), "index_sha256": result.get("index_sha256"),
            "answer_text": result.get("answer_text", ""),
            "selected_evidence": result.get("selected_evidence") or [],
            "auto_routing": result.get("auto_routing") or {},
            "domain_results": domain_results,
            "candidate_only": result.get("candidate_only"),
            "whole_game_knowledge_base": result.get("whole_game_knowledge_base"),
            "production_route_wired": result.get("production_route_wired")}


def candidate_part(result):
    if result.get("backend") == "megaman2_candidate":
        return result, result.get("candidate_route") or result.get("route") or {}
    for row in result.get("domain_results") or []:
        if row.get("domain") == "megaman2":
            return row, row.get("candidate_route") or {}
    return {}, {}


def grade_auto(case, result, mode):
    checks = []

    def check(name, value):
        checks.append({"name": name, "ok": bool(value)})

    candidate, route = candidate_part(result)
    selected = candidate.get("selected_evidence") or []
    auto_domains = [d.get("domain") for d in (result.get("auto_routing") or {}).get("domains", [])]
    if not candidate and M.PRODUCTION_DOMAIN not in auto_domains:
        all_hits = list(result.get("selected_evidence") or [])
        for row in result.get("domain_results") or []:
            all_hits.extend(row.get("selected_evidence") or [])
        check("not_candidate_no_borrow", result.get("backend") != "megaman2_candidate"
              and all(not str(h.get("revision", "")).startswith("megaman2_")
                      for h in all_hits))
        if case["kind"] in {"blocked", "unsupported"}:
            check("no_false_pass", result.get("status") != "pass"
                  and not result.get("selected_evidence"))
        return {"id": case["id"], "q": case["q"], "kind": case["kind"], "mode": mode,
                "ok": all(c["ok"] for c in checks), "checks": checks,
                "result": compact(result)}
    check("candidate_backend", candidate.get("backend") == "megaman2_candidate")
    check("candidate_flags", candidate.get("candidate_only") is True
          and candidate.get("whole_game_knowledge_base") is False
          and candidate.get("production_route_wired") is True)
    if case.get("index_expected") or candidate.get("index_used"):
        check("candidate_hash", candidate.get("index_sha256") == M.expected_index_sha256())
    check("no_kof_evidence", all(not str(h.get("source_id", "")).startswith("kof98")
                                 for h in selected + (candidate.get("hits") or [])))
    if case["kind"] == "positive":
        check("status_pass", candidate.get("status") == "pass")
        check("one_selected", len(selected) == 1)
        check("revision", route.get("revision") == case["revision"])
        if selected:
            hit = selected[0]
            check("source", hit.get("source_id") == case["source_id"])
            check("authority", hit.get("status") == "verified_read"
                  and hit.get("authority") == "authoritative")
            check("locator", case["target"] in hit.get("locator", ""))
            check("fact_text", all(term in candidate.get("answer_text", "")
                                   for term in case["must_contain"]))
            if mode == "strict":
                check("strict_fragment", (hit.get("fragment_provenance") or {}).get("eligible") is True)
    elif case["kind"] == "blocked":
        check("status", result.get("status") in {"miss", "inconclusive"})
        check("refusal", result.get("refusal") == case["refusal"])
        check("outer_no_evidence", not result.get("selected_evidence"))
        if case["disposition"] != "multi_domain_needs_split":
            check("candidate_no_evidence", not selected)
            check("no_retrieval", candidate.get("index_used") is None
                  and not candidate.get("hits"))
    elif case["kind"] == "movelist":
        check("status", candidate.get("status") == "miss")
        check("refusal", candidate.get("reason_code") == "move_list_not_collected")
        check("candidate_index", candidate.get("index_used") == "index.json")
        check("no_evidence", not selected)
    elif case["kind"] == "weak":
        check("status_inconclusive", candidate.get("status") == "inconclusive")
        check("candidate_index", candidate.get("index_used") == "index.json")
        check("revision", route.get("revision") == case["revision"])
        check("reference_hit", any(h.get("source_id") == case["source_id"]
                                   and h.get("authority") == "reference_only"
                                   for h in candidate.get("hits") or []))
        check("no_evidence", not selected)
    elif case["kind"] == "unsupported":
        check("status", result.get("status") in {"miss", "inconclusive"})
        check("no_evidence", not result.get("selected_evidence") and not selected)
    return {"id": case["id"], "q": case["q"], "kind": case["kind"], "mode": mode,
            "disposition": case.get("disposition"),
            "ok": all(c["ok"] for c in checks), "checks": checks,
            "result": compact(result)}


def main():
    protected = [K.INDEX_JSON, K.hybrid_index_path(), K.CORPUS_MAP, S.REG_JSON,
                 K.KB_DIR / "query_log.jsonl", KE.DB_PATH,
                 M.INDEX_PATH, M.MAP_PATH, M.REGISTRY_PATH, M.CONTRACT_PATH]
    before = {str(p): snapshot(p) for p in protected}
    LOG.write_text("", encoding="utf-8")
    index = K.load_index(M.INDEX_PATH)
    chunks = {c["chunk_id"]: c for c in index["chunks"]}
    isolated_rows, auto_rows = [], []
    for case in ISOLATED.ASK_CASES:
        for mode in ("default", "strict"):
            direct = M.ask(case["q"], mode=mode, log_path=LOG)
            isolated_rows.append(ISOLATED.grade_case(case, direct, chunks, mode))
            auto = K.query_auto(case["q"], topk=8, top_window=3,
                                fragment_policy="strict" if mode == "strict" else None)
            auto_rows.append(grade_auto(case, auto, mode))
    failure_rows = ISOLATED.failure_close_cases()
    route_rows = []
    for rid, q, expected in ISOLATED.ROUTE_CASES:
        domains = [r["domain"] for r in KR.route_many(q)]
        candidate_route = M.route_question(q)
        expect_production_domain = expected in {
            "candidate", "version_not_collected", "multi_domain_needs_split"} or bool(
                candidate_route.get("matched"))
        route_rows.append({"id": rid, "q": q, "expected": expected,
                           "candidate_disposition": candidate_route["disposition"],
                           "domains": domains,
                           "ok": candidate_route["disposition"] == expected
                           and (("megaman2" in domains) == expect_production_domain)})
    probes = {}
    for name, q, kwargs in (
            ("zh_walking", "洛克人2 步行速度是多少", {}),
            ("zh_jump", "洛克人2 跳跃 Y 速度是什么", {}),
            ("zh_xspd", "洛克人2 的 X 速度内存地址是什么", {}),
            ("fullwidth_alias", "洛克人  ２ 的 walking speed 是什么？", {}),
            ("explicit_revision", "X speed 内存地址是什么",
             {"revision": M.TECHNICAL_REVISION}),
            ("mm20_negative", "洛克人20 的 walking speed 是什么？", {}),
            ("multi_kof", "洛克人2 的 walking speed 和拳皇98 的必杀射门分别是什么？", {})):
        probes[name] = compact(K.query_auto(q, **kwargs))
    old_log = KC.QUERY_LOG
    try:
        KC.QUERY_LOG = LOG
        cross, info = KC.crosscheck(
            [{"event_id": "mm2_route_eval", "titles": ["洛克人2 步行速度是多少"]}],
            mode="bm25", index_path=K.INDEX_JSON)
    finally:
        KC.QUERY_LOG = old_log
    cross_result = cross["mm2_route_eval"]
    old_hash = M.expected_index_sha256
    try:
        M.expected_index_sha256 = lambda: "0" * 64
        bad_hash = K.query_auto("洛克人2 的 walking speed 是什么？")
    finally:
        M.expected_index_sha256 = old_hash
    after = {str(p): snapshot(p) for p in protected}
    changed = [p for p in before if before[p] != after[p]]
    log_rows = [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    summary = {
        "route_total": len(route_rows), "route_ok": sum(r["ok"] for r in route_rows),
        "isolated_default_ok": sum(r["ok"] for r in isolated_rows if r["mode"] == "default"),
        "isolated_strict_ok": sum(r["ok"] for r in isolated_rows if r["mode"] == "strict"),
        "auto_default_ok": sum(r["ok"] for r in auto_rows if r["mode"] == "default"),
        "auto_strict_ok": sum(r["ok"] for r in auto_rows if r["mode"] == "strict"),
        "auto_total": len(auto_rows),
        "failure_close_total": len(failure_rows),
        "failure_close_ok": sum(r["ok"] for r in failure_rows),
        "wrong_candidate_evidence": sum(
            bool(candidate_part(r["result"])[0].get("selected_evidence"))
            and r["kind"] != "positive"
            and r.get("disposition") != "multi_domain_needs_split"
            for r in auto_rows),
        "blocked_outer_evidence": sum(bool(r["result"]["selected_evidence"])
                                      and r["kind"] == "blocked" for r in auto_rows),
        "non_candidate_scope_total": sum("not_candidate_no_borrow" in
                                         {c["name"] for c in r["checks"]} for r in auto_rows),
        "query_log_lines": len(log_rows)}
    checks = {
        "all_routes_ok": summary["route_total"] == summary["route_ok"],
        "isolated_all_ok": all(r["ok"] for r in isolated_rows),
        "auto_all_ok": all(r["ok"] for r in auto_rows),
        "failure_close_all_ok": all(r["ok"] for r in failure_rows),
        "wrong_candidate_evidence_zero": summary["wrong_candidate_evidence"] == 0,
        "blocked_outer_evidence_zero": summary["blocked_outer_evidence"] == 0,
        "chinese_positives_pass": all(probes[n]["status"] == "pass"
                                      for n in ("zh_walking", "zh_jump", "zh_xspd",
                                                "fullwidth_alias", "explicit_revision")),
        "mm20_not_candidate": probes["mm20_negative"]["backend"] != "megaman2_candidate",
        "multi_not_merged": probes["multi_kof"]["status"] == "inconclusive"
                            and probes["multi_kof"]["refusal"] == "multi_domain_needs_split"
                            and not probes["multi_kof"]["selected_evidence"],
        "consumer_anchored": cross_result.get("status") == "pass"
                             and cross_result.get("index_sha256") == M.expected_index_sha256()
                             and info.get("unanchored_downgraded") == 0,
        "hash_mismatch_closed": bad_hash.get("reason_code") == "candidate_hash_mismatch"
                                and not bad_hash.get("selected_evidence"),
        "shared_and_candidate_inputs_unchanged": not changed,
        "query_log_valid": len(log_rows) == len(ISOLATED.ASK_CASES) * 2 + 1
                           and all(row.get("status") for row in log_rows)}
    report = {"schema_version": 1, "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "consumer": "taspipe.kb.query_auto", "candidate_domain": M.PRODUCTION_DOMAIN,
              "candidate_only": True, "whole_game_knowledge_base": False,
              "summary": summary, "checks": checks, "all_ok": all(checks.values()),
              "route_cases": route_rows, "isolated_cases": isolated_rows,
              "auto_cases": auto_rows, "failure_close": failure_rows,
              "probes": probes, "consumer_crosscheck": {"result": cross_result, "info": info},
              "hash_mismatch": compact(bad_hash),
              "isolation": {"ok": not changed, "changed_paths": changed,
                            "before": before, "after": after},
              "query_log": {"path": str(LOG), "lines": len(log_rows),
                            "sha256": hashlib.sha256(LOG.read_bytes()).hexdigest()},
              "code_sha256": {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                              for name, module in (("kb", K), ("kb_route", KR),
                                                   ("kb_megaman2", M), ("kb_selftest_gates",
                                                    importlib.import_module("taspipe.kb_selftest_gates")))},
              "remaining": ["候选只覆盖TASVideos明确技术条目，不是整款游戏知识库",
                            "出招表与官方说明书级玩法正文未收集",
                            "PAL/美版/日版ROM身份与跨版等价未验证",
                            "内存字典仍是reference_only，未做本机逐字段实测",
                           "自动入口的unrouted全库假pass已失败关闭；手动kb.query全库检索仍保留供显式调用"]}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_ok": report["all_ok"], "summary": summary, "checks": checks,
                      "changed_paths": changed, "report": str(REPORT)},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
