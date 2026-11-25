# -*- coding: utf-8 -*-
"""验证洛克人1候选路由与隔离问答消费方，并生成可审计结果。"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
TOOLS = ROOT / "_工具脚本"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / "知识库小样_20261118"))

from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import kb_megaman1 as M
from taspipe import sources as S
import eval_common as E

CANDIDATE = BASE / "megaman1_candidate_20261125"
FROZEN = BASE / "megaman1_questions_frozen_20261125.json"
OUT_JSON = BASE / "megaman1_candidate_consumer_eval_20261125.json"
OUT_MD = BASE / "megaman1_candidate_consumer_eval_20261125.md"
LOG = CANDIDATE / "qc" / "consumer_query_log_20261125.jsonl"
NEWS = ROOT / "选题决策层" / "kb快照" / "index.json"
REAL_PATHS = [K.INDEX_JSON, K.CORPUS_MAP, S.REG_JSON, S.LEDGER_JSON,
              K.KB_DIR / "query_log.jsonl", KE.DB_PATH, NEWS,
              K.KB_DIR / "index_hybrid.json", K.KB_DIR / "terms_hybrid.json"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(path):
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {"present": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": sha(path)}


def write_text(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def render_md(report):
    s = report["summary"]
    lines = [f"# 洛克人1候选路由与消费方验收 · {report['taken_at']}", "",
             "- 范围：NTSC 美版洛克人1的 RAM/工具方法隔离候选；不是整款游戏知识库。",
             f"- 路由反例：{s['route_ok']}/{s['route_total']}",
             f"- 冻结题消费：default {s['default_ok']}/12；strict {s['strict_ok']}/12",
             f"- 错误出证：default {s['default_wrong']}；strict {s['strict_wrong']}",
             f"- 候选消费日志：{report['query_log']['lines']} 行；"
             f"失败关闭检查 {report['failure_close']['ok']}/{report['failure_close']['total']}",
             f"- 真实共享状态前后一致：{report['isolation']['ok']}", "",
             "## 路由反例", "", "| 用例 | 判定 | 通过 |", "|---|---|---|"]
    for row in report["route_cases"]:
        lines.append(f"| {row['id']} | {row['actual']} | {row['ok']} |")
    lines += ["", "## 冻结题逐题", "", "| 题 | 档 | default | strict | 出证定位 |",
              "|---|---|---|---|---|"]
    for row in report["questions"]:
        loc = row["default"].get("selected_locator") or "-"
        lines.append(f"| {row['id']} | {row['expect']} | "
                     f"{row['default']['ok']} | {row['strict']['ok']} | {loc} |")
    lines += ["", "## 边界", "",
              "- 只有显式洛克人1别名，或调用方显式提供该 revision 上下文，才进入候选检索。",
              "- PAL-B/欧版、系列泛词、其他作品、跨游戏合并问题均不进入候选检索。",
              "- 索引缺失或 SHA 不符时失败关闭，不回退生产索引。",
              "- 本消费方未改生产 DOMAINS、生产 corpus map、生产 index 或知识对照.py。",
              "- 官方说明书级玩法语料和整款游戏覆盖仍是后续门槛。", ""]
    return "\n".join(lines)


def main():
    before = {str(p): snapshot(p) for p in REAL_PATHS}
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    if frozen["candidate_index_sha256"] != M.EXPECTED_INDEX_SHA256:
        raise RuntimeError("消费方冻结索引契约与题集不一致")
    route_specs = [
        ("R01", "洛克人1 的坐标轴方向是什么？", "candidate"),
        ("R02", "洛克人 １ 的坐标轴方向是什么？", "candidate"),
        ("R03", "Ｍｅｇａ　Ｍａｎ　１ 的坐标轴方向是什么？", "candidate"),
        ("R04", "rockman 1 的坐标轴方向是什么？", "candidate"),
        ("R05", "洛克人 的坐标轴方向是什么？", "ambiguous_series"),
        ("R06", "Mega Man X 的坐标轴方向是什么？", "ambiguous_series"),
        ("R07", "洛克人2 的坐标轴方向是什么？", "ambiguous_series"),
        ("R08", "洛克人1 PAL-B 的坐标表能直接照用吗？", "version_not_collected"),
        ("R09", "Mega Man 1 欧版的坐标表能直接照用吗？", "version_not_collected"),
        ("R10", "拳皇98 的坐标轴方向是什么？", "not_matched"),
        ("R11", "洛克人1 和拳皇98 的坐标轴分别是什么？", "multi_domain_needs_split"),
        ("R12", "owned 和 current_weapon 两个内存字段分别对应什么？", "not_matched"),
        ("R13", "洛克人1 NTSC 美版的坐标轴方向是什么？", "candidate"),
    ]
    route_cases = []
    for rid, q, expect in route_specs:
        route = M.route_question(q)
        actual = route["disposition"]
        ok = actual == expect
        asked = M.ask(q)
        no_retrieval = actual == "candidate" or (
            asked["index_used"] is None and not asked["selected_evidence"])
        route_cases.append({"id": rid, "q": q, "expected": expect, "actual": actual,
                            "ok": ok and no_retrieval, "blocked_no_retrieval": no_retrieval,
                            "route": route})

    LOG.parent.mkdir(parents=True, exist_ok=True)
    write_text(LOG, "")
    question_rows = []
    for item in frozen["questions"]:
        row = {"id": item["id"], "q": item["q"], "expect": item["expect"]}
        explicit_context = item.get("filters", {}).get("revision") == M.REVISION
        for mode in ("default", "strict"):
            result = M.ask(item["q"], mode=mode, log_path=LOG,
                           assume_revision=explicit_context)
            grade = E.grade_v2(item, result)
            route_ok = result["route"]["disposition"] in {"candidate", "version_not_collected"}
            evidence_ok = item["expect"] != "refuse" or not result["selected_evidence"]
            index_ok = result["index_sha256"] in {None, M.EXPECTED_INDEX_SHA256}
            row[mode] = {**grade, "route_ok": route_ok, "evidence_ok": evidence_ok,
                         "index_ok": index_ok, "status": result["status"],
                         "refusal": result["refusal"], "reason": result["reason"],
                         "route_disposition": result["route"]["disposition"],
                         "selected_locator": grade["selected_locator"],
                         "ok": grade["ok"] and route_ok and evidence_ok and index_ok}
        question_rows.append(row)

    with tempfile.TemporaryDirectory(prefix="mm1-consumer-close-") as tmp:
        bad = Path(tmp) / "bad_index.json"
        bad.write_text("{}", encoding="utf-8")
        missing = Path(tmp) / "missing_index.json"
        with mock.patch.object(M, "INDEX_PATH", bad):
            bad_result = M.ask("洛克人1 的坐标轴方向是什么？")
        with mock.patch.object(M, "INDEX_PATH", missing):
            missing_result = M.ask("洛克人1 的坐标轴方向是什么？")
    generic_plain = M.ask("owned 和 current_weapon 两个内存字段分别对应什么？")
    generic_explicit = M.ask("owned 和 current_weapon 两个内存字段分别对应什么？",
                             assume_revision=True)
    close_rows = [
        {"id": "FC01", "ok": bad_result["refusal"] == "candidate_hash_mismatch"
         and bad_result["index_used"] is None and not bad_result["selected_evidence"]},
        {"id": "FC02", "ok": missing_result["refusal"] == "candidate_unavailable"
         and missing_result["index_used"] is None and not missing_result["selected_evidence"]},
        {"id": "FC03", "ok": generic_plain["refusal"] == "candidate_domain_not_matched"
         and generic_plain["index_used"] is None},
        {"id": "FC04", "ok": generic_explicit["status"] == "pass"
         and generic_explicit["route"]["disposition"] == "candidate"},
    ]
    after = {str(p): snapshot(p) for p in REAL_PATHS}
    changed = [p for p in before if before[p] != after[p]]
    log_rows = [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    default_grades = [r["default"] for r in question_rows]
    strict_grades = [r["strict"] for r in question_rows]
    report = {
        "status": "evaluated_isolated_candidate_consumer",
        "taken_at": "2026-11-25",
        "consumer": "taspipe.kb_megaman1.ask",
        "candidate_revision": M.REVISION,
        "candidate_index": str(M.INDEX_PATH),
        "candidate_index_sha256": M.EXPECTED_INDEX_SHA256,
        "production_route_wired": False,
        "production_consumer_wired": False,
        "production_defaults_unchanged": True,
        "external_generative_model_calls": 0,
        "paid_api_calls": 0,
        "summary": {
            "route_total": len(route_cases),
            "route_ok": sum(r["ok"] and r["blocked_no_retrieval"] for r in route_cases),
            "default_ok": sum(g["ok"] for g in default_grades),
            "strict_ok": sum(g["ok"] for g in strict_grades),
            "default_wrong": sum(g["wrong_evidence"] for g in default_grades),
            "strict_wrong": sum(g["wrong_evidence"] for g in strict_grades),
            "default_missed": sum(g["missed_answer"] for g in default_grades),
            "strict_missed": sum(g["missed_answer"] for g in strict_grades),
        },
        "route_cases": route_cases,
        "questions": question_rows,
        "failure_close": {"rows": close_rows, "ok": sum(r["ok"] for r in close_rows),
                          "total": len(close_rows)},
        "query_log": {"path": str(LOG), "lines": len(log_rows),
                      "sha256": sha(LOG),
                      "entry_points": sorted({r.get("entry_point") for r in log_rows}),
                      "retrieval_rows": sum(r.get("retrieval") != "not_run" for r in log_rows),
                      "blocked_rows": sum(r.get("retrieval") == "not_run" for r in log_rows)},
        "isolation": {"ok": not changed, "changed_paths": changed,
                      "real_state_before": before, "real_state_after": after},
        "remaining": ["官方说明书级玩法语料未建立", "整款游戏覆盖未建立",
                      "PAL-B 跨版等价未验证", "生产 DOMAINS/corpus map/index 未接线"],
    }
    write_text(OUT_JSON, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_text(OUT_MD, render_md(report))
    all_ok = (report["summary"]["route_ok"] == len(route_cases)
              and report["summary"]["default_ok"] == len(question_rows)
              and report["summary"]["strict_ok"] == len(question_rows)
              and report["failure_close"]["ok"] == report["failure_close"]["total"]
              and report["isolation"]["ok"] and len(log_rows) == 24)
    print(f"CONSUMER_OK route={report['summary']['route_ok']}/{len(route_cases)} "
          f"default={report['summary']['default_ok']}/12 strict={report['summary']['strict_ok']}/12 "
          f"wrong={report['summary']['default_wrong']}/{report['summary']['strict_wrong']} "
          f"failclose={report['failure_close']['ok']}/4 logs={len(log_rows)} unchanged={not changed}")
    print(str(OUT_JSON))
    print(str(OUT_MD))
    return 0 if all_ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
