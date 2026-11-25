# -*- coding: utf-8 -*-
"""生成最终加固交付的逐件清单与哈希。"""
import hashlib
import json
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124"
QC = OUT / "report_qc_post_provenance_20261124"
MANIFEST = OUT / "final_manifest_post_provenance_20261124.json"
JSON_PATH = OUT / "artifact_inventory_post_provenance_20261124.json"
MD_PATH = OUT / "artifact_inventory_post_provenance_20261124.md"
SCRIPT_PATH = OUT / "make_artifact_inventory_post_provenance_20261124.py"

PRODUCTION_ACTIVE = "是（生产默认参数未变）"
OPT_IN_ONLY = "仅 strict 显式开启"
NOT_PRODUCTION = "否（测试、审计或交付件）"
SHADOW_ONLY = "否（影子评测）"
CANDIDATE_ONLY = "否（候选，未接入生产）"


def info(path):
    path = Path(path)
    data = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def item(artifact_id, path, category, purpose, production, rerunnable, command=None):
    return {
        "id": artifact_id,
        "category": category,
        "purpose": purpose,
        "production_active": production,
        "rerunnable": rerunnable,
        "command": command,
        **info(path),
    }


def entries():
    taspipe = ROOT / "_工具脚本/taspipe"
    rows = [
        item("CODE-KB", taspipe / "kb.py", "生产代码",
             "知识库查询、判定与证据选择入口；top_window=3、fragment_policy=None、fact_selector=None 保持不变。",
             PRODUCTION_ACTIVE, True),
        item("CODE-PROVENANCE", taspipe / "kb_provenance.py", "生产代码",
             "片段级来源资格、二手/转述识别、本地实测覆盖继承上下文、同主张撤回冲突判定。",
             OPT_IN_ONLY, True),
        item("CODE-KB-GATES", taspipe / "kb_selftest_gates.py", "生产测试代码",
             "知识库独立闸门；新增 [252]–[254] 三条来源资格反例。",
             NOT_PRODUCTION, True, 'PYTHONUTF8=1 py -3 -u -m taspipe.kb_selftest_gates'),
        item("AUDIT-IDENTITY-SCRIPT", OUT / "audit_identity_20261124.py", "身份审计脚本",
             "通过生产 registry.index_roms 与 sources.resolve_identity 核对六个版本的本地身份。",
             NOT_PRODUCTION, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "audit_identity_20261124.py"}"'),
        item("AUDIT-IDENTITY", OUT / "version_identity_audit_20261124.json", "身份审计结果",
             "六个 present_unverified 版本全部保留；promoted=[]，身份证据不冒充机制权威。",
             NOT_PRODUCTION, True),
        item("REGRESSION-SCRIPT", OUT / "regression_after_provenance_20261124.py", "回归脚本",
             "经生产 K.query 对照默认臂与 strict 臂，并保护索引、来源库、台账、电竞库和查询日志。",
             NOT_PRODUCTION, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "regression_after_provenance_20261124.py"}"'),
        item("REGRESSION", OUT / "regression_after_provenance_20261124.json", "回归结果",
             "原始 status=pass 从 13 降为 8；Q01–Q05 被 strict 拦截，无新增通过，真实状态隔离 PASS。",
             SHADOW_ONLY, True),
        item("REGRESSION-LOG", OUT / "regression_after_provenance_20261124.log", "回归日志",
             "默认臂与 strict 臂逐题对照的运行日志。",
             SHADOW_ONLY, True),
        item("SELECTOR", OUT / "selector_sweep_after_provenance.json", "选择器影子评测",
             "base/scoped/scoped_beyond 26/26，replace 23/26，strict_fragments 22/26；错误证据均为 0。",
             SHADOW_ONLY, True),
        item("SELECTOR-MD", OUT / "selector_sweep_after_provenance.md", "选择器影子报告",
             "选择器逐题结果、回归 ID 与扩展探针拦截 ID 的人读版。",
             SHADOW_ONLY, True),
        item("AUDIT-KB", OUT / "audit_post_provenance_20261124.json", "知识库审计",
             "生产 kb.audit 结果：inconclusive，pass 6 / fail 0 / inconclusive 3。",
             NOT_PRODUCTION, True),
        item("GATE-PROJECT", OUT / "selftest_post_provenance_20261124.log", "全项目闸门日志",
             "最终加固后串行重跑：SELFTEST OK 1438/1438。",
             NOT_PRODUCTION, True, "PYTHONUTF8=1 py -3 -u -m taspipe.selftest"),
        item("GATE-KB", OUT / "kb_selftest_post_provenance_20261124.log", "知识库闸门日志",
             "最终加固后串行重跑：KB_SELFTEST OK 287/287。",
             NOT_PRODUCTION, True, "PYTHONUTF8=1 py -3 -u -m taspipe.kb_selftest_gates"),
        item("GATE-CROSS", OUT / "cross_platform_post_provenance_20261124.log", "跨平台闸门日志",
             "最终加固后串行重跑：CROSS_PLATFORM_SELFTEST OK 33/33。",
             NOT_PRODUCTION, True),
        item("GATE-TOPIC", OUT / "topic_selftest_post_provenance_20261124.log", "选题层闸门日志",
             "选题决策层 166/166；T15a–T15h 验证真实反馈库、产出、缓存、探针和查询日志未改。",
             NOT_PRODUCTION, True,
             f'PYTHONUTF8=1 py -3 -u "{ROOT / "选题决策层/自检.py"}"'),
        item("BLIND-JSON", OUT / "blind_eval_post_provenance_20261124.json", "生产盲测结果",
             "旧盲测集经生产 query_auto 重跑：26/26，错误证据 0，隔离 PASS。",
             NOT_PRODUCTION, True),
        item("BLIND-MD", OUT / "blind_eval_post_provenance_20261124.md", "生产盲测报告",
             "26 题生产盲测逐题人读结果。",
             NOT_PRODUCTION, True),
        item("BLIND-QLOG", OUT / "blind_eval_post_provenance_20261124.query_log.jsonl", "隔离查询日志",
             "盲测重定向查询日志；不是生产 query_log.jsonl。",
             NOT_PRODUCTION, True),
        item("BLIND-LOG", OUT / "blind_eval_post_provenance_20261124.log", "生产盲测运行日志",
             "生产盲测入口运行摘要。",
             NOT_PRODUCTION, True),
        item("HELDOUT-JSON", OUT / "heldout_eval_post_provenance_20261124.json", "留出盲测结果",
             "独立留出集 16/16：strict_pass 12、refuse 3、version_guard 1；错误证据 0，隔离 PASS。",
             NOT_PRODUCTION, True),
        item("HELDOUT-MD", OUT / "heldout_eval_post_provenance_20261124.md", "留出盲测报告",
             "16 题留出集逐题人读结果。",
             NOT_PRODUCTION, True),
        item("HELDOUT-QLOG", OUT / "heldout_eval_post_provenance_20261124.query_log.jsonl", "隔离查询日志",
             "留出盲测重定向查询日志；不是生产 query_log.jsonl。",
             NOT_PRODUCTION, True),
        item("HELDOUT-LOG", OUT / "heldout_eval_post_provenance_20261124.log", "留出盲测运行日志",
             "留出盲测入口运行摘要。",
             NOT_PRODUCTION, True),
        item("FULLDOMAIN-JSON", OUT / "full_domain_eval_post_provenance_20261124.json", "全域评测结果",
             "复古、现代游戏与电竞静态/动态/跨域共 16/16；不拿动态空表顶替真实数据。",
             NOT_PRODUCTION, True),
        item("FULLDOMAIN-MD", OUT / "full_domain_eval_post_provenance_20261124.md", "全域评测报告",
             "全域 16 题分类与人读结果。",
             NOT_PRODUCTION, True),
        item("FULLDOMAIN-LOG", OUT / "full_domain_eval_post_provenance_20261124.log", "全域评测运行日志",
             "全域评测入口运行摘要。",
             NOT_PRODUCTION, True),
        item("MEGAMAN-READINESS", ROOT / "知识库P1_20261118/megaman1_corpus_readiness_20261124.md", "候选语料就绪度",
             "洛克人1候选语料可做隔离索引与草案，但未满足生产启用条件。",
             CANDIDATE_ONLY, False),
        item("MEGAMAN-DRAFT", ROOT / "知识库P1_20261118/megaman1_questions_draft_20261124.json", "独立盲测草案",
             "12 题 draft_not_frozen；MM10来源资格与MM07–MM09治理映射仍是冻结阻塞项。",
             CANDIDATE_ONLY, False),
        item("REPORT-MD", ROOT / "知识库改进优化指导_2026-11-24_最终加固回填.md", "最终实施回填",
             "独立最终加固副本；原实施回填 MD/PDF 未覆盖。",
             NOT_PRODUCTION, False),
        item("MANIFEST-SCRIPT", OUT / "make_final_manifest_post_provenance_20261124.py", "清单生成脚本",
             "校验770块基线、快照、回归、身份审计和MM1草案后生成总指纹。",
             NOT_PRODUCTION, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "make_final_manifest_post_provenance_20261124.py"}"'),
        item("MANIFEST", MANIFEST, "最终总指纹",
             "索引、快照、代码、评测、闸门、审计、身份核对、隔离证据与生产默认值的总清单。",
             NOT_PRODUCTION, True),
        item("RENDER-SCRIPT", OUT / "render_qc_post_provenance_20261124.py", "PDF渲染与QC脚本",
             "用本地Edge、PyMuPDF和PIL渲染独立报告，检查溢出、页边界、空页、替换符、首末页与联系表。",
             NOT_PRODUCTION, True,
             f'PYTHONUTF8=1 py -3 -u "{OUT / "render_qc_post_provenance_20261124.py"}"'),
        item("RENDER-LOG", OUT / "render_post_provenance_20261124.log", "PDF渲染运行日志",
             "最终PDF渲染和16项QA检查的完整运行输出。",
             NOT_PRODUCTION, True),
        item("REPORT-PDF", ROOT / "知识库改进优化指导_2026-11-24_最终加固回填.pdf", "最终实施回填PDF",
             "15页独立最终副本；自动QA 16/16项通过，并完成首末页及§14表格目视核对。",
             NOT_PRODUCTION, False),
        item("QC-HTML", QC / "report.html", "PDF中间渲染件",
             "最终报告的本地HTML渲染源，用于PDF打印与DOM溢出检查。",
             NOT_PRODUCTION, True),
        item("QC-JSON", QC / "render_qa.json", "PDF QA结果",
             "页数、文本长度、DOM溢出、页外文本块及16项检查结果。",
             NOT_PRODUCTION, True),
        item("QC-CONTACT", QC / "contact_sheet.png", "全页联系表",
             "15页缩略图总览，用于发现空页、断表、异常留白和标题漂移。",
             NOT_PRODUCTION, True),
        item("QC-PAGE01", QC / "page_01.png", "首页抽帧",
             "PDF首页1.5倍抽帧，核对标题、副标题和旧版数字声明。",
             NOT_PRODUCTION, True),
        item("QC-PAGE14", QC / "page_14.png", "加固章节抽帧",
             "§14首页抽帧，核对来源资格说明与最终串行回归表。",
             NOT_PRODUCTION, True),
        item("QC-PAGE15", QC / "page_15.png", "末页抽帧",
             "PDF末页抽帧，核对六版本结论、MM1边界与交付索引。",
             NOT_PRODUCTION, True),
        item("COVERAGE-JSON", OUT / "kb_coverage_final.json", "复用覆盖看板",
             "文本、电竞、查询日志和版本覆盖快照；本轮总清单继续引用。",
             NOT_PRODUCTION, True),
        item("COVERAGE-MD", OUT / "kb_coverage_final.md", "复用覆盖报告",
             "覆盖看板人读版；本轮报告继续引用。",
             NOT_PRODUCTION, True),
        item("NEWS-SMOKE", OUT / "news_snapshot_crosscheck.json", "复用新闻消费冒烟",
             "验证新闻快照同步与真实消费入口；真实查询日志未改。",
             NOT_PRODUCTION, True),
        item("NEWS-QLOG", OUT / "news_snapshot_crosscheck.query_log.jsonl", "复用隔离冒烟日志",
             "新闻消费冒烟的重定向查询日志；不是生产查询日志。",
             NOT_PRODUCTION, True),
        item("SOURCES-AUDIT", OUT / "sources_audit_final.json", "复用来源库审计",
             "90条来源、23个知识包、87/87要素有来源支撑；fail 0。",
             NOT_PRODUCTION, True),
        item("UNVERIFIED-INVENTORY", OUT / "unverified_source_inventory_20261124.json", "复用未验证来源清单",
             "六个present_unverified版本的来源审计输入；promoted=[]。",
             NOT_PRODUCTION, False),
        item("INVENTORY-SCRIPT", SCRIPT_PATH, "产物清单生成脚本",
             "逐件读取字节与SHA-256，生成本Markdown及机器可读JSON。",
             NOT_PRODUCTION, True,
             f'PYTHONUTF8=1 py -3 -u "{SCRIPT_PATH}"'),
    ]
    return rows


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    qa = json.loads((QC / "render_qa.json").read_text(encoding="utf-8"))
    assert all(qa["checks"].values())
    assert qa["pages"] == 15
    assert manifest["report_md"]["sha256"] == info(manifest["report_md"]["path"])["sha256"]
    rows = entries()
    assert len({row["id"] for row in rows}) == len(rows)
    assert len({row["path"] for row in rows}) == len(rows)
    payload = {
        "schema": "kb_artifact_inventory_post_provenance_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "本轮最终加固新增件及被最终报告引用的复用件；清单自身不递归计算哈希。",
        "production_unchanged": manifest["production_unchanged"],
        "pdf_qa": {"pages": qa["pages"], "checks": qa["checks"],
                   "all_passed": all(qa["checks"].values())},
        "artifact_count": len(rows),
        "artifacts": rows,
        "human_inventory": str(MD_PATH),
        "git": manifest["git"],
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json_info = info(JSON_PATH)
    lines = [
        "# 2026-11-24 最终加固产物清单",
        "",
        f"- 生成时间（UTC）：{payload['generated_at']}",
        f"- 登记件数：**{len(rows)}**；另有本 Markdown 与机器可读 JSON 两个清单容器。",
        "- 生产默认未变：`top_window=3`、`fragment_policy=None`、`fact_selector=None`；洛克人1未启用；未提交或推送 Git。",
        "- 清单容器自身不递归计算哈希；JSON 的逐件记录覆盖全部被登记文件，本表额外登记 JSON 的哈希。",
        "- PDF：15页；自动QA 16/16项通过；首末页与§14回归表已抽帧目视核对。",
        "",
        "## 逐件登记",
        "",
        "| ID | 文件 | 用途 | 生产状态 | 可复跑 | 字节 | SHA-256 |",
        "|---|---|---|---|---|---:|---|",
    ]
    for row in rows:
        uri = Path(row["path"]).as_uri()
        rerun = "是" if row["rerunnable"] else "否"
        lines.append(
            f"| {row['id']} | [{Path(row['path']).name}]({uri}) | {row['purpose']} | "
            f"{row['production_active']} | {rerun} | {row['bytes']} | `{row['sha256']}` |"
        )
    lines.extend([
        f"| INVENTORY-JSON | [{JSON_PATH.name}]({JSON_PATH.as_uri()}) | 本清单的机器可读版，含全部登记件路径、用途、生产状态、字节与SHA-256。 | 否（交付索引） | 是 | {json_info['bytes']} | `{json_info['sha256']}` |",
        "",
        "## 复核入口",
        "",
        f"- [最终总清单]({MANIFEST.as_uri()})：生产状态、索引/快照、代码、评测、闸门与隔离证据。",
        f"- [最终PDF]({(ROOT / '知识库改进优化指导_2026-11-24_最终加固回填.pdf').as_uri()})：完整实施回填。",
        f"- [PDF QA]({(QC / 'render_qa.json').as_uri()})：16项自动检查。",
        f"- [全页联系表]({(QC / 'contact_sheet.png').as_uri()})：15页视觉总览。",
        "",
    ])
    MD_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"markdown": str(MD_PATH), "json": str(JSON_PATH),
                      "artifact_count": len(rows), "json_sha256": json_info["sha256"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
