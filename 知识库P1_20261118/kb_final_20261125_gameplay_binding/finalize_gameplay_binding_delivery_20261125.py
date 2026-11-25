from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import unquote
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
GAME = ROOT / "_工具脚本/taspipe/游戏包"
TOOLS = ROOT / "_工具脚本/taspipe"
EVIDENCE = GAME / "证据/晓月圆舞曲/gameplay_verify_binding_20261125"
PREFLIGHT = OUT / "preflight_fingerprints_gameplay_binding_20261125.json"
PROTECTED = OUT / "protected_delivery_hashes_gameplay_binding_20261125.json"
BINDING_VERIFICATION = OUT / "gameplay_binding_verification_20261125.json"
QC = OUT / "report_qc_gameplay_binding_20261125/render_qa.json"
REPORT_MD = ROOT / "知识库改进优化指导_2026-11-25_晓月19项玩法证据回绑.md"
REPORT_PDF = ROOT / "知识库改进优化指导_2026-11-25_晓月19项玩法证据回绑.pdf"
MANIFEST = OUT / "final_manifest_gameplay_binding_20261125.json"
VERIFICATION = OUT / "final_delivery_verification_gameplay_binding_20261125.json"
INVENTORY_JSON = OUT / "artifact_inventory_gameplay_binding_20261125.json"
INVENTORY_MD = OUT / "artifact_inventory_gameplay_binding_20261125.md"
INVENTORY_VERIFICATION = OUT / "artifact_inventory_verification_gameplay_binding_20261125.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifact(path, role):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path), "role": role}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def gate_counts():
    specs = {
        "project_selftest": ("selftest_gameplay_binding_20261125.log", r"SELFTEST OK (\d+)/(\d+)"),
        "kb_selftest": ("kb_selftest_gameplay_binding_20261125.log", r"KB_SELFTEST OK (\d+)/(\d+)"),
        "cross_platform_selftest": ("cross_platform_selftest_gameplay_binding_20261125.log", r"CROSS_PLATFORM_SELFTEST OK (\d+)/(\d+)"),
        "sources_selftest": ("sources_selftest_gameplay_binding_20261125.log", r"SOURCES_SELFTEST OK (\d+)/(\d+)"),
        "topic_selftest": ("topic_selftest_gameplay_binding_20261125.log", r"自检合计 (\d+) 格：PASS (\d+) / FAIL (\d+)"),
    }
    result = {}
    for key, (name, pattern) in specs.items():
        text = (OUT / name).read_text(encoding="utf-8")
        match = re.search(pattern, text)
        assert match, f"缺闸门汇总 {name}"
        if key == "topic_selftest":
            total, passed, failed = map(int, match.groups())
            assert failed == 0
        else:
            passed, total = map(int, match.groups())
        assert passed == total
        result[key] = {"passed": passed, "total": total, "ok": True,
                       "log": artifact(OUT / name, "闸门日志")}
    return result


def common_checks():
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    checks = {}
    for section in ("code", "data"):
        for key, item in pre[section].items():
            path = Path(item["path"])
            checks[f"{section}:{key}"] = path.is_file() and sha(path) == item["sha256"]
    protected = json.loads(PROTECTED.read_text(encoding="utf-8"))
    checks["old_deliveries_unchanged"] = protected["status"] == "pass" and all(
        item["unchanged"] and (ROOT / item["path"]).is_file()
        and sha(ROOT / item["path"]) == item["expected"] for item in protected["files"])
    checks["old_delivery_count_1301"] = protected["checked"] == protected["unchanged"] == 1301
    binding_verification = json.loads(BINDING_VERIFICATION.read_text(encoding="utf-8"))
    checks["binding_verification_579"] = binding_verification["status"] == "pass" and binding_verification["check_count"] == 579 and all(binding_verification["checks"].values())
    source_audit = json.loads((OUT / "source_audit_gameplay_binding_20261125.json").read_text(encoding="utf-8"))
    kb_audit = json.loads((OUT / "kb_audit_gameplay_binding_20261125.json").read_text(encoding="utf-8"))
    checks["source_audit_fail_zero"] = source_audit["counts"]["fail"] == 0
    checks["source_coverage_208"] = source_audit["counts"]["elements_checked"] == source_audit["counts"]["elements_supported"] == 208
    weak = next(item["detail"] for item in source_audit["checks"] if item["check_id"] == "verified_support")
    checks["weak_141"] = len(weak) == 141
    checks["menu_weak_95"] = sum("menu_catalog" in item for item in weak) == 95
    checks["detector_weak_6"] = sum("detectors" in item for item in weak) == 6
    checks["bound_19_not_weak"] = not any(f"aria_{group}_{soul_id:03d}" in item for item in weak
                                           for group, soul_id in [("red", 4), ("red", 5), ("red", 12), ("red", 24), ("red", 31), ("red", 35), ("red", 37), ("red", 47), ("blue", 2), ("blue", 4), ("blue", 6), ("blue", 13), ("blue", 22), ("yellow", 10), ("yellow", 15), ("yellow", 26), ("yellow", 27), ("yellow", 28), ("yellow", 29)])
    checks["kb_audit_fail_zero"] = kb_audit["counts"]["fail"] == 0
    checks["kb_chunks_826"] = kb_audit["counts"]["chunks"] == 826
    coverage = json.loads((OUT / "coverage_gameplay_binding_20261125.json").read_text(encoding="utf-8"))
    states = {}
    for row in coverage["rows"]:
        states[row["state"]] = states.get(row["state"], 0) + 1
    checks["coverage_counts"] = states == {"verified": 11, "present_unverified": 6, "registered_empty": 9}
    pack_path = GAME / "gba_aria_of_sorrow_souls.menu_catalog.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    checks["menu_schema_1_2"] = pack["schema_version"] == "aria_soul_menu_catalog/1.2"
    checks["menu_gameplay_19"] = sum(item["gameplay_verified"] for item in pack["elements"]) == 19
    checks["menu_gameplay_false_95"] = sum(item["gameplay_verified"] is False for item in pack["elements"]) == 95
    checks["menu_detector_all_false"] = all(item["detector_verified"] is False for item in pack["elements"])
    checks["menu_identity_candidate"] = pack["catalog"]["sources"][0]["source_id"] == "local_aria_menu_catalog_20261125" and pack["catalog"]["sources"][0]["status"] == "candidate"
    checks["menu_human_false"] = pack["visual_review"]["human_visual_review"] is False
    binding_path = EVIDENCE / "gameplay_evidence_binding_20261125.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    checks["binding_report_hash"] = pack["gameplay_verification"]["report_sha256"] == sha(binding_path)
    checks["binding_19_cases"] = binding["status"] == "pass" and len(binding["cases"]) == 19
    evidence_inventory = json.loads((EVIDENCE / "artifact_inventory.json").read_text(encoding="utf-8"))
    checks["binding_inventory_519"] = evidence_inventory["file_count"] == len(evidence_inventory["files"]) == 519
    for item in evidence_inventory["files"]:
        path = ROOT / item["path"]
        checks[f"binding_inventory:{item['path']}"] = path.is_file() and path.stat().st_size == item["bytes"] and sha(path) == item["sha256"]
    registry = json.loads((GAME / "来源库/sources.json").read_text(encoding="utf-8"))
    source = next(item for item in registry["sources"] if item["source_id"] == "local_aria_gameplay_verify_20261125")
    old_source = next(item for item in registry["sources"] if item["source_id"] == "local_gameplay_20261124")
    checks["new_source_verified_read"] = source["status"] == "verified_read"
    checks["old_source_candidate"] = old_source["status"] == "candidate" and old_source["last_verified"] is None
    corpus = json.loads((GAME / "知识库/corpus_map.json").read_text(encoding="utf-8"))
    new_entries = [item for item in corpus["entries"] if item["source_id"] == "local_aria_gameplay_verify_20261125"]
    checks["corpus_20_authoritative_unindexed"] = len(new_entries) == 20 and all(item["authority"] == "authoritative" and item["index"] is False for item in new_entries)
    qc = json.loads(QC.read_text(encoding="utf-8"))
    checks["pdf_qc_33_all_true"] = qc["check_count"] == 33 and all(qc["checks"].values())
    checks["pdf_hash_match"] = sha(REPORT_PDF) == qc["pdf_sha256"]
    checks["pdf_pages_positive"] = qc["pages"] > 0 and qc["checks"]["no_blank_pages"]
    checks["report_markdown_hash"] = sha(REPORT_MD) == qc["markdown_sha256"]
    sys.path.insert(0, str(ROOT / "_工具脚本"))
    from taspipe.showcase import PLATFORM_PROFILES
    checks["gba_platform_gate_false"] = PLATFORM_PROFILES["GBA"]["verified"] is False
    return checks


def delivery_files():
    excluded = {MANIFEST.name, VERIFICATION.name, INVENTORY_JSON.name, INVENTORY_MD.name,
                INVENTORY_VERIFICATION.name}
    return [path for path in sorted(OUT.rglob("*")) if path.is_file() and path.name not in excluded]


def build_manifest():
    checks = common_checks()
    assert all(checks.values()), [key for key, value in checks.items() if not value]
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    source_audit = json.loads((OUT / "source_audit_gameplay_binding_20261125.json").read_text(encoding="utf-8"))
    kb_audit = json.loads((OUT / "kb_audit_gameplay_binding_20261125.json").read_text(encoding="utf-8"))
    qc = json.loads(QC.read_text(encoding="utf-8"))
    files = [artifact(path, "交付工件") for path in delivery_files()]
    key_production = [
        TOOLS / "sources.py",
        TOOLS / "sources_selftest_gates.py",
        TOOLS / "kb.py",
        GAME / "来源库/sources.json",
        GAME / "复古游戏文献来源库.md",
        GAME / "gba_aria_of_sorrow_souls.menu_catalog.json",
        GAME / "知识库/corpus_map.json",
        GAME / "知识库/index.json",
        EVIDENCE / "gameplay_evidence_binding_20261125.json",
        EVIDENCE / "artifact_inventory.json",
        REPORT_MD,
        REPORT_PDF,
    ]
    files.extend(artifact(path, "生产修正或报告") for path in key_production)
    manifest = {
        "schema": "kb_final_manifest_gameplay_binding_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "晓月圆舞曲19项已有正式玩法正反例的逐案复核、460份证据固化、菜单目录限定回绑、串行回归与旧交付保护；资格不外推。",
        "all_checks_ok": True,
        "production_defaults": pre["production_defaults"],
        "preflight": pre,
        "gates": gate_counts(),
        "audits": {
            "sources": {"status": source_audit["status"], "counts": source_audit["counts"],
                        "artifact": artifact(OUT / "source_audit_gameplay_binding_20261125.json", "来源审计")},
            "kb": {"status": kb_audit["status"], "counts": kb_audit["counts"],
                   "artifact": artifact(OUT / "kb_audit_gameplay_binding_20261125.json", "知识库审计")},
        },
        "gameplay_binding": {"elements": 114, "verified": 19, "false": 95,
                             "detector_false": 114, "copied_files": 519,
                             "evidence_files": 460, "copied_bytes": 14958586,
                             "source_status": "verified_read", "menu_source_status": "candidate",
                             "human_visual_review": False, "platform_gate_verified": False},
        "pdf_qc": {"pages": qc["pages"], "checks": qc["check_count"],
                   "artifact": artifact(QC, "PDF质检"), "pdf": artifact(REPORT_PDF, "报告PDF")},
        "protected_delivery": artifact(PROTECTED, "旧交付保护"),
        "binding_verification": artifact(BINDING_VERIFICATION, "玩法绑定复核"),
        "checks": checks,
        "files": files,
    }
    write_json(MANIFEST, manifest)
    return manifest


def verify_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    checks = common_checks()
    for item in manifest["files"]:
        path = Path(item["path"])
        checks[f"manifest:{path.name}"] = path.is_file() and path.stat().st_size == item["bytes"] and sha(path) == item["sha256"]
    assert all(checks.values()), [key for key, value in checks.items() if not value]
    result = {
        "schema": "gameplay_binding_final_delivery_verification_v1",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass", "all_checks_ok": True,
        "check_count": len(checks), "checks": checks,
        "manifest": artifact(MANIFEST, "最终manifest"),
        "source_audit": manifest["audits"]["sources"]["counts"],
        "kb_audit": manifest["audits"]["kb"]["counts"],
        "gates": {key: f"{value['passed']}/{value['total']}" for key, value in manifest["gates"].items()},
        "pdf": manifest["pdf_qc"],
        "remaining": {"menu_gameplay_false": 95, "menu_detector_false": 114,
                      "human_visual_review": False, "present_unverified_versions": 6,
                      "registered_empty_versions": 9, "gba_platform_gate": False,
                      "strict_production_default": False, "dense_production_default": False,
                      "dynamic_esports_results": 0},
    }
    write_json(VERIFICATION, result)
    return result


def build_inventory():
    paths = {path.resolve() for path in delivery_files()}
    paths.update(path.resolve() for path in EVIDENCE.rglob("*") if path.is_file())
    paths.update((ROOT / rel).resolve() for rel in [
        "_工具脚本/taspipe/sources.py",
        "_工具脚本/taspipe/sources_selftest_gates.py",
        "_工具脚本/taspipe/kb.py",
        "_工具脚本/taspipe/游戏包/来源库/sources.json",
        "_工具脚本/taspipe/游戏包/复古游戏文献来源库.md",
        "_工具脚本/taspipe/游戏包/gba_aria_of_sorrow_souls.menu_catalog.json",
        "_工具脚本/taspipe/游戏包/知识库/corpus_map.json",
        "_工具脚本/taspipe/游戏包/知识库/index.json",
        "知识库改进优化指导_2026-11-25_晓月19项玩法证据回绑.md",
        "知识库改进优化指导_2026-11-25_晓月19项玩法证据回绑.pdf",
    ])
    files = []
    for path in sorted(paths):
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            relative = str(path)
        if EVIDENCE in path.parents:
            role = "玩法固化证据"
        elif path in (REPORT_MD, REPORT_PDF):
            role = "独立报告"
        elif OUT in path.parents:
            role = "交付工件"
        else:
            role = "生产修正"
        row = artifact(path, role)
        row["relative_path"] = relative
        files.append(row)
    data = {
        "schema": "gameplay_binding_artifact_inventory_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files), "total_bytes": sum(item["bytes"] for item in files),
        "scope": "新交付目录、19项玩法绑定的521份固化文件、串行审计与闸门、生产修正和报告；不含manifest、最终验证和清单自身。",
        "files": files,
    }
    write_json(INVENTORY_JSON, data)
    lines = [
        "# 晓月19项玩法证据回绑交付 · 逐件工件清单",
        "",
        f"- 文件数：{len(files)}",
        f"- 总字节数：{sum(item['bytes'] for item in files)}",
        "- 范围：新交付目录、19项玩法绑定的521份固化文件、串行审计与闸门、生产修正和报告；不含manifest、最终验证和清单自身。",
        "",
        "| 相对路径 | 角色 | 字节 | SHA-256 |",
        "|---|---|---:|---:|",
    ]
    for item in files:
        lines.append(f"| `{item['relative_path']}` | {item['role']} | {item['bytes']} | `{item['sha256']}` |")
    INVENTORY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data


def check_delivery():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    verification = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    inventory = json.loads(INVENTORY_JSON.read_text(encoding="utf-8"))
    checks = common_checks()
    for item in manifest["files"]:
        path = Path(item["path"])
        checks[f"manifest:{path.name}"] = path.is_file() and path.stat().st_size == item["bytes"] and sha(path) == item["sha256"]
    checks["manifest_verification_link"] = verification["manifest"]["sha256"] == sha(MANIFEST)
    for item in inventory["files"]:
        path = Path(item["path"])
        checks[f"inventory:{item['relative_path']}"] = path.is_file() and path.stat().st_size == item["bytes"] and sha(path) == item["sha256"]
    checks["inventory_file_count"] = inventory["file_count"] == len(inventory["files"])
    checks["inventory_total_bytes"] = inventory["total_bytes"] == sum(item["bytes"] for item in inventory["files"])
    links = re.findall(r"\]\(([^)\s#]+)\)", REPORT_MD.read_text(encoding="utf-8"))
    for raw in links:
        path = Path(unquote(raw))
        if not path.is_absolute():
            path = ROOT / path
        checks[f"report_link:{raw}"] = path.exists()
    assert links
    assert all(checks.values()), [key for key, value in checks.items() if not value]
    result = {
        "schema": "gameplay_binding_artifact_inventory_verification_v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass", "all_checks_ok": True,
        "check_count": len(checks), "inventory_files": inventory["file_count"],
        "report_links": len(links), "checks": checks,
    }
    write_json(INVENTORY_VERIFICATION, result)
    return result


def main():
    stage = sys.argv[1]
    if stage == "manifest":
        result = build_manifest()
    elif stage == "verify":
        result = verify_manifest()
    elif stage == "inventory":
        result = build_inventory()
    elif stage == "check":
        result = check_delivery()
    else:
        raise SystemExit("用法: finalize_gameplay_binding_delivery_20261125.py {manifest|verify|inventory|check}")
    print(json.dumps({"stage": stage, "status": result.get("status", "pass"),
                      "files": result.get("file_count", len(result.get("files", []))),
                      "checks": result.get("check_count")}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
