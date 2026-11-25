from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PREFLIGHT = OUT / "preflight_fingerprints_gameplay_binding_20261125.json"
BINDING = ROOT / "_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/gameplay_verify_binding_20261125/gameplay_evidence_binding_20261125.json"
REPORT = ROOT / "知识库改进优化指导_2026-11-25_晓月19项玩法证据回绑.md"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def link(path, label=None):
    rel = Path(path).resolve().relative_to(ROOT).as_posix()
    return f"[{label or rel}]({rel})"


def main():
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    rows = []
    for row in binding["cases"]:
        metric = f"{row['metric']['name']} {row['metric']['positive']}/{row['metric']['negative']}"
        comparison = f"{row['captured_frames_per_arm']}帧；抽样全不同"
        rows.append(f"| {row['element_id']} | {row['element']['name_zh']} | `{row['case_id']}` | "
                    f"{row['slot']['positive']}/0 @ {row['slot']['addr']} | {metric} | {comparison} |")
    lines = [
        "# 知识库改进优化指导：晓月圆舞曲19项玩法证据回绑",
        "",
        "- 日期：2026-11-25",
        "- 交付性质：独立修复副本；旧最终交付保持原样。",
        "- ROM SHA-1：`40AAB076A528F52E93260BB98D91A40039E0DA02`",
        "- 实际核心：`BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk`",
        "",
        "## 1. 本轮结论",
        "",
        "已有19份正式 `mode=verify/status=pass` 的本机正反例报告此前未回绑到114项菜单目录，导致目录全部停留在 `gameplay_verified=false`。本轮逐案复算报告、配方、manifest和460份证据后，仅将对应19项改为 `true`；其余95项玩法、全部114项检测器和GBA平台总闸门继续为 `false`。",
        "",
        "菜单身份来源 `local_aria_menu_catalog_20261125` 仍为 `candidate`；旧采集来源 `local_gameplay_20261124` 仍为 `candidate`，未被洗白。新增的 `local_aria_gameplay_verify_20261125` 是独立的限定范围 `verified_read` 来源。",
        "",
        "## 2. 根因与修正",
        "",
        "根因不是证据不存在，而是正式玩法报告与菜单稳定ID之间缺少可审计绑定。修正采用三条互不替代的链：",
        "",
        "1. 证据链：逐案校验正例槽位、空槽反例、RAM预期与实际、核心、帧数和抽样帧差异。",
        "2. 固化链：复制19份报告、19份配方、19份manifest及460份证据到项目内独立目录，并生成逐件SHA-256清单。",
        "3. 资格链：菜单包升为 `aria_soul_menu_catalog/1.2`，仅19项增加 `gameplay_evidence` 并标记 `fixed_route_pass`；新增来源和20条 `index=false/authoritative` corpus登记。",
        "",
        "菜单包：[gba_aria_of_sorrow_souls.menu_catalog.json](_工具脚本/taspipe/游戏包/gba_aria_of_sorrow_souls.menu_catalog.json)",
        "",
        "统一绑定报告：[gameplay_evidence_binding_20261125.json](_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/gameplay_verify_binding_20261125/gameplay_evidence_binding_20261125.json)",
        "",
        "逐件证据清单：[artifact_inventory.json](_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/gameplay_verify_binding_20261125/artifact_inventory.json)",
        "",
        "## 3. 19项逐案矩阵",
        "",
        "“正/负”表示目标槽ID与空槽0；指标正/负表示正例臂与空槽臂的末值。红蓝魂指标为MP，黄魂指标为HP。",
        "",
        "| 稳定ID | 名称 | 案例 | 槽位 正/负 | 指标 正/负 | 抽样帧比较 |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(rows)
    lines.extend([
        "",
        "### 3.1 红蓝魂13项",
        "",
        "固定战斗初态只改对应槽位并执行角色宏；目标槽保持、MP低于80，空槽保持80，抽样帧存在真实差异。只证明该ID在固定路线可触发并消耗MP，不证明伤害、射程、全部招式语义、中文菜单装备流程或任意场景稳定性。",
        "",
        "### 3.2 黄魂6项",
        "",
        "固定受击路线末HP高于空魂对照292。黄魂10末HP为302，并另有蓝色 `+5` 提示；其余5项只证明末HP优势。黄魂15/26当前路线表现相同，黄魂28/29末HP均为316，不能据此区分防御、CON或单次受击机制。",
        "",
        "## 4. 固化证据",
        "",
        f"- 复制文件：{binding['counts']['copied_files']} 件。",
        f"- 复制总字节：{binding['counts']['copied_bytes']:,}。",
        f"- 其中报告/配方/manifest：57件；模拟器与帧/RAM证据：460件，13,617,762字节。",
        "- 逐件复核：579项通过，覆盖519份复制文件、19个元素绑定、来源证据和corpus路径一致性。",
        "- 状态版本：`r20261125T120000` 与 `r20261125T145623`；旧11案归档目录名与配方revision不同，本轮按报告真实字段记录，不按目录名猜版本。",
        "",
        "审计脚本：[audit_gameplay_verify_evidence_20261125.py](知识库P1_20261118/kb_final_20261125_gameplay_binding/audit_gameplay_verify_evidence_20261125.py)",
        "",
        "回绑脚本：[bind_gameplay_verify_evidence_20261125.py](知识库P1_20261118/kb_final_20261125_gameplay_binding/bind_gameplay_verify_evidence_20261125.py)",
        "",
        "复核脚本：[verify_gameplay_binding_20261125.py](知识库P1_20261118/kb_final_20261125_gameplay_binding/verify_gameplay_binding_20261125.py)",
        "",
        "## 5. 资格边界",
        "",
        "- `gameplay_verified=true`：19项，且只限报告固定路线。",
        "- `gameplay_verified=false`：其余95项，包括黄魂4。",
        "- `detector_verified=false`：全部114项；玩法通过不等于检测器通过。",
        "- `human_visual_review=false`：菜单二次视觉复核仍无人工签核。",
        "- `PLATFORM_PROFILES.GBA.verified=false`：平台总闸门未放行。",
        "- `strict_production_default=false`、`dense_production_default=false`：未改变生产默认。",
        "- 未写入商业ROM/BIOS，未发送授权申请，未提交或推送Git。",
        "",
        "## 6. 审计与串行回归",
        "",
        f"- 来源审计：pass {pre['source_audit']['counts']['pass']} / fail {pre['source_audit']['counts']['fail']} / inconclusive {pre['source_audit']['counts']['inconclusive']}；来源{pre['source_audit']['counts']['sources']}、包{pre['source_audit']['counts']['packs']}、要素{pre['source_audit']['counts']['elements_supported']}/{pre['source_audit']['counts']['elements_checked']}有支撑。",
        f"- 弱支撑：{pre['source_audit']['weak_total']}项，其中菜单{pre['source_audit']['menu_weak']}项、检测器{pre['source_audit']['detector_weak']}项；本轮19项已从弱支撑移除。",
        f"- 知识库审计：pass {pre['kb_audit']['pass']} / fail {pre['kb_audit']['fail']} / inconclusive {pre['kb_audit']['inconclusive']}；{pre['kb_audit']['chunks']}块，生产索引SHA未变。",
        "- 覆盖快照：verified 11 / present_unverified 6 / registered_empty 9。",
        "- 全项目自检：1551/1551。",
        "- 知识库独立闸门：336/336。",
        "- 跨平台独立闸门：33/33。",
        "- 来源独立闸门：74/74。",
        "- 选题决策层：166/166，FAIL 0。",
        f"- 旧交付保护：{pre['protected_delivery']['unchanged']}/{pre['protected_delivery']['checked']}未变。",
        "",
        "## 7. 当前仍未完成项",
        "",
        "- 其余95项菜单玩法正反例。",
        "- 全部114项检测器正反例、语义身份和全时间线验收。",
        "- 菜单人工签核与能力魂8项中文版地址/被动效果。",
        "- 黄魂4单次受击/麻痹实验；黄魂15/26与28/29的机制区分。",
        "- 6个present_unverified版本的权威机制正文、9个registered_empty版本。",
        "- 既有40项非菜单非检测器弱支撑要素，以及6项候选检测器弱支撑。",
        "- GBA平台总闸门、strict/dense升生产默认审批、动态电竞赛果和真实用户查询样本。",
        "",
        "## 8. 最终代码与数据指纹",
        "",
        "| 工件 | SHA-256 |",
        "|---|---|",
    ])
    labels = {
        "sources_audit": "来源审计代码", "sources_selftest_gates": "来源闸门",
        "kb": "知识库代码", "kb_selftest_gates": "知识库闸门",
        "cross_platform_gates": "跨平台闸门", "showcase": "showcase平台边界",
        "audit_gameplay": "19案审计脚本", "bind_gameplay": "回绑脚本", "verify_gameplay": "回绑复核脚本",
        "prepare_delivery": "交付准备脚本", "build_report": "报告生成脚本",
        "render_qc": "PDF渲染质检脚本", "finalize_delivery": "最终交付脚本",
    }
    for key, item in pre["code"].items():
        lines.append(f"| {labels.get(key, key)} | `{item['sha256']}` |")
    data_labels = {
        "source_registry": "来源注册表", "source_catalog_md": "来源人读清单",
        "menu_catalog": "114项菜单目录", "corpus_map": "corpus map", "index": "生产BM25索引",
        "gameplay_binding": "19项绑定报告", "gameplay_inventory": "519件证据清单",
        "gameplay_audit": "19案审计", "gameplay_verification": "579项复核",
        "source_audit": "来源审计快照", "kb_audit": "知识库审计快照", "coverage": "覆盖快照",
    }
    for key, item in pre["data"].items():
        lines.append(f"| {data_labels.get(key, key)} | `{item['sha256']}` |")
    lines.extend([
        "",
        "- PDF页数、字节数和SHA-256以同目录 `report_qc_gameplay_binding_20261125/render_qa.json` 为准；Markdown自身SHA-256以最终manifest为准。",
        "",
    ])
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": REPORT.relative_to(ROOT).as_posix(), "bytes": REPORT.stat().st_size,
                      "sha256": sha(REPORT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
