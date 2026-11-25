from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import sys
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "知识库P1_20261118/kb_final_20261125_menu_evidence_binding"
PREFLIGHT = OUT / "preflight_fingerprints_menu_evidence_binding_20261125.json"
MANIFEST = OUT / "final_manifest_menu_evidence_binding_20261125.json"
VERIFICATION = OUT / "final_delivery_verification_menu_evidence_binding_20261125.json"
INVENTORY_JSON = OUT / "artifact_inventory_menu_evidence_binding_20261125.json"
INVENTORY_MD = OUT / "artifact_inventory_menu_evidence_binding_20261125.md"
INVENTORY_VERIFICATION = OUT / "artifact_inventory_verification_menu_evidence_binding_20261125.json"
REPORT_MD = ROOT / "知识库改进优化指导_2026-11-25_晓月菜单证据固化与来源覆盖修正.md"
REPORT_PDF = ROOT / "知识库改进优化指导_2026-11-25_晓月菜单证据固化与来源覆盖修正.pdf"
QC_JSON = OUT / "report_qc_menu_evidence_binding_20261125/render_qa.json"
EVIDENCE_DIR = ROOT / "_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/menu_catalog_nav_full_20261125"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifact(path, role):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path), "role": role}


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def gate_counts():
    specs = {
        "project_selftest": ("selftest_menu_evidence_binding_20261125.log", r"SELFTEST OK (\d+)/(\d+)"),
        "kb_selftest": ("kb_selftest_menu_evidence_binding_20261125.log", r"KB_SELFTEST OK (\d+)/(\d+)"),
        "cross_platform_selftest": ("cross_platform_menu_evidence_binding_20261125.log", r"CROSS_PLATFORM_SELFTEST OK (\d+)/(\d+)"),
        "sources_selftest": ("sources_selftest_menu_evidence_binding_20261125.log", r"SOURCES_SELFTEST OK (\d+)/(\d+)"),
        "topic_selftest": ("topic_selftest_menu_evidence_binding_20261125.log", r"自检合计 (\d+) 格：PASS (\d+) / FAIL (\d+)"),
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
    source_audit = json.loads((OUT / "source_audit.json").read_text(encoding="utf-8"))
    kb_audit = json.loads((OUT / "kb_audit_menu_evidence_binding_20261125.json").read_text(encoding="utf-8"))
    checks["source_audit_fail_zero"] = source_audit["counts"]["fail"] == 0
    checks["source_coverage_202_of_202"] = source_audit["counts"]["elements_checked"] == source_audit["counts"]["elements_supported"] == 202
    checks["kb_audit_fail_zero"] = kb_audit["counts"]["fail"] == 0
    checks["index_chunks_826"] = kb_audit["counts"]["chunks"] == 826
    weak = next(c["detail"] for c in source_audit["checks"] if c["check_id"] == "verified_support")
    checks["weak_elements_154"] = len(weak) == 154
    checks["menu_weak_elements_114"] = sum("menu_catalog" in item for item in weak) == 114
    checks["legacy_weak_elements_40"] = sum("menu_catalog" not in item for item in weak) == 40
    coverage = json.loads((OUT / "coverage_menu_evidence_binding_20261125.log").read_text(encoding="utf-8"))
    states = {}
    for row in coverage["rows"]:
        states[row["state"]] = states.get(row["state"], 0) + 1
    checks["coverage_counts"] = states == {"verified": 11, "present_unverified": 6, "registered_empty": 9}
    pack_path = ROOT / "_工具脚本/taspipe/游戏包/gba_aria_of_sorrow_souls.menu_catalog.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    ids = [item["element_id"] for item in pack["elements"]]
    checks["menu_114_unique_stable_ids"] = len(ids) == len(set(ids)) == 114
    checks["menu_source_candidate"] = pack["catalog"]["sources"][0]["status"] == "candidate"
    checks["menu_all_gameplay_false"] = all(item["gameplay_verified"] is False for item in pack["elements"])
    checks["menu_all_detector_false"] = all(item["detector_verified"] is False for item in pack["elements"])
    media = []
    for item in pack["elements"]:
        for kind, ref in item["evidence"].items():
            path = ROOT / ref["path"]
            media.append(path.is_file() and sha(path) == ref["sha256"])
    checks["menu_342_media_hashes"] = len(media) == 342 and all(media)
    for key in ("source_report", "source_config", "name_observation", "effect_observation", "legacy_patch_audit"):
        ref = pack[key]
        path = ROOT / ref["path"]
        checks[f"menu_ref:{key}"] = path.is_file() and sha(path) == ref["sha256"]
    registry = json.loads((ROOT / "_工具脚本/taspipe/游戏包/来源库/sources.json").read_text(encoding="utf-8"))
    source = next(item for item in registry["sources"] if item["source_id"] == "local_aria_menu_catalog_20261125")
    checks["registry_menu_source_candidate"] = source["status"] == "candidate"
    checks["registry_pack_status_match"] = source["status"] == pack["catalog"]["sources"][0]["status"]
    protected = json.loads((OUT / "protected_delivery_hashes_20261125.json").read_text(encoding="utf-8"))
    checks["old_deliveries_unchanged"] = protected["status"] == "pass" and all(
        item["unchanged"] and sha(ROOT / item["path"]) == item["expected"] for item in protected["files"])
    qc = json.loads(QC_JSON.read_text(encoding="utf-8"))
    checks["pdf_qc_all_true"] = qc["check_count"] == 32 and all(qc["checks"].values())
    checks["pdf_hash_match"] = sha(REPORT_PDF) == qc["pdf_sha256"]
    checks["pdf_pages_positive"] = qc["pages"] > 0 and qc["checks"]["no_blank_pages"]
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
    source_audit = json.loads((OUT / "source_audit.json").read_text(encoding="utf-8"))
    kb_audit = json.loads((OUT / "kb_audit_menu_evidence_binding_20261125.json").read_text(encoding="utf-8"))
    qc = json.loads(QC_JSON.read_text(encoding="utf-8"))
    files = [artifact(path, "交付工件") for path in delivery_files()]
    key_production = [
        ROOT / "_工具脚本/taspipe/sources.py",
        ROOT / "_工具脚本/taspipe/sources_selftest_gates.py",
        ROOT / "_工具脚本/taspipe/游戏包/来源库/sources.json",
        ROOT / "_工具脚本/taspipe/游戏包/复古游戏文献来源库.md",
        ROOT / "_工具脚本/taspipe/游戏包/gba_aria_of_sorrow_souls.menu_catalog.json",
        EVIDENCE_DIR / "menu_catalog_report.json",
        EVIDENCE_DIR / "source_capture_report.json",
        EVIDENCE_DIR / "menu_catalog_nav_full.json",
        EVIDENCE_DIR / "menu_names_observed.json",
        EVIDENCE_DIR / "menu_effects_observed.json",
        EVIDENCE_DIR / "menu_patch_vs_nav_audit.json",
        REPORT_MD,
        REPORT_PDF,
    ]
    files.extend(artifact(path, "生产修正或报告") for path in key_production)
    manifest = {
        "schema": "kb_final_manifest_menu_evidence_binding_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "晓月圆舞曲114项菜单证据固化、稳定ID、候选来源覆盖与审计反证格；旧交付不变。",
        "all_checks_ok": True,
        "production_defaults": {
            "top_window": 3, "fragment_policy": None, "fact_selector": None,
            "strict_production_default": False, "dense_production_default": False,
            "gba_platform_gate": False, "commercial_rom_or_bios_ingested": False,
        },
        "preflight": pre,
        "gates": gate_counts(),
        "audits": {
            "sources": {"status": source_audit["status"], "counts": source_audit["counts"],
                        "artifact": artifact(OUT / "source_audit.json", "来源审计")},
            "kb": {"status": kb_audit["status"], "counts": kb_audit["counts"],
                   "artifact": artifact(OUT / "kb_audit_menu_evidence_binding_20261125.json", "知识库审计")},
        },
        "menu_evidence": {
            "elements": 114, "media_files": 342, "media_bytes": 6874438,
            "missing_files": 0, "hash_mismatches": 0,
            "source_status": "candidate", "gameplay_verified": False,
            "detector_verified": False, "platform_gate_verified": False,
        },
        "pdf_qc": {"pages": qc["pages"], "checks": qc["check_count"],
                   "artifact": artifact(QC_JSON, "PDF质检"), "pdf": artifact(REPORT_PDF, "报告PDF")},
        "protected_delivery": artifact(OUT / "protected_delivery_hashes_20261125.json", "旧交付保护"),
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
        "schema": "menu_evidence_final_delivery_verification_v1",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass", "all_checks_ok": True,
        "check_count": len(checks), "checks": checks,
        "manifest": artifact(MANIFEST, "最终manifest"),
        "source_audit": manifest["audits"]["sources"]["counts"],
        "kb_audit": manifest["audits"]["kb"]["counts"],
        "gates": {key: f"{value['passed']}/{value['total']}" for key, value in manifest["gates"].items()},
        "pdf": manifest["pdf_qc"],
        "remaining": {
            "menu_candidate_elements": 114, "legacy_weak_elements": 40,
            "present_unverified_versions": 6, "registered_empty_versions": 9,
            "gba_platform_gate": False, "strict_production_default": False,
            "dense_production_default": False, "dynamic_esports_results": 0,
        },
    }
    write_json(VERIFICATION, result)
    return result


def build_inventory():
    paths = {path.resolve() for path in delivery_files()}
    paths.update(path.resolve() for path in EVIDENCE_DIR.rglob("*") if path.is_file())
    paths.update((ROOT / rel).resolve() for rel in [
        "_工具脚本/taspipe/sources.py",
        "_工具脚本/taspipe/sources_selftest_gates.py",
        "_工具脚本/taspipe/游戏包/来源库/sources.json",
        "_工具脚本/taspipe/游戏包/复古游戏文献来源库.md",
        "_工具脚本/taspipe/游戏包/gba_aria_of_sorrow_souls.menu_catalog.json",
        "知识库改进优化指导_2026-11-25_晓月菜单证据固化与来源覆盖修正.md",
        "知识库改进优化指导_2026-11-25_晓月菜单证据固化与来源覆盖修正.pdf",
    ])
    files = []
    for path in sorted(paths):
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            relative = str(path)
        if EVIDENCE_DIR in path.parents:
            role = "菜单固化证据"
        elif path in (REPORT_MD, REPORT_PDF):
            role = "独立报告"
        elif OUT in path.parents:
            role = "交付工件"
        else:
            role = "生产修正"
        files.append(artifact(path, role))
        files[-1]["relative_path"] = relative
    data = {
        "schema": "menu_evidence_artifact_inventory_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files), "total_bytes": sum(item["bytes"] for item in files),
        "scope": "新交付目录、114项菜单的342份媒体与支撑文件、本轮生产修正和报告；不含清单自身及清单验证结果。",
        "files": files,
    }
    write_json(INVENTORY_JSON, data)
    lines = [
        "# 晓月菜单证据固化交付 · 逐件工件清单",
        "",
        f"- 文件数：{len(files)}",
        f"- 总字节数：{sum(item['bytes'] for item in files)}",
        "- 范围：新交付目录、342 份菜单媒体及支撑文件、生产修正和报告；不含本清单自身及清单验证结果。",
        "",
        "| 相对路径 | 角色 | 字节 | SHA-256 |",
        "|---|---|---:|---|",
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
    links = re.findall(r"file:///([^)\s#]+)", REPORT_MD.read_text(encoding="utf-8"))
    for raw in links:
        path = Path(unquote(raw))
        checks[f"report_link:{raw}"] = path.exists()
    assert links
    assert all(checks.values()), [key for key, value in checks.items() if not value]
    result = {
        "schema": "menu_evidence_artifact_inventory_verification_v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass", "all_checks_ok": True, "check_count": len(checks),
        "inventory_files": inventory["file_count"], "report_links": len(links),
        "checks": checks,
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
        raise SystemExit("用法: finalize_menu_evidence_delivery_20261125.py {manifest|verify|inventory|check}")
    print(json.dumps({"stage": stage, "status": result.get("status", "pass"),
                      "files": result.get("file_count", len(result.get("files", []))),
                      "checks": result.get("check_count")}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
