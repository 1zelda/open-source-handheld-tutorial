# -*- coding: utf-8 -*-
"""洛克人1候选v2生产路由验收：冻结题、query_auto、消费链与失败关闭。"""
import hashlib
import importlib
import json
import sys
import time
from pathlib import Path

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
FROZEN = M.FROZEN_QUESTIONS
DIRECT_LOG = M.CANDIDATE_DIR / "qc" / "production_route_v2_query_log_20261125.jsonl"
AUTO_LOG = HERE / "production_auto_query_log_20261125.jsonl"
CONSUMER_LOG = HERE / "consumer_query_log_20261125.jsonl"
REPORT_JSON = HERE / "eval_report.json"
REPORT_MD = HERE / "eval_report.md"
OLD_CANDIDATE = BASE / "megaman1_candidate_20261125"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(path):
    path = Path(path)
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {"present": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": sha(path)}


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def compact(result):
    parts = [{"domain": row.get("domain"), "status": row.get("status"),
              "refusal": row.get("refusal"), "reason_code": row.get("reason_code"),
              "backend": row.get("backend"), "index_used": row.get("index_used"),
              "index_sha256": row.get("index_sha256"),
              "selected_evidence": row.get("selected_evidence") or [],
              "candidate_only": row.get("candidate_only"),
              "whole_game_knowledge_base": row.get("whole_game_knowledge_base"),
              "production_route_wired": row.get("production_route_wired")}
             for row in result.get("domain_results") or []]
    return {"status": result.get("status"), "refusal": result.get("refusal"),
            "reason_code": result.get("reason_code"), "reason": result.get("reason"),
            "backend": result.get("backend"), "retrieval": result.get("retrieval"),
            "index_used": result.get("index_used"), "index_sha256": result.get("index_sha256"),
            "answer_text": result.get("answer_text", ""),
            "selected_evidence": result.get("selected_evidence") or [],
            "auto_routing": result.get("auto_routing") or {}, "domain_results": parts,
            "candidate_only": result.get("candidate_only"),
            "whole_game_knowledge_base": result.get("whole_game_knowledge_base"),
            "production_route_wired": result.get("production_route_wired")}


def candidate_part(result):
    if result.get("backend") == "megaman1_candidate":
        return result
    return next((row for row in result.get("domain_results") or []
                 if row.get("domain") == M.PRODUCTION_DOMAIN), {})


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
            if item.get("manual_pages"):
                check("manual_source", hit.get("source_id") == "archive_mega_man_nes_us_manual")
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
        result = K.query_auto(q, topk=8)
        auto_domains = [d.get("domain") for d in (result.get("auto_routing") or {}).get("domains", [])]
        expected_auto_domain = expect_domain or (
            expected == "ambiguous_series" and not route.get("other_installment"))
        rows.append({"id": rid, "q": q, "expected": expected,
                     "actual": route["disposition"], "auto_domains": auto_domains,
                     "auto_status": result.get("status"), "auto_backend": result.get("backend"),
                     "ok": route["disposition"] == expected
                           and ((M.PRODUCTION_DOMAIN in auto_domains) == expected_auto_domain)
                           and (expected_auto_domain or not candidate_part(result).get("selected_evidence"))})
    return rows


def render_md(report):
    s = report["summary"]
    counts = report["question_counts"]
    lines = ["# 洛克人1候选v2生产自动路由验收", "", "## 结论", "",
             f"- 生产入口：`taspipe.kb.query_auto`；候选域：`{M.PRODUCTION_DOMAIN}`。",
             f"- 冻结 {counts['total']} 题：auto default {s['auto_default_ok']}/{counts['total']}；auto strict {s['auto_strict_ok']}/{counts['total']}。",
             f"- 隔离消费方：direct default {s['direct_default_ok']}/{counts['total']}；direct strict {s['direct_strict_ok']}/{counts['total']}。",
             f"- 路由边界：{s['route_ok']}/{s['route_total']}；失败关闭：{s['failure_close_ok']}/{s['failure_close_total']}。",
             f"- 错误候选出证：{s['wrong_candidate_evidence']}；阻断外层出证：{s['blocked_outer_evidence']}。",
             f"- 共享状态、旧候选与当前候选输入：{'全部未变' if report['isolation']['ok'] else '检测到变化'}。",
             "- 范围为 NTSC 美版 RAM/工具方法 + 官方说明书扫描核验短摘录；不是整款游戏知识库。", "",
             "## 逐题", "", "| ID | 类型 | default | strict | default 出证 | strict 出证 |",
             "|---|---|---|---|---|---|"]
    for row in report["questions"]:
        d = next(x for x in report["auto_cases"] if x["id"] == row["id"] and x["mode"] == "default")
        t = next(x for x in report["auto_cases"] if x["id"] == row["id"] and x["mode"] == "strict")
        dl = (candidate_part(d["result"]).get("selected_evidence") or [{}])[0].get("locator", "—")
        tl = (candidate_part(t["result"]).get("selected_evidence") or [{}])[0].get("locator", "—")
        lines.append(f"| {row['id']} | {row['expect']} | {d['result']['status']} | "
                     f"{t['result']['status']} | {dl or '—'} | {tl or '—'} |")
    lines += ["", "## 边界", "",
              "- 新增说明书题必须命中官方手册来源且保持唯一证据；旧 RAM/工具题仍命中原来源。",
              "- 中英文、全角与多空格别名自动进入候选；显式 revision 可提供缺别名问句身份。",
              "- 系列泛词要求补代次；洛克人10/20 不误路由；PAL-B/欧版拒答。",
              "- 多域问题保留域内证据，但外层不合并成 pass，也不给外层出证。",
              "- 索引缺失、哈希不符或出证资格失败均失败关闭，不回退生产文本索引。",
              "- MM10 目标时刻续作、MM11 角色创建系统、MM12 PAL-B 跨版等价仍拒答。",
              "- 完整商业手册扫描未进入候选或交付目录。", "",
              "## 产物", "",
              f"- 完整 JSON：`{REPORT_JSON.relative_to(ROOT).as_posix()}`",
              f"- 生产查询日志：`{AUTO_LOG.relative_to(ROOT).as_posix()}`",
              f"- 消费链日志：`{CONSUMER_LOG.relative_to(ROOT).as_posix()}`", ""]
    return "\n".join(lines)


def main():
    protected = [K.INDEX_JSON, K.hybrid_index_path(), K.CORPUS_MAP, S.REG_JSON, S.LEDGER_JSON,
                 K.KB_DIR / "query_log.jsonl", KE.DB_PATH,
                 ROOT / "选题决策层" / "kb快照" / "index.json",
                 M.INDEX_PATH, M.MAP_PATH, M.REGISTRY_PATH, M.FROZEN_QUESTIONS,
                 OLD_CANDIDATE / "index.json", OLD_CANDIDATE / "corpus_map.json",
                 OLD_CANDIDATE / "sources.json"]
    before = {str(p): snapshot(p) for p in protected}
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    if frozen["status"] != "frozen" or frozen["candidate_index_sha256"] != M.expected_index_sha256():
        raise RuntimeError("冻结题集或候选索引契约不一致")
    counts = frozen["expected_counts"]
    write_text(DIRECT_LOG, "")
    direct_rows, auto_rows, auto_log_rows, questions = [], [], [], []
    for item in frozen["questions"]:
        questions.append({"id": item["id"], "q": item["q"], "expect": item["expect"],
                          "manual_pages": item.get("manual_pages")})
        explicit = M.route_question(item["q"])["disposition"] == "not_matched"
        for mode in ("default", "strict"):
            direct = M.ask(item["q"], mode=mode, log_path=DIRECT_LOG,
                           assume_revision=True, production=True)
            direct_rows.append(grade_question(item, direct, mode, automatic=False))
            auto = K.query_auto(item["q"], revision=M.REVISION if explicit else None,
                                topk=8, top_window=3,
                                fragment_policy="strict" if mode == "strict" else None,
                                log_sink=auto_log_rows.append,
                                log_context={"entry_point": f"mm1-v2-production-eval-{mode}"})
            auto_rows.append(grade_question(item, auto, mode))
    write_text(AUTO_LOG, "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
                                for r in auto_log_rows))
    routes = route_cases()
    old_hash, old_index = M.expected_index_sha256, M.INDEX_PATH
    try:
        M.expected_index_sha256 = lambda: "0" * 64
        bad_hash = K.query_auto("洛克人1 的坐标轴方向是什么？")
        M.expected_index_sha256 = old_hash
        M.INDEX_PATH = HERE / "missing_index.json"
        missing_index = K.query_auto("洛克人1 的坐标轴方向是什么？")
    finally:
        M.expected_index_sha256, M.INDEX_PATH = old_hash, old_index
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
    probes = {name: compact(K.query_auto(q, **kwargs)) for name, q, kwargs in (
        ("controls", "洛克人1官方说明书里 A 键和 B 键分别控制什么动作？", {}),
        ("energy", "洛克人1 Energy Meter 监测的能量水平，受击与能量胶囊分别有什么影响？", {}),
        ("magnet_beam", "洛克人1官方说明书里 Magnet Beam 在哪个关卡出现，取得后能做什么？", {}),
        ("robot_masters", "洛克人1官方说明书里六名 Robot Master 各自的设计用途或专长是什么？", {}),
        ("series_ambiguous", "洛克人的坐标轴方向是什么？", {}),
        ("pal_refused", "洛克人1 PAL-B 的坐标表能直接照用吗？", {}),
        ("mm10_negative", "洛克人10 的坐标轴方向是什么？", {}),
        ("multi_kof", "洛克人1 的坐标轴和拳皇98 的简化连招分别是什么？", {}),
        ("non_candidate", "拳皇98 的简化连招是什么？", {}))}
    after = {str(p): snapshot(p) for p in protected}
    changed = [p for p in before if before[p] != after[p]]
    direct_log_rows = [json.loads(x) for x in DIRECT_LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    consumer_log_rows = [json.loads(x) for x in CONSUMER_LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    expected_logs = counts["total"] * 2
    summary = {
        "route_total": len(routes), "route_ok": sum(r["ok"] for r in routes),
        "direct_default_ok": sum(r["ok"] for r in direct_rows if r["mode"] == "default"),
        "direct_strict_ok": sum(r["ok"] for r in direct_rows if r["mode"] == "strict"),
        "auto_default_ok": sum(r["ok"] for r in auto_rows if r["mode"] == "default"),
        "auto_strict_ok": sum(r["ok"] for r in auto_rows if r["mode"] == "strict"),
        "failure_close_total": len(failure_rows), "failure_close_ok": sum(r["ok"] for r in failure_rows),
        "wrong_candidate_evidence": sum(bool(candidate_part(r["result"]).get("selected_evidence"))
                                        and r["expect"] != "strict_pass" for r in auto_rows),
        "blocked_outer_evidence": sum(bool(r["result"]["selected_evidence"])
                                      and r["expect"] == "refuse" for r in auto_rows),
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
        "manual_probes_pass": all(probes[n]["status"] == "pass" for n in
                                  ("controls", "energy", "magnet_beam", "robot_masters")),
        "manual_probe_sources": all((candidate_part(probes[n]).get("selected_evidence") or [{}])[0].get("source_id")
                                    == "archive_mega_man_nes_us_manual" for n in
                                    ("controls", "energy", "magnet_beam", "robot_masters")),
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
        "logs_complete": summary["direct_log_lines"] == expected_logs
                         and summary["auto_log_lines"] == expected_logs
                         and summary["consumer_log_lines"] == 1,
        "shared_old_and_candidate_inputs_unchanged": not changed,
    }
    report = {
        "schema_version": 2, "status": "evaluated_production_route_v2_manual",
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "consumer": "taspipe.kb.query_auto", "candidate_domain": M.PRODUCTION_DOMAIN,
        "candidate_revision": M.REVISION, "candidate_only": True,
        "whole_game_knowledge_base": False, "production_defaults_unchanged": True,
        "external_generative_model_calls": 0, "paid_api_calls": 0,
        "question_counts": counts, "summary": summary, "checks": checks,
        "all_ok": all(checks.values()), "questions": questions, "route_cases": routes,
        "direct_cases": direct_rows, "auto_cases": auto_rows, "failure_close": failure_rows,
        "probes": probes, "consumer_crosscheck": {"result": cross_result, "info": info},
        "hash_mismatch": compact(bad_hash), "missing_index": compact(missing_index),
        "isolation": {"ok": not changed, "changed_paths": changed, "before": before, "after": after},
        "query_logs": {
            "direct": {"path": str(DIRECT_LOG), "lines": len(direct_log_rows), "sha256": sha(DIRECT_LOG)},
            "auto": {"path": str(AUTO_LOG), "lines": len(auto_log_rows), "sha256": sha(AUTO_LOG)},
            "consumer": {"path": str(CONSUMER_LOG), "lines": len(consumer_log_rows), "sha256": sha(CONSUMER_LOG)}},
        "code_sha256": {name: sha(importlib.import_module(module).__file__) for name, module in
                        (("kb", "taspipe.kb"), ("kb_route", "taspipe.kb_route"),
                         ("kb_megaman1", "taspipe.kb_megaman1"),
                         ("kb_selftest_gates", "taspipe.kb_selftest_gates"))},
        "remaining": ["候选不是整款游戏知识库，官方说明书只收短摘录",
                      "PAL-B与其他版本跨版等价未验证",
                      "FM2导入与segmented TAS仍为reference_only，不能证明目标时刻续作流程",
                      "全部敌人、关卡与隐藏要素尚未形成完整覆盖"],
    }
    write_text(REPORT_JSON, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_text(REPORT_MD, render_md(report))
    print(json.dumps({"all_ok": report["all_ok"], "question_counts": counts,
                      "summary": summary, "checks": checks, "changed_paths": changed,
                      "report": str(REPORT_JSON)}, ensure_ascii=False, indent=2))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
