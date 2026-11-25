# -*- coding: utf-8 -*-
"""洛克人1候选生产路由验收：复用冻结题与 query_auto，不写共享知识库。"""
import hashlib
import importlib
import json
import sys
import time
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "_工具脚本"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "知识库小样_20261118"))

from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import kb_megaman1 as M
from taspipe import kb_route as KR
from taspipe import sources as S
import eval_common as E

KC = importlib.import_module("选题决策层.知识对照")
FROZEN = BASE / "megaman1_questions_frozen_20261125.json"
DIRECT_LOG = M.CANDIDATE_DIR / "qc" / "production_route_query_log_20261125.jsonl"
AUTO_LOG = HERE / "production_auto_query_log_20261125.jsonl"
CONSUMER_LOG = HERE / "consumer_query_log_20261125.jsonl"
REPORT_JSON = HERE / "eval_report.json"
REPORT_MD = HERE / "eval_report.md"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(path):
    p = Path(path)
    if not p.is_file():
        return {"present": False}
    st = p.stat()
    return {"present": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": sha(p)}


def write_text(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def compact(result):
    parts = []
    for row in result.get("domain_results") or []:
        parts.append({
            "domain": row.get("domain"), "status": row.get("status"),
            "refusal": row.get("refusal"), "reason_code": row.get("reason_code"),
            "backend": row.get("backend"), "index_used": row.get("index_used"),
            "index_sha256": row.get("index_sha256"),
            "selected_evidence": row.get("selected_evidence") or [],
            "candidate_only": row.get("candidate_only"),
            "whole_game_knowledge_base": row.get("whole_game_knowledge_base"),
            "production_route_wired": row.get("production_route_wired"),
        })
    return {
        "status": result.get("status"), "refusal": result.get("refusal"),
        "reason_code": result.get("reason_code"), "reason": result.get("reason"),
        "backend": result.get("backend"), "retrieval": result.get("retrieval"),
        "index_used": result.get("index_used"), "index_sha256": result.get("index_sha256"),
        "answer_text": result.get("answer_text", ""),
        "selected_evidence": result.get("selected_evidence") or [],
        "auto_routing": result.get("auto_routing") or {},
        "domain_results": parts,
        "candidate_only": result.get("candidate_only"),
        "whole_game_knowledge_base": result.get("whole_game_knowledge_base"),
        "production_route_wired": result.get("production_route_wired"),
    }


def candidate_part(result):
    if result.get("backend") == "megaman1_candidate":
        return result
    for row in result.get("domain_results") or []:
        if row.get("domain") == M.PRODUCTION_DOMAIN:
            return row
    return {}


def grade_question(item, result, mode, automatic=True):
    checks = []

    def check(name, value):
        checks.append({"name": name, "ok": bool(value)})

    candidate = candidate_part(result) if automatic else result
    selected = candidate.get("selected_evidence") or []
    outer_selected = result.get("selected_evidence") or []
    domains = [d.get("domain") for d in (result.get("auto_routing") or {}).get("domains", [])]
    check("grade_v2", E.grade_v2(item, result)["ok"])
    if automatic:
        check("candidate_domain", M.PRODUCTION_DOMAIN in domains)
    check("candidate_flags", candidate.get("candidate_only") is True
          and candidate.get("whole_game_knowledge_base") is False)
    check("outer_not_merged", result.get("status") != "pass" or len(outer_selected) == 1)
    if item["expect"] == "strict_pass":
        check("pass", candidate.get("status") == "pass")
        check("one_evidence", len(selected) == 1 and len(outer_selected) == 1)
        check("hash", candidate.get("index_sha256") == M.expected_index_sha256())
        if selected:
            hit = selected[0]
            check("gold_locator", item["gold"]["path_contains"] in hit.get("locator", ""))
            check("revision", hit.get("revision") == M.REVISION)
            check("qualified", hit.get("status") == "verified_read"
                  and hit.get("authority") == "authoritative")
            if mode == "strict":
                check("strict_fragment", (hit.get("fragment_provenance") or {}).get("eligible") is True)
    else:
        check("refused", result.get("status") != "pass")
        check("no_evidence", not outer_selected and not selected)
        if item["id"] == "MM12":
            check("version_boundary", result.get("reason_code") == "version_not_collected")
    return {"id": item["id"], "q": item["q"], "expect": item["expect"], "mode": mode,
            "ok": all(c["ok"] for c in checks), "checks": checks,
            "result": compact(result)}


def route_cases():
    specs = [
        ("R01", "洛克人1 的坐标轴方向是什么？", "candidate", True),
        ("R02", "洛克人 １ 的坐标轴方向是什么？", "candidate", True),
        ("R03", "Ｍｅｇａ　Ｍａｎ　１ 的坐标轴方向是什么？", "candidate", True),
        ("R04", "rockman 1 的坐标轴方向是什么？", "candidate", True),
        ("R05", "洛克人 的坐标轴方向是什么？", "ambiguous_series", True),
        ("R06", "Mega Man X 的坐标轴方向是什么？", "ambiguous_series", False),
        ("R07", "洛克人2 的坐标轴方向是什么？", "ambiguous_series", False),
        ("R08", "洛克人1 PAL-B 的坐标表能直接照用吗？", "version_not_collected", True),
        ("R09", "Mega Man 1 欧版的坐标表能直接照用吗？", "version_not_collected", True),
        ("R10", "拳皇98 的坐标轴方向是什么？", "not_matched", False),
        ("R11", "洛克人1 和拳皇98 的坐标轴分别是什么？", "multi_domain_needs_split", True),
        ("R12", "owned 和 current_weapon 两个内存字段分别对应什么？", "not_matched", False),
        ("R13", "洛克人1 NTSC 美版的坐标轴方向是什么？", "candidate", True),
        ("R14", "洛克人10 的坐标轴方向是什么？", "ambiguous_series", False),
        ("R15", "洛克人  １ 的坐标轴方向是什么？", "candidate", True),
    ]
    rows = []
    for rid, q, expected, expect_domain in specs:
        route = M.route_question(q)
        domains = [r["domain"] for r in KR.route_many(q)]
        result = K.query_auto(q, topk=8)
        auto_domains = [d.get("domain") for d in (result.get("auto_routing") or {}).get("domains", [])]
        expected_auto_domain = expect_domain or (
            expected == "ambiguous_series" and not route.get("other_installment"))
        rows.append({
            "id": rid, "q": q, "expected": expected,
            "actual": route["disposition"], "domains": domains,
            "auto_domains": auto_domains,
            "auto_status": result.get("status"), "auto_backend": result.get("backend"),
            "ok": route["disposition"] == expected
                  and ((M.PRODUCTION_DOMAIN in auto_domains) == expected_auto_domain)
                  and (expected_auto_domain or not candidate_part(result).get("selected_evidence")),
        })
    return rows


def render_md(report):
    s = report["summary"]
    lines = [
        "# 洛克人1生产自动路由验收", "",
        "## 结论", "",
        f"- 生产入口：`taspipe.kb.query_auto`；候选域：`{M.PRODUCTION_DOMAIN}`。",
        f"- 冻结 12 题：default {s['auto_default_ok']}/12；strict {s['auto_strict_ok']}/12。",
        f"- 隔离消费方回归：default {s['direct_default_ok']}/12；strict {s['direct_strict_ok']}/12。",
        f"- 路由边界：{s['route_ok']}/{s['route_total']}；失败关闭：{s['failure_close_ok']}/{s['failure_close_total']}。",
        f"- 错误候选出证：{s['wrong_candidate_evidence']}；阻断外层出证：{s['blocked_outer_evidence']}。",
        f"- 共享状态与候选输入：{'全部未变' if report['isolation']['ok'] else '检测到变化'}。",
        "- 范围仍只是 NTSC 美版洛克人1的 RAM/工具方法；不是整款游戏知识库。", "",
        "## 逐题", "",
        "| ID | 类型 | default | strict | default 出证 | strict 出证 |",
        "|---|---|---|---|---|---|",
    ]
    for row in report["questions"]:
        d = next(x for x in report["auto_cases"] if x["id"] == row["id"] and x["mode"] == "default")
        t = next(x for x in report["auto_cases"] if x["id"] == row["id"] and x["mode"] == "strict")
        dl = (candidate_part(d["result"]).get("selected_evidence") or [{}])[0].get("locator", "—")
        tl = (candidate_part(t["result"]).get("selected_evidence") or [{}])[0].get("locator", "—")
        lines.append(f"| {row['id']} | {row['expect']} | {d['result']['status']} | "
                     f"{t['result']['status']} | {dl or '—'} | {tl or '—'} |")
    lines += ["", "## 边界", "",
              "- 中英文、全角与多空格别名自动进入候选；显式 revision 可提供缺别名问句的游戏身份。",
              "- 系列泛词要求补代次；洛克人10/20 不误路由到洛克人1。",
              "- PAL-B/欧版拒答；官方说明书级玩法缺证拒答。",
              "- 多域问题保留域内证据，但外层不合并成 pass，也不给外层出证。",
              "- 索引缺失、哈希不符、主数据解析失败或出证资格失败均失败关闭，不回退生产文本索引。",
              "- 选题知识对照已识别 megaman1 内容域，候选 SHA 与唯一证据可透传。",
              "- FM2 导入与 segmented TAS 仍只是 reference_only，不能证明洛克人1目标时刻续作流程。", "",
              "## 产物", "",
              f"- 完整 JSON：`{REPORT_JSON.relative_to(ROOT).as_posix()}`",
              f"- 生产查询日志：`{AUTO_LOG.relative_to(ROOT).as_posix()}`",
              f"- 消费链日志：`{CONSUMER_LOG.relative_to(ROOT).as_posix()}`", ""]
    return "\n".join(lines)


def main():
    protected = [K.INDEX_JSON, K.hybrid_index_path(), K.CORPUS_MAP, S.REG_JSON, S.LEDGER_JSON,
                 K.KB_DIR / "query_log.jsonl", KE.DB_PATH,
                 ROOT / "选题决策层" / "kb快照" / "index.json",
                 M.INDEX_PATH, M.MAP_PATH, M.REGISTRY_PATH]
    before = {str(p): snapshot(p) for p in protected}
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    if frozen["status"] != "frozen" or frozen["candidate_index_sha256"] != M.expected_index_sha256():
        raise RuntimeError("冻结题集或候选索引契约不一致")
    DIRECT_LOG.parent.mkdir(parents=True, exist_ok=True)
    write_text(DIRECT_LOG, "")
    auto_log_rows = []
    direct_rows, auto_rows, questions = [], [], []
    for item in frozen["questions"]:
        questions.append({"id": item["id"], "q": item["q"], "expect": item["expect"]})
        explicit = M.route_question(item["q"])["disposition"] == "not_matched"
        for mode in ("default", "strict"):
            direct = M.ask(item["q"], mode=mode, log_path=DIRECT_LOG,
                           assume_revision=True, production=True)
            direct_rows.append(grade_question(item, direct, mode, automatic=False))
            auto = K.query_auto(
                item["q"], revision=M.REVISION if explicit else None,
                topk=8, top_window=3,
                fragment_policy="strict" if mode == "strict" else None,
                log_sink=auto_log_rows.append,
                log_context={"entry_point": f"mm1-production-eval-{mode}"})
            auto_rows.append(grade_question(item, auto, mode))
    write_text(AUTO_LOG, "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
                                for r in auto_log_rows))
    routes = route_cases()
    old_hash = M.expected_index_sha256
    old_index = M.INDEX_PATH
    try:
        M.expected_index_sha256 = lambda: "0" * 64
        bad_hash = K.query_auto("洛克人1 的坐标轴方向是什么？")
        M.expected_index_sha256 = old_hash
        M.INDEX_PATH = HERE / "missing_index.json"
        missing_index = K.query_auto("洛克人1 的坐标轴方向是什么？")
    finally:
        M.expected_index_sha256 = old_hash
        M.INDEX_PATH = old_index
    failure_rows = [
        {"id": "FC01", "ok": bad_hash.get("reason_code") == "candidate_hash_mismatch"
         and not bad_hash.get("selected_evidence") and not bad_hash.get("hits")},
        {"id": "FC02", "ok": missing_index.get("reason_code") == "candidate_unavailable"
         and not missing_index.get("selected_evidence") and not missing_index.get("hits")},
    ]
    old_consumer_log = KC.QUERY_LOG
    try:
        KC.QUERY_LOG = CONSUMER_LOG
        write_text(CONSUMER_LOG, "")
        cross, info = KC.crosscheck(
            [{"event_id": "mm1_route_eval", "titles": ["洛克人1 X坐标对象表地址范围"]}],
            mode="bm25", index_path=K.INDEX_JSON)
    finally:
        KC.QUERY_LOG = old_consumer_log
    cross_result = cross["mm1_route_eval"]
    probes = {}
    for name, q, kwargs in (
            ("zh_positive", "洛克人1 的坐标轴方向是什么？", {}),
            ("english_positive", "Mega Man 1 Rockman object RAM table address ranges", {}),
            ("fullwidth_positive", "洛克人  １ 的坐标轴方向是什么？", {}),
            ("explicit_revision", "owned 和 current_weapon 两个内存字段分别对应什么？",
             {"revision": M.REVISION}),
            ("series_ambiguous", "洛克人的坐标轴方向是什么？", {}),
            ("pal_refused", "洛克人1 PAL-B 的坐标表能直接照用吗？", {}),
            ("mm10_negative", "洛克人10 的坐标轴方向是什么？", {}),
            ("multi_kof", "洛克人1 的坐标轴和拳皇98 的简化连招分别是什么？", {}),
            ("non_candidate", "拳皇98 的简化连招是什么？", {})):
        probes[name] = compact(K.query_auto(q, **kwargs))
    after = {str(p): snapshot(p) for p in protected}
    changed = [p for p in before if before[p] != after[p]]
    direct_log_rows = [json.loads(x) for x in DIRECT_LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    consumer_log_rows = [json.loads(x) for x in CONSUMER_LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    summary = {
        "route_total": len(routes), "route_ok": sum(r["ok"] for r in routes),
        "direct_default_ok": sum(r["ok"] for r in direct_rows if r["mode"] == "default"),
        "direct_strict_ok": sum(r["ok"] for r in direct_rows if r["mode"] == "strict"),
        "auto_default_ok": sum(r["ok"] for r in auto_rows if r["mode"] == "default"),
        "auto_strict_ok": sum(r["ok"] for r in auto_rows if r["mode"] == "strict"),
        "failure_close_total": len(failure_rows),
        "failure_close_ok": sum(r["ok"] for r in failure_rows),
        "wrong_candidate_evidence": sum(
            bool(candidate_part(r["result"]).get("selected_evidence"))
            and r["expect"] != "strict_pass" for r in auto_rows),
        "blocked_outer_evidence": sum(
            bool(r["result"]["selected_evidence"]) and r["expect"] == "refuse" for r in auto_rows),
        "direct_log_lines": len(direct_log_rows), "auto_log_lines": len(auto_log_rows),
        "consumer_log_lines": len(consumer_log_rows),
    }
    checks = {
        "all_routes_ok": summary["route_total"] == summary["route_ok"],
        "direct_all_ok": all(r["ok"] for r in direct_rows),
        "auto_all_ok": all(r["ok"] for r in auto_rows),
        "failure_close_all_ok": all(r["ok"] for r in failure_rows),
        "wrong_candidate_evidence_zero": summary["wrong_candidate_evidence"] == 0,
        "blocked_outer_evidence_zero": summary["blocked_outer_evidence"] == 0,
        "positive_probes_pass": all(probes[n]["status"] == "pass" for n in
                                    ("zh_positive", "english_positive", "fullwidth_positive",
                                     "explicit_revision")),
        "series_and_version_refused": probes["series_ambiguous"].get("reason_code") == "ambiguous_series"
                                      and probes["pal_refused"].get("reason_code") == "version_not_collected",
        "mm10_not_candidate": probes["mm10_negative"].get("backend") != "megaman1_candidate",
        "multi_not_merged": probes["multi_kof"].get("status") == "inconclusive"
                            and probes["multi_kof"].get("refusal") == "multi_domain_needs_split"
                            and not probes["multi_kof"].get("selected_evidence"),
        "non_candidate_no_borrow": probes["non_candidate"].get("backend") != "megaman1_candidate"
                                   and not candidate_part(probes["non_candidate"]).get("selected_evidence"),
        "consumer_anchored": cross_result.get("status") == "pass"
                             and cross_result.get("index_sha256") == M.expected_index_sha256()
                             and info.get("unanchored_downgraded") == 0,
        "logs_complete": summary["direct_log_lines"] == 24
                         and summary["auto_log_lines"] == 24
                         and summary["consumer_log_lines"] == 1,
        "shared_and_candidate_inputs_unchanged": not changed,
    }
    report = {
        "schema_version": 1, "status": "evaluated_production_route",
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "consumer": "taspipe.kb.query_auto", "candidate_domain": M.PRODUCTION_DOMAIN,
        "candidate_revision": M.REVISION, "candidate_only": True,
        "whole_game_knowledge_base": False, "production_defaults_unchanged": True,
        "external_generative_model_calls": 0, "paid_api_calls": 0,
        "summary": summary, "checks": checks, "all_ok": all(checks.values()),
        "questions": questions, "route_cases": routes, "direct_cases": direct_rows,
        "auto_cases": auto_rows, "failure_close": failure_rows, "probes": probes,
        "consumer_crosscheck": {"result": cross_result, "info": info},
        "hash_mismatch": compact(bad_hash), "missing_index": compact(missing_index),
        "isolation": {"ok": not changed, "changed_paths": changed,
                      "before": before, "after": after},
        "query_logs": {
            "direct": {"path": str(DIRECT_LOG), "lines": len(direct_log_rows), "sha256": sha(DIRECT_LOG)},
            "auto": {"path": str(AUTO_LOG), "lines": len(auto_log_rows), "sha256": sha(AUTO_LOG)},
            "consumer": {"path": str(CONSUMER_LOG), "lines": len(consumer_log_rows), "sha256": sha(CONSUMER_LOG)},
        },
        "code_sha256": {name: sha(importlib.import_module(module).__file__) for name, module in
                        (("kb", "taspipe.kb"), ("kb_route", "taspipe.kb_route"),
                         ("kb_megaman1", "taspipe.kb_megaman1"),
                         ("kb_selftest_gates", "taspipe.kb_selftest_gates"))},
        "remaining": ["候选只覆盖NTSC美版洛克人1的RAM与工具方法，不是整款游戏知识库",
                      "官方说明书级玩法语料未建立",
                      "PAL-B与其他版本跨版等价未验证",
                      "FM2导入与segmented TAS仍为reference_only，不能证明目标时刻续作流程"],
    }
    write_text(REPORT_JSON, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_text(REPORT_MD, render_md(report))
    print(json.dumps({"all_ok": report["all_ok"], "summary": summary, "checks": checks,
                      "changed_paths": changed, "report": str(REPORT_JSON)},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
