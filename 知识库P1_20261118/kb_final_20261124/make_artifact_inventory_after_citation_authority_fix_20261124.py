# -*- coding: utf-8 -*-
"""生成来源别名修正交付的逐件清单与 SHA-256。"""
import hashlib
import json
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124"
QC = OUT / "report_qc_after_citation_authority_fix_20261124"
MANIFEST = OUT / "final_manifest_after_citation_authority_fix_20261124.json"
JSON_PATH = OUT / "artifact_inventory_after_citation_authority_fix_20261124.json"
MD_PATH = OUT / "artifact_inventory_after_citation_authority_fix_20261124.md"
SCRIPT_PATH = OUT / "make_artifact_inventory_after_citation_authority_fix_20261124.py"
REPORT_MD = ROOT / "知识库改进优化指导_2026-11-24_来源别名修正回填.md"
REPORT_PDF = ROOT / "知识库改进优化指导_2026-11-24_来源别名修正回填.pdf"

ACTIVE = "是（生产默认未变）"
SHADOW = "否（strict 影子臂）"
TEST = "否（测试、审计或交付件）"
DATA = "是（生产索引/主数据）"
HISTORY = "否（历史快照，不作当前结论）"


def info(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def item(artifact_id, path, category, purpose, production, rerunnable, command=None):
    return {"id": artifact_id, "category": category, "purpose": purpose,
            "production_active": production, "rerunnable": rerunnable,
            "command": command, **info(path)}


def entries(qa):
    taspipe = ROOT / "_工具脚本/taspipe"
    game = taspipe / "游戏包"
    rows = [
        item("CODE-KB", taspipe / "kb.py", "生产代码",
             "知识库查询、判定、来源别名元数据透传与证据选择入口；默认参数未变。", ACTIVE, True),
        item("CODE-PROVENANCE", taspipe / "kb_provenance.py", "生产代码",
             "按 citation_authority 解析来源别名：未知编号不连坐，已知弱别名仍继承 reference_only。", SHADOW, True),
        item("CODE-KB-GATES", taspipe / "kb_selftest_gates.py", "生产测试代码",
             "KB 302 项闸门；含 [257]/[260]–[263] 的来源别名资格与反例。", TEST, True,
             "PYTHONUTF8=1 py -3 -u -m taspipe.kb_selftest_gates"),
        item("INDEX-BASE", game / "知识库/index.json", "生产索引",
             "773 块 BM25 base；本轮全部最终评测绑定 SHA 2a93e76d…。", DATA, True),
        item("INDEX-SNAPSHOT", ROOT / "选题决策层/kb快照/index.json", "生产快照",
             "新闻消费快照；由 make_snapshot() 同步，与 base 同 SHA。", DATA, True),
        item("INDEX-HYBRID", game / "知识库/index_hybrid.json", "排除臂",
             "787 块 hybrid 索引；未同步、未启用，不套用 base 成绩。", HISTORY, False),
        item("CORPUS-MAP", game / "知识库/corpus_map.json", "生产主数据",
             "语料与版本映射；来源别名资格的上游主数据。", DATA, True),
        item("SOURCES", game / "来源库/sources.json", "生产主数据",
             "来源资格、核验状态与版本归属。", DATA, True),
        item("ESPORTS-DB", game / "电竞事实库/facts_v1.db", "生产主数据",
             "电竞结构化事实库；四张动态表计数均为 0。", DATA, True),
        item("SELECTOR-SCRIPT", ROOT / "知识库P1_20261118/ph3_selector_sweep.py", "生产评测脚本",
             "26 题 + 60 探针，四种选择器/strict 臂全部调用生产 kb.query。", TEST, True,
             f'PYTHONUTF8=1 py -3 -u "{ROOT / "知识库P1_20261118/ph3_selector_sweep.py"}" <输出前缀>'),
        item("SELECTOR-JSON", OUT / "selector_sweep_after_citation_authority_fix_20261124.json", "当前评测",
             "base/scoped/scoped_beyond 26/26，replace 23/26，strict 21/26；四臂错误出证 0。", SHADOW, True),
        item("SELECTOR-MD", OUT / "selector_sweep_after_citation_authority_fix_20261124.md", "当前评测报告",
             "逐题与逐探针结果；strict 新放行 0。", SHADOW, True),
        item("SELECTOR-LOG", OUT / "selector_sweep_after_citation_authority_fix_20261124.log", "当前评测日志",
             "四臂逐题运行输出。", SHADOW, True),
        item("REGRESSION-SCRIPT", OUT / "strict_default_regression_after_citation_authority_fix_20261124.py", "隔离回归脚本",
             "复制索引到临时目录，经生产 kb.query 对照默认/strict，并反查真实状态。", TEST, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "strict_default_regression_after_citation_authority_fix_20261124.py"}"'),
        item("REGRESSION-JSON", OUT / "strict_default_regression_after_citation_authority_fix_20261124.json", "隔离回归结果",
             "默认 raw 13/v2 26；strict raw 7/v2 21；真实状态变化 0。", SHADOW, True),
        item("REGRESSION-LOG", OUT / "strict_default_regression_after_citation_authority_fix_20261124.log", "隔离回归日志",
             "26 题逐题默认/strict 状态与隔离摘要。", SHADOW, True),
        item("EVOLUTION-SCRIPT", OUT / "strict_alias_evolution_audit_after_citation_authority_fix_20261124.py", "演变审计脚本",
             "比较旧 strict 22、临时 25、当前 21；保留冻结标签。", TEST, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "strict_alias_evolution_audit_after_citation_authority_fix_20261124.py"}"'),
        item("EVOLUTION-MD", OUT / "strict_alias_evolution_audit_after_citation_authority_fix_20261124.md", "演变审计报告",
             "22/26→25/26→21/26 的规则、索引与探针变化。", SHADOW, True),
        item("EVOLUTION-JSON", OUT / "strict_alias_evolution_audit_after_citation_authority_fix_20261124.json", "演变审计结果",
             "冻结金标哈希、逐探针转移、X23 insufficient_source 一致性。", SHADOW, True),
        item("NEWS-SCRIPT", OUT / "news_snapshot_crosscheck_after_citation_authority_fix_20261124.py", "生产消费冒烟脚本",
             "经 crosscheck→query_auto 跑 7 问；QUERY_LOG 重定向到隔离文件。", TEST, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "news_snapshot_crosscheck_after_citation_authority_fix_20261124.py"}"'),
        item("NEWS-JSON", OUT / "news_snapshot_crosscheck_after_citation_authority_fix_20261124.json", "生产消费冒烟结果",
             "4 个窄事实 pass，3 个负向样例未误放行；真实状态未变。", TEST, True),
        item("NEWS-QLOG", OUT / "news_snapshot_crosscheck_after_citation_authority_fix_20261124.query_log.jsonl", "隔离查询日志",
             "7 个唯一问题；不是生产 query_log.jsonl。", TEST, True),
        item("NEWS-LOG", OUT / "news_snapshot_crosscheck_after_citation_authority_fix_20261124.log", "生产消费冒烟日志",
             "新闻快照同步与消费结果摘要。", TEST, True),
        item("GATE-PROJECT", OUT / "selftest_after_citation_authority_fix_20261124.log", "全项目闸门",
             "SELFTEST OK 1462/1462。", TEST, True, "PYTHONUTF8=1 py -3 -u -m taspipe.selftest"),
        item("GATE-KB", OUT / "kb_selftest_after_citation_authority_fix_20261124.log", "知识库闸门",
             "KB_SELFTEST OK 302/302。", TEST, True, "PYTHONUTF8=1 py -3 -u -m taspipe.kb_selftest_gates"),
        item("GATE-CROSS", OUT / "cross_platform_after_citation_authority_fix_20261124.log", "跨平台闸门",
             "CROSS_PLATFORM_SELFTEST OK 33/33。", TEST, True,
             "PYTHONUTF8=1 py -3 -u -m taspipe.cross_platform_selftest_gates"),
        item("GATE-TOPIC", OUT / "topic_selftest_after_citation_authority_fix_20261124.log", "选题层闸门",
             "166/166，FAIL 0。", TEST, True,
             f'PYTHONUTF8=1 py -3 -u "{ROOT / "选题决策层/自检.py"}"'),
        item("BLIND-JSON", OUT / "blind_eval_after_citation_authority_fix_20261124.json", "生产盲测",
             "26/26；错误出证 0；隔离 PASS。", TEST, True),
        item("BLIND-MD", OUT / "blind_eval_after_citation_authority_fix_20261124.md", "生产盲测报告",
             "26 题逐题结果。", TEST, True),
        item("BLIND-QLOG", OUT / "blind_eval_after_citation_authority_fix_20261124.query_log.jsonl", "隔离查询日志",
             "盲测重定向日志。", TEST, True),
        item("BLIND-LOG", OUT / "blind_eval_after_citation_authority_fix_20261124.log", "生产盲测日志",
             "盲测运行摘要。", TEST, True),
        item("HELDOUT-JSON", OUT / "heldout_eval_after_citation_authority_fix_20261124.json", "独立留出盲测",
             "16/16；错误出证 0；隔离 PASS。", TEST, True),
        item("HELDOUT-MD", OUT / "heldout_eval_after_citation_authority_fix_20261124.md", "独立留出报告",
             "16 题逐题结果。", TEST, True),
        item("HELDOUT-LOG", OUT / "heldout_eval_after_citation_authority_fix_20261124.log", "独立留出日志",
             "留出评测运行摘要。", TEST, True),
        item("FULLDOMAIN-JSON", OUT / "full_domain_eval_after_citation_authority_fix_20261124.json", "全域评测",
             "16/16；覆盖电竞静态、动态拒答、现代游戏与复古回归。", TEST, True),
        item("FULLDOMAIN-MD", OUT / "full_domain_eval_after_citation_authority_fix_20261124.md", "全域评测报告",
             "全域分类结果。", TEST, True),
        item("FULLDOMAIN-LOG", OUT / "full_domain_eval_after_citation_authority_fix_20261124.log", "全域评测日志",
             "全域评测运行摘要。", TEST, True),
        item("AUDIT-IDENTITY", OUT / "version_identity_audit_20261124.json", "版本身份审计",
             "六个 present_unverified 全部保留，promoted=[]。", TEST, True),
        item("MEGAMAN-READINESS", OUT.parent / "megaman1_corpus_readiness_20261124.md", "候选语料就绪度",
             "洛克人1候选边界与启用前硬缺口。", HISTORY, False),
        item("MEGAMAN-DRAFT", OUT.parent / "megaman1_questions_draft_20261124.json", "候选盲测草案",
             "12 题 draft_not_frozen；未接生产。", HISTORY, False),
        item("REPORT-MD", REPORT_MD, "当前交付正文",
             "来源别名修正的当前权威结论、历史版本、闸门与剩余缺口。", TEST, False),
        item("MANIFEST-SCRIPT", OUT / "make_final_manifest_after_citation_authority_fix_20261124.py", "总指纹脚本",
             "断言 773 块索引、当前代码哈希、四套闸门、评测、隔离与旧交付未覆盖。", TEST, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "make_final_manifest_after_citation_authority_fix_20261124.py"}"'),
        item("MANIFEST", MANIFEST, "当前总指纹",
             "索引、代码、评测、闸门、隔离、电竞动态表与旧交付证据。", TEST, True),
        item("MANIFEST-LOG", OUT / "make_final_manifest_after_citation_authority_fix_20261124.log", "总指纹日志",
             "总指纹生成摘要。", TEST, True),
        item("RENDER-SCRIPT", OUT / "render_qc_after_citation_authority_fix_20261124.py", "PDF 渲染与 QC",
             "Edge 打印 PDF，PyMuPDF/PIL 抽帧，检查溢出、页边界、空页与替换符。", TEST, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "render_qc_after_citation_authority_fix_20261124.py"}"'),
        item("RENDER-LOG", OUT / "render_after_citation_authority_fix_20261124.log", "PDF 渲染日志",
             "PDF 渲染与全部自动 QA 输出。", TEST, True),
        item("REPORT-PDF", REPORT_PDF, "当前交付 PDF",
             f'{qa["pages"]} 页；自动 QA {qa["check_count"]}/{qa["check_count"]}；首末页与第 {qa["section4_page"]} 页已抽帧。', TEST, False),
        item("QC-HTML", QC / "report.html", "PDF 中间件",
             "当前报告的本地 HTML 渲染源。", TEST, True),
        item("QC-JSON", QC / "render_qa.json", "PDF QA 结果",
             "页数、文本长度、DOM 溢出、页外文本块与逐项断言。", TEST, True),
        item("QC-CONTACT", QC / "contact_sheet.png", "全页联系表",
             f'{qa["pages"]} 页视觉总览。', TEST, True),
    ]
    for page in qa["snapshot_pages"]:
        label = "QC-FIRST" if page == 1 else "QC-LAST" if page == qa["pages"] else "QC-SECTION4" if page == qa["section4_page"] else f"QC-PAGE{page:02d}"
        rows.append(item(label, QC / f"page_{page:02d}.png", "PDF 抽帧",
                         f"第 {page} 页 1.5 倍抽帧，用于目视核对标题、表格与页边界。", TEST, True))
    historical = [
        "知识库改进优化指导_2026-11-24_实施回填.md",
        "知识库改进优化指导_2026-11-24_实施回填.pdf",
        "知识库改进优化指导_2026-11-24_最终加固回填.md",
        "知识库改进优化指导_2026-11-24_最终加固回填.pdf",
        "知识库改进优化指导_2026-11-24_strict片段修正回填.md",
        "知识库改进优化指导_2026-11-24_strict片段修正回填.pdf",
        "知识库P1_20261118/kb_final_20261124/final_manifest.json",
        "知识库P1_20261118/kb_final_20261124/final_manifest_post_provenance_20261124.json",
        "知识库P1_20261118/kb_final_20261124/selector_sweep_after_provenance.json",
        "知识库P1_20261118/kb_final_20261124/selector_sweep_after_strict_citation_fix_20261124.json",
        "知识库P1_20261118/kb_final_20261124/regression_after_strict_citation_fix_20261124.json",
        "知识库P1_20261118/kb_final_20261124/strict_probe_change_audit_after_citation_fix_20261124.json",
    ]
    for name in historical:
        rows.append(item("HISTORY-" + Path(name).stem.upper() + "-" + Path(name).suffix[1:].upper(),
                         ROOT / name, "历史参照",
                         "保留原样用于追溯；不得写成当前结果。", HISTORY, False))
    rows.extend([
        item("FINAL-VALIDATION-SCRIPT", OUT / "final_validation_after_citation_authority_fix_20261124.py", "最终核验脚本",
             "只读核对共享哈希、清单逐件哈希、PDF QA、闸门、隔离与旧交付。", TEST, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "final_validation_after_citation_authority_fix_20261124.py"}"'),
    ])
    rows.append(item("INVENTORY-SCRIPT", SCRIPT_PATH, "产物清单脚本",
                     "逐件读取字节与 SHA-256，生成本 Markdown 与 JSON。", TEST, True,
                     f'PYTHONUTF8=1 py -3 -u "{SCRIPT_PATH}"'))
    return rows


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    qa = json.loads((QC / "render_qa.json").read_text(encoding="utf-8"))
    assert all(qa["checks"].values())
    assert qa["section4_page"] is not None
    assert manifest["report_md"]["sha256"] == info(manifest["report_md"]["path"])["sha256"]
    assert manifest["prior_delivery_unchanged"]["ok"] is True
    rows = entries(qa)
    assert len({row["id"] for row in rows}) == len(rows)
    assert len({row["path"] for row in rows}) == len(rows)
    payload = {
        "schema": "kb_artifact_inventory_after_citation_authority_fix_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "当前来源别名修正交付件、生产主数据、闸门、评测、隔离证据与历史参照；清单自身不递归计算哈希。",
        "production_unchanged": manifest["production_unchanged"],
        "pdf_qa": {"pages": qa["pages"], "section4_page": qa["section4_page"],
                   "checks": qa["checks"], "all_passed": all(qa["checks"].values())},
        "artifact_count": len(rows),
        "artifacts": rows,
        "human_inventory": str(MD_PATH),
        "git": manifest["git"],
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json_info = info(JSON_PATH)
    lines = [
        "# 2026-11-24 来源别名修正产物清单", "",
        f"- 生成时间（UTC）：{payload['generated_at']}",
        f"- 登记件数：**{len(rows)}**；另有本 Markdown 与机器可读 JSON 两个清单容器。",
        "- 生产默认未变：`top_window=3`、`fragment_policy=None`、`fact_selector=None`；strict 为影子臂，当前 21/26。",
        "- 本轮重跑：26 题盲测、16 题留出、16 题全域、四套闸门、默认/strict 隔离回归、三代探针审计与新闻消费冒烟。",
        "- 历史报告与临时 strict 方案只作追溯，不写成当前结论。",
        "- 清单容器自身不递归计算哈希；JSON 的逐件记录覆盖全部被登记文件，本表额外登记 JSON 的哈希。",
        f"- PDF：{qa['pages']} 页；自动 QA {qa['check_count']}/{qa['check_count']} 项通过；首末页与第 {qa['section4_page']} 页已抽帧。",
        "", "## 逐件登记", "",
        "| ID | 文件 | 用途 | 生产状态 | 可复跑 | 字节 | SHA-256 |",
        "|---|---|---|---|---|---:|---|",
    ]
    for row in rows:
        rerun = "是" if row["rerunnable"] else "否"
        lines.append(f"| {row['id']} | [{Path(row['path']).name}]({Path(row['path']).as_uri()}) | "
                     f"{row['purpose']} | {row['production_active']} | {rerun} | {row['bytes']} | `{row['sha256']}` |")
    lines.extend([
        f"| INVENTORY-JSON | [{JSON_PATH.name}]({JSON_PATH.as_uri()}) | 本清单机器可读版，含全部登记件路径、用途、生产状态、字节与 SHA-256。 | 否（交付索引） | 是 | {json_info['bytes']} | `{json_info['sha256']}` |",
        "", "## 复核入口", "",
        f"- [当前总指纹]({MANIFEST.as_uri()})：索引、代码、评测、闸门、隔离与旧交付证据。",
        f"- [当前 PDF]({REPORT_PDF.as_uri()})：完整来源别名修正回填。",
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
