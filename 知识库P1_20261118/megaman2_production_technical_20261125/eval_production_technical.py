# -*- coding: utf-8 -*-
"""洛克人2生产技术域生产验收：真实 query_auto、对照、出卡与只读审计。"""
import hashlib
import importlib
import json
import re
import sys
import time
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parent
TOOLS = ROOT / "_工具脚本"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

from taspipe import detector_promotion as DP
from taspipe import detector_promotion_selftest as DPT
from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import kb_megaman2 as M
from taspipe import kb_route as KR
from taspipe import sources as S

KC = importlib.import_module("选题决策层.知识对照")
CARD = importlib.import_module("选题决策层.选题卡")
QC = HERE / "qc"
REPORT = HERE / "eval_report.json"
REPORT_MD = HERE / "eval_report.md"
QUERY_LOG = QC / "production_query_log.jsonl"
CROSS_LOG = QC / "crosscheck_query_log.jsonl"
CARDS_JSON = HERE / "cards.json"
CARDS_MD = HERE / "cards.md"
BASE_AUDIT = QC / "kb_audit_base.json"
HYBRID_AUDIT = QC / "kb_audit_hybrid.json"
SOURCE_AUDIT = QC / "sources_audit.json"

POSITIVE_SPECS = [
    {"id": "MM2T01", "q": "洛克人2 X 坐标向哪个方向增加？",
     "file": "mm2_tasvideos_coordinates_20261125.txt", "fact": "right",
     "hook": "洛克人2坐标轴方向", "axis": "coordinate"},
    {"id": "MM2T02", "q": "洛克人2 跳跃时 Y speed 初始值是什么？",
     "file": "mm2_tasvideos_jump_20261125.txt", "fact": "04.DF",
     "hook": "洛克人2跳跃Y轴初速度", "axis": "y"},
    {"id": "MM2T03", "q": "洛克人2 攀爬速度是多少？",
     "file": "mm2_tasvideos_climb_transform_20261125.txt", "fact": "00.C0",
     "hook": "洛克人2攀爬速度", "axis": "speed"},
    {"id": "MM2T04", "q": "洛克人2 跳跃时 X speed 是什么？",
     "file": "mm2_tasvideos_jump_horizontal_20261125.txt", "fact": "01.50",
     "hook": "洛克人2跳跃横向速度", "axis": "x"},
    {"id": "MM2T05", "q": "洛克人2 步行速度是多少？",
     "file": "mm2_tasvideos_walking_20261125.txt", "fact": "01.60",
     "hook": "洛克人2步行速度", "axis": "speed"},
    {"id": "MM2T06", "q": "洛克人2 从静止加速需要多少帧？",
     "file": "mm2_tasvideos_acceleration_20261125.txt", "fact": "7 frames",
     "hook": "洛克人2加速帧数", "axis": "frames"},
    {"id": "MM2T07", "q": "洛克人2 从全速停止需要多少帧？",
     "file": "mm2_tasvideos_acceleration_20261125.txt", "fact": "8 (decimal) frames",
     "hook": "洛克人2减速停止帧数", "axis": "frames"},
    {"id": "MM2T08", "q": "洛克人2 Xspd 内存地址范围是什么？",
     "file": "mm2_tasvideos_object_table_20261125.txt", "fact": "$600:$620",
     "hook": "洛克人2对象表Xspd地址", "axis": "address"},
]

REFUSAL_SPECS = [
    {"id": "MM2R01", "q": "洛克人2 PAL 版 walking speed",
     "status": "inconclusive", "refusal": "version_not_collected"},
    {"id": "MM2R02", "q": "MM2 JP ROM 的 walking speed 是什么？",
     "status": "inconclusive", "refusal": "version_not_collected"},
    {"id": "MM2R03", "q": "洛克人2 NTSC 美版 walking speed",
     "status": "inconclusive", "refusal": "version_not_collected"},
    {"id": "MM2R04", "q": "洛克人2 出招表",
     "status": "miss", "refusal": "move_list_not_collected"},
    {"id": "MM2R05", "q": "Mega Man 2: The Power Fighters walking speed",
     "status": "miss", "refusal": "ambiguous_series"},
    {"id": "MM2R06", "q": "洛克人2 有几个对象",
     "status": "miss", "refusal": "candidate_evidence_insufficient"},
]

REFERENCE_REVISIONS = [
    (M.MEMORY_REVISION, "洛克人2 内存地址是什么"),
    (M.CATALOG_REVISION, "洛克人2 销量是多少"),
    (M.TAS_REVISION, "洛克人2 TAS 有哪些"),
]

ARIA_PACKS = sorted((TOOLS / "taspipe/游戏包").glob("gba_aria_of_sorrow_souls.detectors*.showcase.json"))
REAL_PATHS = [
    K.INDEX_JSON,
    K.hybrid_index_path(),
    K.CORPUS_MAP,
    S.REG_JSON,
    S.MD_PATH,
    K.KB_DIR / "query_log.jsonl",
    KE.DB_PATH,
    ROOT / "选题决策层/kb快照/index.json",
    *ARIA_PACKS,
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


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def answer_text(result):
    if result.get("answer_text"):
        return result["answer_text"]
    answer = result.get("answer") or {}
    return answer.get("text", "") if answer.get("kind") == "evidence_excerpt" else ""


def compact(result):
    domains = []
    for row in result.get("domain_results") or []:
        domains.append({
            "domain": row.get("domain"), "status": row.get("status"),
            "refusal": row.get("refusal"), "reason_code": row.get("reason_code"),
            "backend": row.get("backend"), "index_used": row.get("index_used"),
            "index_sha256": row.get("index_sha256"), "answer_text": row.get("answer_text"),
            "selected_evidence": row.get("selected_evidence") or [],
            "hit_count": len(row.get("hits") or []),
            "candidate_only": row.get("candidate_only"),
            "whole_game_knowledge_base": row.get("whole_game_knowledge_base"),
            "production_route_wired": row.get("production_route_wired"),
        })
    return {
        "q": result.get("q"), "status": result.get("status"),
        "refusal": result.get("refusal"), "reason_code": result.get("reason_code"),
        "reason": result.get("reason"), "retrieval": result.get("retrieval"),
        "backend": result.get("backend"), "index_used": result.get("index_used"),
        "index_sha256": result.get("index_sha256"), "answer_text": answer_text(result),
        "selected_evidence": result.get("selected_evidence") or [],
        "hit_count": len(result.get("hits") or []),
        "hits": result.get("hits") or [], "route": result.get("route"),
        "candidate_route": result.get("candidate_route"),
        "auto_routing": result.get("auto_routing"),
        "domain_results": domains, "candidate_only": result.get("candidate_only"),
        "whole_game_knowledge_base": result.get("whole_game_knowledge_base"),
        "production_route_wired": result.get("production_route_wired"),
        "fragment_policy": result.get("fragment_policy"),
    }


def checks_ok(checks):
    return all(row["ok"] for row in checks)


def grade_positive(spec, entry, mode, result, production_sha, source, evidence_paths):
    checks = []

    def check(name, value):
        checks.append({"name": name, "ok": bool(value)})

    selected = result.get("selected_evidence") or []
    text = answer_text(result)
    route = result.get("candidate_route") or result.get("route") or {}
    check("status_pass", result.get("status") == "pass")
    if entry == "auto":
        check("backend", result.get("backend") == "megaman2")
    else:
        check("backend", (result.get("query_log") or {}).get("caller") == "kb_megaman2.ask")
    check("revision", route.get("revision") == M.TECHNICAL_REVISION)
    check("index_identity", result.get("index_used") == "index.json"
          and result.get("index_sha256") == production_sha)
    check("production_boundary", result.get("candidate_only") is False
          and result.get("whole_game_knowledge_base") is False
          and result.get("production_route_wired") is True)
    check("one_selected", len(selected) == 1)
    if entry == "auto":
        auto = result.get("auto_routing") or {}
        check("single_domain", auto.get("mode") == "single"
              and [d.get("domain") for d in auto.get("domains") or []] == ["megaman2"])
        check("default_not_strict", mode != "default" or result.get("fragment_policy") is None)
    if selected:
        hit = selected[0]
        locator = hit.get("locator") or ""
        source_path = locator.split("#L", 1)[0]
        check("source", hit.get("source_id") == M.PRODUCTION_SOURCE_ID)
        check("hit_revision", hit.get("revision") == M.TECHNICAL_REVISION)
        check("qualified", hit.get("status") == "verified_read"
              and hit.get("authority") == "authoritative")
        check("expected_file", spec["file"] in locator)
        check("registered_evidence_path", str(S.resolve_path(source_path)) in evidence_paths)
        check("line_locator", bool(re.search(r"#L\d+(?:-L\d+)?$", locator)))
        check("fact", spec["fact"] in text)
        check("axis", M._speed_axis_ok(spec["q"], text))
        if mode == "strict":
            check("strict_fragment", (hit.get("fragment_provenance") or {}).get("eligible") is True)
    check("source_verified", source.get("status") == "verified_read")
    return {"id": spec["id"], "q": spec["q"], "entry": entry, "mode": mode,
            "axis": spec["axis"], "expected_file": spec["file"], "expected_fact": spec["fact"],
            "ok": checks_ok(checks), "checks": checks, "result": compact(result)}


def grade_refusal(spec, result):
    checks = [
        {"name": "status", "ok": result.get("status") == spec["status"]},
        {"name": "refusal", "ok": result.get("refusal") == spec["refusal"]},
        {"name": "no_evidence", "ok": not result.get("selected_evidence")},
        {"name": "no_retrieval", "ok": not result.get("hits")},
    ]
    return {"id": spec["id"], "q": spec["q"], "expected_status": spec["status"],
            "expected_refusal": spec["refusal"], "ok": checks_ok(checks),
            "checks": checks, "result": compact(result)}


def make_card(spec, cross):
    source_name = "TASVideos GameResources NES/Rockman/Data — Rockman 2 技术条目"
    return {
        "core_hook": spec["hook"], "event_id": spec["id"], "profile_id": "retro_tech",
        "attention": "中", "evidence_status": cross.get("status"), "queue": "技术验收",
        "sources": [source_name], "source_count": 1, "item_count": 1,
        "evidence_note": "TASVideos 原文技术条目；来源范围内可答，不证明地区 ROM 等价",
        "first_seen": "2026-11-25", "pub_latest": "",
        "title_only_note": "本题用真实生产 query_auto 出证",
        "core_hook_note": "只覆盖已登记技术事实，不扩展为整款游戏结论",
        "dims": {}, "must_mention": "必须同时交代来源范围与 PAL/美版/日版 ROM 等价未验证",
        "urls": ["https://tasvideos.org/GameResources/NES/Rockman/Data"],
        "judged_at": "2026-11-25", "rule_version": "mm2-production-technical-v1",
        "kb": cross,
    }


def render_report_md(report):
    lines = [
        "# 洛克人2生产技术域生产验收",
        "",
        f"- 生成时间：`{report['taken_at']}`",
        f"- 总结论：**{report['status']}**",
        "- 范围：TASVideos 原文明确记载的 Rockman 2 技术子域，不是整款游戏知识库。",
        "- 边界：不证明 PAL/美版/日版 ROM 等价；候选说明书、内存字典、目录与 TAS 元数据不升格。",
        "",
        "## 1. 生产正例与七文件覆盖",
        "",
        f"- 正例：{report['summary']['positive_ok']}/{report['summary']['positive_total']}",
        f"- 覆盖取证：{len(report['evidence_coverage']['covered_files'])}/{len(report['evidence_coverage']['registered_files'])} 份",
        "",
        "| ID | 问题 | 取证文件 | 必须命中 | default/auto | strict/auto |",
        "|---|---|---|---|---|---|",
    ]
    for spec in POSITIVE_SPECS:
        rows = [r for r in report["positive"] if r["id"] == spec["id"] and r["entry"] == "auto"]
        default = next(r for r in rows if r["mode"] == "default")
        strict = next(r for r in rows if r["mode"] == "strict")
        lines.append(f"| {spec['id']} | {spec['q']} | `{spec['file']}` | `{spec['fact']}` | "
                     f"{'通过' if default['ok'] else '失败'} | {'通过' if strict['ok'] else '失败'} |")
    lines += [
        "",
        "## 2. 失败关闭与恒量反证",
        "",
        "| ID | 探针 | 预期 | 实际 | 结果 |",
        "|---|---|---|---|---|",
    ]
    for row in report["negative"]:
        result = row["result"]
        expected = row.get("expected_refusal") or row.get("expected_reason_code") or "candidate_only"
        actual = result.get("refusal") or result.get("reason_code") or str(result.get("candidate_only"))
        lines.append(f"| {row['id']} | {row['q']} | `{expected}` | `{actual}` | "
                     f"{'通过' if row['ok'] else '失败'} |")
    lines += [
        "",
        "## 3. 选题对照与出卡",
        "",
        f"- crosscheck：{report['consumer']['crosscheck_ok']}/{len(POSITIVE_SPECS)} 通过，"
        f"unanchored 降级 {report['consumer']['unanchored_downgraded']}。",
        f"- 选题卡：{report['consumer']['cards_ok']}/{len(POSITIVE_SPECS)} 张带唯一出证。",
        "- 卡片由真实 `知识对照.crosscheck()` 结果送入现有 `选题卡.render_card_md()`，不是手写证据摘要。",
        "",
        "## 4. 审计与共享状态",
        "",
        "| 审计 | pass | fail | inconclusive | 状态 |",
        "|---|---:|---:|---:|---|",
    ]
    for name, key in (("生产 base", "base"), ("生产 hybrid", "hybrid"), ("来源库", "sources")):
        audit = report["audits"][key]
        counts = audit["counts"]
        lines.append(f"| {name} | {counts['pass']} | {counts['fail']} | {counts['inconclusive']} | {audit['status']} |")
    lines += [
        "",
        f"- 评测期间共享文件漂移：{len(report['isolation']['changed_paths'])}。",
        f"- 生产索引 SHA-256：`{report['indexes']['base']['sha256']}`",
        f"- hybrid 索引 SHA-256：`{report['indexes']['hybrid']['sha256']}`",
        "",
        "## 5. 复现与产物",
        "",
        "- [生产契约](contract.json)",
        "- [范围与未覆盖项](scope.json)",
        "- [评测脚本](eval_production_technical.py)",
        "- [机器可读报告](eval_report.json)",
        "- [生产查询日志](qc/production_query_log.jsonl)",
        "- [crosscheck 日志](qc/crosscheck_query_log.jsonl)",
        "- [选题卡 JSON](cards.json)",
        "- [选题卡 Markdown](cards.md)",
        "",
        "外部生成模型调用 0；付费 API 调用 0；未重启后端；strict 只作显式影子臂，dense/NLI 未评也未升默认。",
    ]
    atomic_text(REPORT_MD, "\n".join(lines) + "\n")


def main():
    QC.mkdir(parents=True, exist_ok=True)
    before = {str(path): snapshot(path) for path in REAL_PATHS}
    production_sha = sha(K.INDEX_JSON)
    registry = S.load_registry(S.REG_JSON)
    source = next(row for row in registry["sources"] if row["source_id"] == M.PRODUCTION_SOURCE_ID)
    evidence_paths = {str(S.resolve_path(path).resolve()) for path in source["evidence"]}
    if source["status"] != "verified_read" or len(evidence_paths) != len(POSITIVE_SPECS) - 1:
        raise RuntimeError("生产来源资格或七份取证登记不符合合同")

    query_rows = []
    positive = []
    for spec in POSITIVE_SPECS:
        for mode in ("default", "strict"):
            direct = M.ask(spec["q"], mode=mode, production=True, topk=5)
            if direct.get("query_log"):
                query_rows.append(direct["query_log"])
            positive.append(grade_positive(spec, "direct", mode, direct,
                                           production_sha, source, evidence_paths))
            auto = K.query_auto(spec["q"], topk=5,
                                fragment_policy="strict" if mode == "strict" else None,
                                log_sink=query_rows.append,
                                log_context={"entry_point": "mm2-production-technical-eval-auto"})
            positive.append(grade_positive(spec, "auto", mode, auto,
                                           production_sha, source, evidence_paths))

    negative = []
    for spec in REFUSAL_SPECS:
        result = K.query_auto(spec["q"], topk=5, log_sink=query_rows.append,
                              log_context={"entry_point": "mm2-production-technical-eval-refusal"})
        negative.append(grade_refusal(spec, result))

    multi_q = "洛克人2 的 walking speed 和拳皇98 的必杀射门分别是什么？"
    multi = K.query_auto(multi_q, topk=5, log_sink=query_rows.append,
                         log_context={"entry_point": "mm2-production-technical-eval-multi"})
    domain = next((row for row in multi.get("domain_results") or []
                   if row.get("domain") == "megaman2"), {})
    domain_selected = domain.get("selected_evidence") or []
    multi_checks = [
        {"name": "outer_split", "ok": multi.get("status") == "inconclusive"
         and multi.get("refusal") == "multi_domain_needs_split"},
        {"name": "outer_no_evidence", "ok": multi.get("selected_evidence") == []},
        {"name": "domain_pass", "ok": domain.get("status") == "pass" and len(domain_selected) == 1},
        {"name": "domain_production_boundary", "ok": domain.get("candidate_only") is False
         and domain.get("production_route_wired") is True
         and domain.get("whole_game_knowledge_base") is False},
    ]
    negative.append({"id": "MM2R07", "q": multi_q, "ok": checks_ok(multi_checks),
                     "checks": multi_checks, "result": compact(multi),
                     "megaman2_domain": compact(domain)})

    for rid, revision, question in [
        ("MM2R08", M.MEMORY_REVISION, "洛克人2 内存地址是什么"),
        ("MM2R09", M.CATALOG_REVISION, "洛克人2 销量是多少"),
        ("MM2R10", M.TAS_REVISION, "洛克人2 TAS 有哪些"),
    ]:
        result = K.query_auto(question, revision=revision, topk=5,
                              log_sink=query_rows.append,
                              log_context={"entry_point": "mm2-production-technical-eval-reference-gate"})
        row_checks = [
            {"name": "not_produced", "ok": result.get("status") == "inconclusive"
             and result.get("reason_code") == "revision_not_produced"},
            {"name": "no_retrieval", "ok": not result.get("hits")},
            {"name": "no_evidence", "ok": not result.get("selected_evidence")},
        ]
        negative.append({"id": rid, "q": question, "revision": revision,
                         "expected_reason_code": "revision_not_produced",
                         "ok": checks_ok(row_checks), "checks": row_checks,
                         "result": compact(result)})

    missing = QC / "missing.index.json"
    missing_result = K.query_auto("洛克人2 步行速度是多少？", topk=5,
                                  index_path=missing, map_path=K.CORPUS_MAP, reg=registry,
                                  log_sink=query_rows.append,
                                  log_context={"entry_point": "mm2-production-technical-eval-missing"})
    missing_checks = [
        {"name": "unavailable", "ok": missing_result.get("status") == "inconclusive"
         and missing_result.get("reason_code") == "candidate_unavailable"},
        {"name": "no_retrieval", "ok": not missing_result.get("hits")},
        {"name": "no_evidence", "ok": not missing_result.get("selected_evidence")},
    ]
    negative.append({"id": "MM2R11", "q": "洛克人2 步行速度是多少？（索引缺失反证）",
                     "ok": checks_ok(missing_checks), "checks": missing_checks,
                     "result": compact(missing_result)})

    for rid, question, wrong_text in [
        ("MM2R12", "洛克人2 跳跃时 X speed 是什么？",
         "when Rockman jumps, his Y speed is set to 04.DF"),
        ("MM2R13", "洛克人2 跳跃时 Y speed 是什么？",
         "during jumping, Rockman’s X speed is 01.50"),
    ]:
        with patch.object(M, "_retrieval_query", return_value=wrong_text):
            result = K.query_auto(question, topk=5, log_sink=query_rows.append,
                                  log_context={"entry_point": "mm2-production-technical-eval-axis-counterproof"})
        axis_checks = [
            {"name": "axis_rejected", "ok": result.get("status") == "inconclusive"
             and result.get("reason_code") == "candidate_evidence_invalid"},
            {"name": "no_evidence", "ok": not result.get("selected_evidence")},
        ]
        negative.append({"id": rid, "q": question, "injected_wrong_axis_text": wrong_text,
                         "ok": checks_ok(axis_checks), "checks": axis_checks,
                         "result": compact(result)})

    manual_q = "洛克人2美版官方说明书里 Metal Blade 的投掷方向、数量和用途是什么？"
    manual = K.query_auto(manual_q, topk=5, log_sink=query_rows.append,
                          log_context={"entry_point": "mm2-production-technical-eval-manual-boundary"})
    manual_selected = manual.get("selected_evidence") or []
    manual_checks = [
        {"name": "candidate_only", "ok": manual.get("candidate_only") is True},
        {"name": "manual_source", "ok": len(manual_selected) == 1
         and manual_selected[0].get("source_id") == M.MANUAL_SOURCE_ID},
        {"name": "candidate_index", "ok": manual.get("index_sha256") == M.expected_index_sha256()
         and manual.get("index_sha256") != production_sha},
    ]
    negative.append({"id": "MM2R14", "q": manual_q, "ok": checks_ok(manual_checks),
                     "checks": manual_checks, "result": compact(manual)})

    atomic_text(QUERY_LOG, "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                                   for row in query_rows))

    old_cross_log = KC.QUERY_LOG
    KC.QUERY_LOG = CROSS_LOG
    try:
        cross, cross_info = KC.crosscheck(
            [{"event_id": spec["id"], "titles": [spec["q"]]} for spec in POSITIVE_SPECS],
            mode="bm25", index_path=K.INDEX_JSON)
    finally:
        KC.QUERY_LOG = old_cross_log

    cards = [make_card(spec, cross[spec["id"]]) for spec in POSITIVE_SPECS]
    card_mds = [CARD.render_card_md(card) for card in cards]
    atomic_text(CARDS_JSON, json.dumps(cards, ensure_ascii=False, indent=2) + "\n")
    atomic_text(CARDS_MD, "# 洛克人2生产技术域验收选题卡\n\n" + "\n\n".join(card_mds) + "\n")

    base_audit = K.audit(index_path=K.INDEX_JSON)
    hybrid_audit = K.audit(index_path=K.hybrid_index_path())
    source_audit = S.audit()
    atomic_text(BASE_AUDIT, json.dumps(base_audit, ensure_ascii=False, indent=2) + "\n")
    atomic_text(HYBRID_AUDIT, json.dumps(hybrid_audit, ensure_ascii=False, indent=2) + "\n")
    atomic_text(SOURCE_AUDIT, json.dumps(source_audit, ensure_ascii=False, indent=2) + "\n")

    covered = set()
    for row in positive:
        if row["entry"] != "auto" or row["mode"] != "default" or not row["ok"]:
            continue
        for hit in row["result"]["selected_evidence"]:
            covered.add(str(S.resolve_path(hit["locator"].split("#L", 1)[0]).resolve()))
    historical_contract = load(BASE / "megaman2_candidate_20261125/contract.json")
    after = {str(path): snapshot(path) for path in REAL_PATHS}
    changed = [path for path in before if before[path] != after[path]]
    positive_ok = sum(row["ok"] for row in positive)
    negative_ok = sum(row["ok"] for row in negative)
    cross_ok = sum(row.get("status") == "pass" and len(row.get("selected_evidence") or []) == 1
                   for row in cross.values())
    cards_ok = sum("KB出证" in md and bool(card["kb"].get("selected_evidence"))
                   and card["kb"]["selected_evidence"][0]["locator"] in md
                   for card, md in zip(cards, card_mds))
    indexes = {}
    for name, path in (("base", K.INDEX_JSON), ("hybrid", K.hybrid_index_path())):
        index = K.load_index(path)
        indexes[name] = {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size,
                         "mtime_ns": path.stat().st_mtime_ns, "sha256": sha(path),
                         "chunks": len(index["chunks"]), "files": len(index["files"]),
                         "pipeline": index.get("pipeline")}
    evidence = []
    for path_text in source["evidence"]:
        path = S.resolve_path(path_text)
        evidence.append({"path": path_text, "bytes": path.stat().st_size, "sha256": sha(path)})
    checks = {
        "positive_all_ok": positive_ok == len(positive),
        "negative_all_ok": negative_ok == len(negative),
        "seven_file_coverage_complete": covered == evidence_paths,
        "single_registered_source": len({row["result"]["selected_evidence"][0]["source_id"]
                                         for row in positive if row["ok"]}) == 1,
        "base_audit_no_fail": base_audit["counts"]["fail"] == 0,
        "hybrid_audit_no_fail": hybrid_audit["counts"]["fail"] == 0,
        "source_audit_no_fail": source_audit["counts"]["fail"] == 0,
        "crosscheck_all_pass": cross_ok == len(POSITIVE_SPECS)
                               and cross_info.get("unanchored_downgraded") == 0,
        "cards_all_have_evidence": cards_ok == len(POSITIVE_SPECS),
        "shared_state_unchanged": not changed,
        "historical_candidate_not_rewritten": historical_contract.get("domain") == "megaman2_candidate"
                                              and historical_contract.get("production_route_wired") is False,
        "production_defaults_unchanged": all(row["result"].get("fragment_policy") is None
                                             for row in positive if row["entry"] == "auto" and row["mode"] == "default"),
    }
    report = {
        "schema_version": 1, "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "洛克人2 TASVideos 生产技术子域；不是整款游戏知识库",
        "production_index_sha256": production_sha, "source_id": M.PRODUCTION_SOURCE_ID,
        "revision": M.TECHNICAL_REVISION,
        "summary": {"positive_total": len(positive), "positive_ok": positive_ok,
                    "negative_total": len(negative), "negative_ok": negative_ok,
                    "crosscheck_ok": cross_ok, "cards_ok": cards_ok,
                    "query_log_lines": len(query_rows)},
        "checks": checks, "positive": positive, "negative": negative,
        "evidence_coverage": {"registered_files": sorted(str(S.resolve_path(p)) for p in source["evidence"]),
                              "covered_files": sorted(covered),
                              "missing_files": sorted(evidence_paths - covered),
                              "evidence": evidence},
        "consumer": {"crosscheck": cross, "crosscheck_info": cross_info,
                     "cards": [{"event_id": card["event_id"], "status": card["evidence_status"],
                                "selected_count": len(card["kb"].get("selected_evidence") or [])}
                               for card in cards],
                     "crosscheck_ok": cross_ok, "cards_ok": cards_ok,
                     "unanchored_downgraded": cross_info.get("unanchored_downgraded")},
        "audits": {"base": base_audit, "hybrid": hybrid_audit, "sources": source_audit},
        "indexes": indexes, "source": source,
        "isolation": {"ok": not changed, "changed_paths": changed, "before": before, "after": after},
        "query_log": {"path": str(QUERY_LOG), "lines": len(query_rows), "sha256": sha(QUERY_LOG)},
        "crosscheck_log": {"path": str(CROSS_LOG), "sha256": sha(CROSS_LOG)},
        "cards": {"json": str(CARDS_JSON), "markdown": str(CARDS_MD),
                  "json_sha256": sha(CARDS_JSON), "markdown_sha256": sha(CARDS_MD)},
        "code_sha256": {name: sha(Path(module.__file__)) for name, module in
                        (("detector_promotion", DP), ("detector_promotion_selftest", DPT),
                         ("kb", K), ("kb_route", KR), ("kb_megaman2", M), ("sources", S))},
        "external_generative_model_calls": 0, "paid_api_calls": 0,
        "backend_restart_performed": False,
    }
    atomic_text(REPORT, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    render_report_md(report)
    print(json.dumps({"status": report["status"], "summary": report["summary"], "checks": checks,
                      "changed_paths": changed, "report": str(REPORT)}, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
