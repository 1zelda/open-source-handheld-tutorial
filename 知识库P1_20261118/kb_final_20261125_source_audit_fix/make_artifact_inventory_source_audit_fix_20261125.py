# -*- coding: utf-8 -*-
"""生成来源继承修正交付逐件清单；清单容器不递归哈希。"""
import hashlib
import json
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261125_source_audit_fix"
QC = OUT / "report_qc_source_audit_fix_20261125"
MANIFEST = OUT / "final_manifest_source_audit_fix_20261125.json"
JSON_PATH = OUT / "artifact_inventory_source_audit_fix_20261125.json"
MD_PATH = OUT / "artifact_inventory_source_audit_fix_20261125.md"
SCRIPT = Path(__file__).resolve()
REPORT_MD = ROOT / "知识库改进优化指导_2026-11-25_来源审计修正回填.md"
REPORT_PDF = ROOT / "知识库改进优化指导_2026-11-25_来源审计修正回填.pdf"

ACTIVE = "是（生产默认）"
SHADOW = "否（显式影子臂）"
PROBE = "否（未批准探针）"
TEST = "否（测试/审计/交付件）"


def info(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def item(aid, path, category, purpose, production, rerunnable, command=None):
    return {"id": aid, "category": category, "purpose": purpose,
            "production_active": production, "rerunnable": rerunnable,
            "command": command, **info(path)}


def describe(path):
    name = path.name
    if name == "index.json":
        return "生产索引", "台账追加后重建的 BM25 基础索引；生产默认自动选择。", ACTIVE, True
    if name == "index_hybrid.json":
        return "未批准索引", "台账追加后重建的 hybrid 探针索引；未批准投产。", PROBE, True
    if name == "kb.py":
        return "生产代码", "别名解析、strict 重绑、索引选择与审计入口。", ACTIVE, True
    if name == "kb_provenance.py":
        return "生产代码", "二手别名继承、本机实测解除继承与撤回段分类。", ACTIVE, True
    if name == "kb_selftest_gates.py":
        return "测试代码", "来源继承、Q18、X21 与空出证回归闸门。", TEST, True
    if name == "report.html":
        return "PDF 中间件", "本地 HTML 渲染源，用于 PDF 打印与 DOM 横向溢出检查。", TEST, True
    if name == "render_qa.json":
        return "PDF QA", "页数、来源章节页码、页外文本块、空页、替换符与关键哈希检查。", TEST, True
    if name == "contact_sheet.png":
        return "PDF 视觉总览", "全部页面缩略图，用于检查空页、断表、异常留白与标题位置。", TEST, True
    if name.startswith("page_"):
        return "PDF 抽帧", "首末页或来源继承章节的 1.5 倍抽帧。", TEST, True
    if name.endswith(".npz"):
        return "稠密探针", "按索引 SHA 前12位命名的嵌入指纹；已移出生产目录。", PROBE, True
    if name.startswith("regression_"):
        return "四臂回归", "基础/hybrid 默认与 strict 逐题状态、定位、资格和隔离结果。", SHADOW, True
    if name.startswith("selector_"):
        return "选择器扫掠", "base/scoped/scoped_beyond/replace/strict_fragments 影子评测。", SHADOW, True
    if name.startswith("source_inheritance_arm_audit"):
        return "逐臂审计", "四臂状态、v2、正确/错误出证、漏答与冻结冲突汇总。", TEST, True
    if name.startswith(("blind_eval", "heldout_eval", "full_domain_eval")):
        return "生产评测", "台账追加后重跑的生产盲测、独立留出或全域评测。", TEST, True
    if name.startswith(("selftest", "kb_selftest", "cross_platform", "topic_selftest", "sources_selftest")):
        return "串行闸门", "本轮串行重跑的通过数、失败数与隔离检查日志。", TEST, True
    if name.startswith("sources_audit"):
        return "审计结果", "来源库审计：pass 8 / fail 0 / inconclusive 1；95 条来源、23 个知识包、88 个要素均有来源支撑。", TEST, True
    if name.startswith("kb_audit"):
        return "审计结果", "知识库覆盖、同步与资格审计：fail=0，既有 inconclusive 保留。", TEST, True
    if name.startswith("dense_isolation"):
        return "隔离验证", "生产目录无新稠密件、自动恢复基础索引、30 条查询逐格不变。", TEST, True
    if name.startswith(("build_", "dense_base", "dense_hybrid")):
        return "构建日志", "索引或稠密探针构建的完整运行输出。", TEST, True
    if name.endswith(".py"):
        return "复跑脚本", "生成本轮对应结果；只写新交付目录。", TEST, True
    return "交付文件", "来源继承修正本轮交付或中间产物。", TEST, False


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    qa = json.loads((QC / "render_qa.json").read_text(encoding="utf-8"))
    assert all(qa["checks"].values())
    assert manifest["report_md"]["sha256"] == info(REPORT_MD)["sha256"]
    assert manifest["prior_delivery_unchanged"]["ok"] is True
    rows = []
    explicit = [
        ("REPORT-MD", REPORT_MD, "交付正文", "来源审计根因、GBA 证据分级、并发取证纳册、四臂审计、稠密漂移和未完成边界。", TEST, False),
        ("REPORT-PDF", REPORT_PDF, "交付 PDF", f"{qa['pages']} 页；自动 QA {qa['check_count']}/{qa['check_count']}；首末页与来源章节抽帧。", TEST, False),
        ("LEDGER", ROOT / "测试问题与闸门说明书.md", "项目台账", "仅追加 §54；前文历史记录未改写。", TEST, False),
        ("CODE-KB", ROOT / "_工具脚本/taspipe/kb.py", "生产代码", "来源别名解析、strict 重绑与审计。", ACTIVE, True),
        ("CODE-PROVENANCE", ROOT / "_工具脚本/taspipe/kb_provenance.py", "生产代码", "片段资格继承与实测解除。", ACTIVE, True),
        ("CODE-KB-GATES", ROOT / "_工具脚本/taspipe/kb_selftest_gates.py", "测试代码", "来源继承、Q18、X21 与空出证回归闸门。", TEST, True),
        ("CODE-SOURCES-AUDIT", ROOT / "_工具脚本/taspipe/sources.py", "生产审计代码", "来源库 schema、状态一致性、取证报告、覆盖与支撑审计。", ACTIVE, True),
        ("CODE-SOURCES-GATES", ROOT / "_工具脚本/taspipe/sources_selftest_gates.py", "测试代码", "合法报告不升级、状态漂移和报告缺失三条确定性闸门。", TEST, True),
        ("SOURCE-REGISTRY", ROOT / "_工具脚本/taspipe/游戏包/来源库/sources.json", "来源主数据", "本轮来源状态与权威核对所依据的 95 条来源、23 个知识包、88 个要素登记。", ACTIVE, False),
        ("GBA-SHOWCASE", ROOT / "_工具脚本/taspipe/游戏包/gba_aria_of_sorrow_souls.showcase.json", "知识包主数据", "展示检测与菜单/gameplay 验证分开定级，平台总闸门未放行。", ACTIVE, False),
        ("INDEX-BASE", ROOT / "_工具脚本/taspipe/游戏包/知识库/index.json", "生产索引", "台账追加后最终 802 块 BM25 索引。", ACTIVE, True),
        ("INDEX-HYBRID", ROOT / "_工具脚本/taspipe/游戏包/知识库/index_hybrid.json", "探针索引", "未批准 816 块 hybrid 索引；稠密指纹未在生产目录激活。", PROBE, True),
        ("CORPUS-MAP", ROOT / "_工具脚本/taspipe/游戏包/知识库/corpus_map.json", "主数据", "汇总件 citations 别名与六份 GBA 取证资格、索引边界。", ACTIVE, False),
        ("SOURCE-CLAIM", ROOT / "_工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md", "源文修正", "Q18 分别记载 S1 音效与 S8 得分框签名，不再声称两源一致。", ACTIVE, False),
        ("MANIFEST", MANIFEST, "总指纹", "最终索引、代码、四臂、闸门、审计、隔离和旧交付保护。", TEST, True),
        ("MANIFEST-SCRIPT", OUT / "make_final_manifest_source_audit_fix_20261125.py", "总指纹脚本", "确定性断言本轮结果并生成 manifest。", TEST, True),
        ("INVENTORY-SCRIPT", SCRIPT, "清单脚本", "逐件读取路径、用途、生产状态、字节与 SHA-256。", TEST, True),
    ]
    for aid, path, category, purpose, production, rerunnable in explicit:
        rows.append(item(aid, path, category, purpose, production, rerunnable))
    explicit_paths = {Path(row[1]).resolve() for row in explicit}
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or path.resolve() in explicit_paths or path in (JSON_PATH, MD_PATH, MANIFEST, SCRIPT):
            continue
        category, purpose, production, rerunnable = describe(path)
        rows.append(item("FILE-" + path.relative_to(OUT).as_posix().replace("/", "-"), path,
                         category, purpose, production, rerunnable))
    for name, expected in manifest["prior_delivery_unchanged"]["artifacts"].items():
        rows.append(item("PRIOR-" + Path(name).stem, ROOT / name, "旧交付保护",
                         "旧最终交付保持原样；本轮 manifest 断言 SHA-256 未变。", TEST, False))
    assert len({row["id"] for row in rows}) == len(rows)
    assert len({row["path"] for row in rows}) == len(rows)
    payload = {"schema": "kb_artifact_inventory_source_audit_fix_v1",
               "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "scope": "来源审计修正新增件、生产主数据/代码、未批准探针与旧交付保护；清单自身不递归哈希。",
               "production_unchanged": manifest["production_unchanged"],
               "pdf_qa": {"pages": qa["pages"], "section_page": qa["source_section_page"],
                          "checks": qa["checks"], "all_passed": all(qa["checks"].values())},
               "artifact_count": len(rows), "artifacts": rows,
               "human_inventory": str(MD_PATH), "git": manifest["git"]}
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json_info = info(JSON_PATH)
    lines = ["# 2026-11-25 来源审计修正产物清单", "",
             f"- 生成时间（UTC）：{payload['generated_at']}",
             f"- 登记件数：**{len(rows)}**；另有 Markdown 与 JSON 两个清单容器。",
             "- 生产默认仍为 `top_window=3`、`fragment_policy=None`、`fact_selector=None`；strict 是影子臂，稠密层未批准且已隔离。",
             "- 台账追加后已重建两套索引并串行复跑；清单只登记最终指纹。",
             "- 清单容器不递归哈希；本表额外登记 JSON 的哈希。",
             f"- PDF：{qa['pages']} 页；自动 QA {qa['check_count']}/{qa['check_count']}；首末页与来源章节已抽帧。",
             "", "## 逐件登记", "",
             "| ID | 文件 | 用途 | 生产状态 | 可复跑 | 字节 | SHA-256 |",
             "|---|---|---|---|---|---:|---|"]
    for row in rows:
        lines.append(f"| {row['id']} | [{Path(row['path']).name}]({Path(row['path']).as_uri()}) | "
                     f"{row['purpose']} | {row['production_active']} | {'是' if row['rerunnable'] else '否'} | "
                     f"{row['bytes']} | `{row['sha256']}` |")
    lines += [f"| INVENTORY-JSON | [{JSON_PATH.name}]({JSON_PATH.as_uri()}) | 机器可读清单。 | 否（交付索引） | 是 | {json_info['bytes']} | `{json_info['sha256']}` |",
              "", "## 复核入口", "",
              f"- [总指纹]({MANIFEST.as_uri()})", f"- [报告 PDF]({REPORT_PDF.as_uri()})",
              f"- [PDF QA]({(QC / 'render_qa.json').as_uri()})",
              f"- [全页联系表]({(QC / 'contact_sheet.png').as_uri()})", ""]
    MD_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"markdown": str(MD_PATH), "json": str(JSON_PATH),
                      "artifact_count": len(rows), "pages": qa["pages"],
                      "qa_checks": qa["check_count"], "json_sha256": json_info["sha256"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
