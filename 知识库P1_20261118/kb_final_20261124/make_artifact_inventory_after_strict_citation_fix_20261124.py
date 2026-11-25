# -*- coding: utf-8 -*-
"""生成 strict 片段修正交付的逐件清单与哈希。"""
import hashlib
import json
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124"
QC = OUT / "report_qc_after_strict_citation_fix_20261124"
MANIFEST = OUT / "final_manifest_after_strict_citation_fix_20261124.json"
JSON_PATH = OUT / "artifact_inventory_after_strict_citation_fix_20261124.json"
MD_PATH = OUT / "artifact_inventory_after_strict_citation_fix_20261124.md"
SCRIPT_PATH = OUT / "make_artifact_inventory_after_strict_citation_fix_20261124.py"
REPORT_MD = ROOT / "知识库改进优化指导_2026-11-24_strict片段修正回填.md"
REPORT_PDF = ROOT / "知识库改进优化指导_2026-11-24_strict片段修正回填.pdf"

PRODUCTION_ACTIVE = "是（生产默认参数未变）"
OPT_IN_ONLY = "仅 strict 显式开启"
NOT_PRODUCTION = "否（测试、审计或交付件）"
SHADOW_ONLY = "否（影子评测）"
CANDIDATE_ONLY = "否（候选，未接入生产）"
REUSED_BASELINE = "复用基线；生产默认未变"


def info(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def item(artifact_id, path, category, purpose, production, rerunnable, command=None):
    return {"id": artifact_id, "category": category, "purpose": purpose,
            "production_active": production, "rerunnable": rerunnable,
            "command": command, **info(path)}


def entries(qa):
    taspipe = ROOT / "_工具脚本/taspipe"
    rows = [
        item("CODE-KB", taspipe / "kb.py", "生产代码",
             "知识库查询、判定与证据选择入口；top_window=3、fragment_policy=None、fact_selector=None 保持不变。",
             PRODUCTION_ACTIVE, True),
        item("CODE-PROVENANCE", taspipe / "kb_provenance.py", "生产代码",
             "裸来源编号不连坐降级；显式转述/参考/待核段仍降级；同主张撤回冲突仍拒绝出证。",
             OPT_IN_ONLY, True),
        item("CODE-KB-GATES", taspipe / "kb_selftest_gates.py", "生产测试代码",
             "知识库独立闸门 [255]–[259]：裸 S1、显式转述反例、Q02–Q05 金标、Q01 拦截和待实测作用域。",
             NOT_PRODUCTION, True, "PYTHONUTF8=1 py -3 -u -m taspipe.kb_selftest_gates"),
        item("STRICT-AUDIT-SCRIPT", OUT / "audit_strict_probe_changes_after_citation_fix_20261124.py", "逐臂审计脚本",
             "对照旧 strict、当前默认与当前 strict，登记 X03/X04/X23 恢复及 X23 冻结标注冲突。",
             NOT_PRODUCTION, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "audit_strict_probe_changes_after_citation_fix_20261124.py"}"'),
        item("STRICT-AUDIT-MD", OUT / "strict_probe_change_audit_after_citation_fix_20261124.md", "逐臂审计报告",
             "strict grade_v2 22/26→25/26；X03/X04/X23 恢复；相对默认新增放行 0；X23 保留 insufficient_source。",
             SHADOW_ONLY, True),
        item("STRICT-AUDIT-JSON", OUT / "strict_probe_change_audit_after_citation_fix_20261124.json", "逐臂审计结果",
             "冻结标签、选中块、片段来源资格、Q02–Q05 金标一致与真实状态隔离的机器可读记录。",
             SHADOW_ONLY, True),
        item("REGRESSION-SCRIPT", OUT / "regression_after_strict_citation_fix_20261124.py", "回归脚本",
             "经生产 K.query 对照默认臂与 strict 臂，并保护索引、来源库、台账、电竞库和查询日志。",
             NOT_PRODUCTION, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "regression_after_strict_citation_fix_20261124.py"}"'),
        item("REGRESSION", OUT / "regression_after_strict_citation_fix_20261124.json", "回归结果",
             "原始 status=pass 默认 13、strict 12；仅拦 Q01；无新增通过；真实状态隔离 PASS。",
             SHADOW_ONLY, True),
        item("REGRESSION-LOG", OUT / "regression_after_strict_citation_fix_20261124.log", "回归日志",
             "strict 修正后默认/strict 逐题对照运行摘要。",
             SHADOW_ONLY, True),
        item("SELECTOR-JSON", OUT / "selector_sweep_after_strict_citation_fix_20261124.json", "选择器影子评测",
             "base/scoped/scoped_beyond 26/26，replace 23/26，strict_fragments 25/26；四臂错误出证 0。",
             SHADOW_ONLY, False),
        item("SELECTOR-MD", OUT / "selector_sweep_after_strict_citation_fix_20261124.md", "选择器影子报告",
             "26 题与 60 探针逐题结果；strict 探针新放行 []，仍拦 X05/X17/X19/X20/X22/X30。",
             SHADOW_ONLY, False),
        item("SELECTOR-LOG", OUT / "selector_sweep_after_strict_citation_fix_20261124.log", "选择器运行日志",
             "四臂逐题运行摘要。",
             SHADOW_ONLY, False),
        item("GATE-PROJECT", OUT / "selftest_after_strict_citation_fix_20261124.log", "全项目闸门日志",
             "strict 修正后串行重跑：SELFTEST OK 1447/1447。",
             NOT_PRODUCTION, True, "PYTHONUTF8=1 py -3 -u -m taspipe.selftest"),
        item("GATE-KB", OUT / "kb_selftest_after_strict_citation_fix_20261124.log", "知识库闸门日志",
             "strict 修正后串行重跑：KB_SELFTEST OK 292/292。",
             NOT_PRODUCTION, True, "PYTHONUTF8=1 py -3 -u -m taspipe.kb_selftest_gates"),
        item("GATE-CROSS", OUT / "cross_platform_after_strict_citation_fix_20261124.log", "跨平台闸门日志",
             "strict 修正后串行重跑：CROSS_PLATFORM_SELFTEST OK 33/33。",
             NOT_PRODUCTION, True),
        item("GATE-TOPIC", OUT / "topic_selftest_after_strict_citation_fix_20261124.log", "选题层闸门日志",
             "strict 修正后串行重跑：166/166；T15a–T15h 真实状态隔离 PASS。",
             NOT_PRODUCTION, True,
             f'PYTHONUTF8=1 py -3 -u "{ROOT / "选题决策层/自检.py"}"'),
        item("BLIND-JSON", OUT / "blind_eval_after_strict_citation_fix_20261124.json", "生产盲测结果",
             "strict 修正后重跑生产 query_auto：26/26，错误证据 0，隔离 PASS。",
             NOT_PRODUCTION, True),
        item("BLIND-MD", OUT / "blind_eval_after_strict_citation_fix_20261124.md", "生产盲测报告",
             "26 题生产盲测逐题人读结果。",
             NOT_PRODUCTION, True),
        item("BLIND-QLOG", OUT / "blind_eval_after_strict_citation_fix_20261124.query_log.jsonl", "隔离查询日志",
             "盲测重定向查询日志；不是生产 query_log.jsonl。",
             NOT_PRODUCTION, True),
        item("BLIND-LOG", OUT / "blind_eval_after_strict_citation_fix_20261124.log", "生产盲测日志",
             "strict 修正后生产盲测运行摘要。",
             NOT_PRODUCTION, True),
        item("HELDOUT-JSON", OUT / "heldout_eval_post_provenance_20261124.json", "复用留出盲测",
             "16/16，错误证据 0，隔离 PASS；生产 fragment_policy=None 未变，本轮未重跑并明确标为复用。",
             REUSED_BASELINE, True),
        item("FULLDOMAIN-JSON", OUT / "full_domain_eval_post_provenance_20261124.json", "复用全域评测",
             "16/16；动态空域拒答；生产 fragment_policy=None 未变，本轮未重跑并明确标为复用。",
             REUSED_BASELINE, True),
        item("COVERAGE-JSON", OUT / "kb_coverage_final.json", "复用覆盖看板",
             "文本、电竞、查询日志与版本覆盖快照。",
             REUSED_BASELINE, True),
        item("NEWS-SMOKE", OUT / "news_snapshot_crosscheck.json", "复用新闻消费冒烟",
             "新闻快照同步与真实消费入口；真实查询日志未改。",
             REUSED_BASELINE, True),
        item("AUDIT-IDENTITY", OUT / "version_identity_audit_20261124.json", "复用身份审计",
             "六个 present_unverified 版本全部保留；promoted=[]。",
             REUSED_BASELINE, True),
        item("AUDIT-KB", OUT / "audit_post_provenance_20261124.json", "复用知识库审计",
             "生产 kb.audit：inconclusive，pass 6 / fail 0 / inconclusive 3。",
             REUSED_BASELINE, True),
        item("AUDIT-SOURCES", OUT / "sources_audit_final.json", "复用来源库审计",
             "来源支撑审计 fail 0。",
             REUSED_BASELINE, True),
        item("MEGAMAN-READINESS", ROOT / "知识库P1_20261118/megaman1_corpus_readiness_20261124.md", "候选语料就绪度",
             "洛克人1候选语料可做隔离索引，但未满足生产启用条件。",
             CANDIDATE_ONLY, False),
        item("MEGAMAN-DRAFT", ROOT / "知识库P1_20261118/megaman1_questions_draft_20261124.json", "独立盲测草案",
             "12 题 draft_not_frozen；未冻结金标、未接生产。",
             CANDIDATE_ONLY, False),
        item("REPORT-MD", REPORT_MD, "strict 修正交付正文",
             "独立副本；§13/§14 历史数字降级，§15 为当前权威结论；旧实施回填与最终加固回填未覆盖。",
             NOT_PRODUCTION, False),
        item("MANIFEST-SCRIPT", OUT / "make_final_manifest_after_strict_citation_fix_20261124.py", "总指纹生成脚本",
             "校验770块基线、四套串行闸门、strict 25/26、Q01 单拦、X23 冲突与旧交付哈希。",
             NOT_PRODUCTION, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "make_final_manifest_after_strict_citation_fix_20261124.py"}"'),
        item("MANIFEST", MANIFEST, "strict 修正总指纹",
             "索引、代码、评测、闸门、逐臂审计、隔离证据、生产默认与旧交付未覆盖证据。",
             NOT_PRODUCTION, True),
        item("RENDER-SCRIPT", OUT / "render_qc_after_strict_citation_fix_20261124.py", "PDF 渲染与 QC 脚本",
             "用本地 Edge、PyMuPDF 和 PIL 渲染独立报告，检查溢出、页边界、空页、替换符、首末页与 §15。",
             NOT_PRODUCTION, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "render_qc_after_strict_citation_fix_20261124.py"}"'),
        item("RENDER-LOG", OUT / "render_after_strict_citation_fix_20261124.log", "PDF 渲染运行日志",
             "strict PDF 渲染与全部自动 QA 检查的完整输出。",
             NOT_PRODUCTION, True),
        item("REPORT-PDF", REPORT_PDF, "strict 修正交付 PDF",
             f'{qa["pages"]} 页独立副本；自动 QA {qa["check_count"]}/{qa["check_count"]} 项通过；首末页与 §15 抽帧。',
             NOT_PRODUCTION, False),
        item("QC-HTML", QC / "report.html", "PDF 中间渲染件",
             "strict 报告的本地 HTML 渲染源，用于 PDF 打印与 DOM 溢出检查。",
             NOT_PRODUCTION, True),
        item("QC-JSON", QC / "render_qa.json", "PDF QA 结果",
             f'页数、§15 页码、文本长度、DOM 溢出、页外文本块及 {qa["check_count"]} 项检查。',
             NOT_PRODUCTION, True),
        item("QC-CONTACT", QC / "contact_sheet.png", "全页联系表",
             f'{qa["pages"]} 页缩略图总览，用于发现空页、断表、异常留白和标题漂移。',
             NOT_PRODUCTION, True),
    ]
    for page in qa["snapshot_pages"]:
        label = "QC-FIRST" if page == 1 else "QC-LAST" if page == qa["pages"] else "QC-SECTION15"
        if page == qa["section15_page"]:
            label = "QC-SECTION15"
        elif page not in (1, qa["pages"]):
            label = f"QC-PAGE{page:02d}"
        rows.append(item(label, QC / f"page_{page:02d}.png", "PDF 抽帧",
                         f'第 {page} 页 1.5 倍抽帧，用于标题、表格和页边界目视核对。',
                         NOT_PRODUCTION, True))
    for name in ("知识库改进优化指导_2026-11-24_实施回填.md",
                 "知识库改进优化指导_2026-11-24_实施回填.pdf",
                 "知识库改进优化指导_2026-11-24_最终加固回填.md",
                 "知识库改进优化指导_2026-11-24_最终加固回填.pdf",
                 "知识库P1_20261118/kb_final_20261124/final_manifest.json",
                 "知识库P1_20261118/kb_final_20261124/final_manifest_post_provenance_20261124.json"):
        rows.append(item("BASELINE-" + Path(name).stem.upper() + "-" + Path(name).suffix[1:].upper(),
                         ROOT / name, "旧交付基线",
                         "旧交付保持原样；总指纹记录其哈希并断言未变化。",
                         NOT_PRODUCTION, False))
    rows.append(item("INVENTORY-SCRIPT", SCRIPT_PATH, "产物清单生成脚本",
                     "逐件读取字节与 SHA-256，生成本 Markdown 及机器可读 JSON。",
                     NOT_PRODUCTION, True,
                     f'PYTHONUTF8=1 py -3 -u "{SCRIPT_PATH}"'))
    return rows


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    qa = json.loads((QC / "render_qa.json").read_text(encoding="utf-8"))
    assert all(qa["checks"].values())
    assert qa["section15_page"] is not None
    assert manifest["report_md"]["sha256"] == info(manifest["report_md"]["path"])["sha256"]
    assert manifest["prior_delivery_unchanged"]["ok"] is True
    rows = entries(qa)
    assert len({row["id"] for row in rows}) == len(rows)
    assert len({row["path"] for row in rows}) == len(rows)
    payload = {
        "schema": "kb_artifact_inventory_after_strict_citation_fix_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "strict 修正新增件、明确标记的复用基线与旧交付未覆盖证据；清单自身不递归计算哈希。",
        "production_unchanged": manifest["production_unchanged"],
        "pdf_qa": {"pages": qa["pages"], "section15_page": qa["section15_page"],
                   "checks": qa["checks"], "all_passed": all(qa["checks"].values())},
        "artifact_count": len(rows),
        "artifacts": rows,
        "human_inventory": str(MD_PATH),
        "git": manifest["git"],
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json_info = info(JSON_PATH)
    lines = [
        "# 2026-11-24 strict 片段修正产物清单", "",
        f"- 生成时间（UTC）：{payload['generated_at']}",
        f"- 登记件数：**{len(rows)}**；另有本 Markdown 与机器可读 JSON 两个清单容器。",
        "- 生产默认未变：`top_window=3`、`fragment_policy=None`、`fact_selector=None`；strict 仍为影子臂；X23 冻结标签未改。",
        "- 留出盲测与全域评测明确标为复用基线；本轮重跑件为生产盲测、四套串行闸门、strict 回归与探针审计。",
        "- 清单容器自身不递归计算哈希；JSON 的逐件记录覆盖全部被登记文件，本表额外登记 JSON 的哈希。",
        f"- PDF：{qa['pages']} 页；自动 QA {qa['check_count']}/{qa['check_count']} 项通过；首末页与第 {qa['section15_page']} 页 §15 已抽帧。",
        "", "## 逐件登记", "",
        "| ID | 文件 | 用途 | 生产状态 | 可复跑 | 字节 | SHA-256 |",
        "|---|---|---|---|---|---:|---|",
    ]
    for row in rows:
        rerun = "是" if row["rerunnable"] else "否"
        lines.append(
            f"| {row['id']} | [{Path(row['path']).name}]({Path(row['path']).as_uri()}) | "
            f"{row['purpose']} | {row['production_active']} | {rerun} | {row['bytes']} | `{row['sha256']}` |"
        )
    lines.extend([
        f"| INVENTORY-JSON | [{JSON_PATH.name}]({JSON_PATH.as_uri()}) | 本清单的机器可读版，含全部登记件路径、用途、生产状态、字节与 SHA-256。 | 否（交付索引） | 是 | {json_info['bytes']} | `{json_info['sha256']}` |",
        "", "## 复核入口", "",
        f"- [strict 总指纹]({MANIFEST.as_uri()})：生产状态、逐臂审计、四套闸门、隔离与旧交付哈希。",
        f"- [strict PDF]({REPORT_PDF.as_uri()})：完整修正回填。",
        f"- [PDF QA]({(QC / 'render_qa.json').as_uri()})：{qa['check_count']} 项自动检查。",
        f"- [全页联系表]({(QC / 'contact_sheet.png').as_uri()})：{qa['pages']} 页视觉总览。",
        "",
    ])
    MD_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"markdown": str(MD_PATH), "json": str(JSON_PATH),
                      "artifact_count": len(rows), "pages": qa["pages"],
                      "qa_checks": qa["check_count"], "json_sha256": json_info["sha256"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
