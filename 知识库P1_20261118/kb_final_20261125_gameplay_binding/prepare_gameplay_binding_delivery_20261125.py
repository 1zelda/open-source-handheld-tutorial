from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OLD_OUT = ROOT / "知识库P1_20261118/kb_final_20261125_menu_visual_review"
GAME = ROOT / "_工具脚本/taspipe/游戏包"
TOOLS = ROOT / "_工具脚本/taspipe"
BINDING = GAME / "证据/晓月圆舞曲/gameplay_verify_binding_20261125"
PROTECTED = OUT / "protected_delivery_hashes_gameplay_binding_20261125.json"
PREFLIGHT = OUT / "preflight_fingerprints_gameplay_binding_20261125.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifact(path, role):
    path = Path(path).resolve()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "sha256": sha(path), "role": role}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def protect_old_deliveries():
    expected = {}
    previous = json.loads((OLD_OUT / "protected_delivery_hashes_menu_visual_review_20261125.json").read_text(encoding="utf-8"))
    for item in previous["files"]:
        expected[item["path"]] = item["expected"]
    inventory = json.loads((OLD_OUT / "artifact_inventory_menu_visual_review_20261125.json").read_text(encoding="utf-8"))
    for item in inventory["files"]:
        if item["role"] != "生产修正":
            expected[item["path"]] = item["sha256"]
    old_dirs = [
        ROOT / "知识库P1_20261118/kb_final_20261124",
        ROOT / "知识库P1_20261118/kb_final_20261124_source_inheritance",
        ROOT / "知识库P1_20261118/kb_final_20261125_source_audit_fix",
        ROOT / "知识库P1_20261118/kb_final_20261125_menu_evidence_binding",
        OLD_OUT,
    ]
    for directory in old_dirs:
        for path in directory.rglob("*"):
            if path.is_file():
                expected[path.relative_to(ROOT).as_posix()] = sha(path)
    files = []
    for rel, digest in sorted(expected.items()):
        path = ROOT / rel
        actual = sha(path) if path.is_file() else None
        files.append({"path": rel, "expected": digest, "actual": actual,
                      "unchanged": actual == digest})
    assert all(item["unchanged"] for item in files), [item["path"] for item in files if not item["unchanged"]]
    result = {"schema_version": "gameplay_binding_protected_delivery_hashes/1.0",
              "checked_at": datetime.now(timezone.utc).isoformat(), "status": "pass",
              "checked": len(files), "unchanged": len(files), "files": files}
    write_json(PROTECTED, result)
    return result


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
        match = re.search(pattern, (OUT / name).read_text(encoding="utf-8"))
        assert match, name
        if key == "topic_selftest":
            total, passed, failed = map(int, match.groups())
            assert failed == 0
        else:
            passed, total = map(int, match.groups())
        assert passed == total
        result[key] = [passed, total]
    return result


def main():
    protected = protect_old_deliveries()
    sources = {
        "source_registry": GAME / "来源库/sources.json",
        "source_catalog_md": GAME / "复古游戏文献来源库.md",
        "menu_catalog": GAME / "gba_aria_of_sorrow_souls.menu_catalog.json",
        "corpus_map": GAME / "知识库/corpus_map.json",
        "index": GAME / "知识库/index.json",
        "gameplay_binding": BINDING / "gameplay_evidence_binding_20261125.json",
        "gameplay_inventory": BINDING / "artifact_inventory.json",
        "gameplay_audit": OUT / "gameplay_evidence_audit_20261125.json",
        "gameplay_verification": OUT / "gameplay_binding_verification_20261125.json",
        "source_audit": OUT / "source_audit_gameplay_binding_20261125.json",
        "kb_audit": OUT / "kb_audit_gameplay_binding_20261125.json",
        "coverage": OUT / "coverage_gameplay_binding_20261125.json",
    }
    code = {
        "sources_audit": TOOLS / "sources.py",
        "sources_selftest_gates": TOOLS / "sources_selftest_gates.py",
        "kb": TOOLS / "kb.py",
        "kb_selftest_gates": TOOLS / "kb_selftest_gates.py",
        "cross_platform_gates": TOOLS / "cross_platform_selftest_gates.py",
        "showcase": TOOLS / "showcase.py",
        "audit_gameplay": OUT / "audit_gameplay_verify_evidence_20261125.py",
        "bind_gameplay": OUT / "bind_gameplay_verify_evidence_20261125.py",
        "verify_gameplay": OUT / "verify_gameplay_binding_20261125.py",
        "prepare_delivery": OUT / "prepare_gameplay_binding_delivery_20261125.py",
        "build_report": OUT / "build_report_gameplay_binding_20261125.py",
        "render_qc": OUT / "render_qc_gameplay_binding_20261125.py",
        "finalize_delivery": OUT / "finalize_gameplay_binding_delivery_20261125.py",
    }
    data = {key: artifact(path, "数据") for key, path in sources.items()}
    code_rows = {key: artifact(path, "代码") for key, path in code.items()}
    assert data["index"]["sha256"] == "05907ec85146f386325285ccd4d2008d8bc28d50d8ec4e2461c14a9351f03f7d"
    pack = json.loads(sources["menu_catalog"].read_text(encoding="utf-8"))
    binding = json.loads(sources["gameplay_binding"].read_text(encoding="utf-8"))
    source_audit = json.loads(sources["source_audit"].read_text(encoding="utf-8"))
    kb_audit = json.loads(sources["kb_audit"].read_text(encoding="utf-8"))
    weak = next(item["detail"] for item in source_audit["checks"] if item["check_id"] == "verified_support")
    coverage = json.loads(sources["coverage"].read_text(encoding="utf-8"))
    states = {}
    for row in coverage["rows"]:
        states[row["state"]] = states.get(row["state"], 0) + 1
    assert sum(item["gameplay_verified"] for item in pack["elements"]) == 19
    assert sum(item["gameplay_verified"] is False for item in pack["elements"]) == 95
    assert all(item["detector_verified"] is False for item in pack["elements"])
    assert binding["counts"]["copied_files"] == 519
    assert len(weak) == 141 and sum("menu_catalog" in item for item in weak) == 95
    assert source_audit["counts"]["fail"] == 0 and source_audit["counts"]["elements_supported"] == 208
    assert kb_audit["counts"]["fail"] == 0 and kb_audit["counts"]["chunks"] == 826
    assert states == {"verified": 11, "present_unverified": 6, "registered_empty": 9}
    result = {
        "schema_version": "gameplay_binding_preflight_fingerprints/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code": code_rows,
        "data": data,
        "gates": gate_counts(),
        "protected_delivery": {"checked": protected["checked"], "unchanged": protected["unchanged"]},
        "source_audit": {"counts": source_audit["counts"], "weak_total": len(weak),
                         "menu_weak": sum("menu_catalog" in item for item in weak),
                         "detector_weak": sum("detectors" in item for item in weak)},
        "kb_audit": kb_audit["counts"],
        "coverage": states,
        "gameplay": {"elements": 114, "verified": 19, "false": 95,
                     "detector_false": 114, "copied_files": 519, "copied_bytes": 14958586},
        "production_defaults": {"top_window": 3, "fragment_policy": None, "fact_selector": None,
                                "strict_production_default": False, "dense_production_default": False,
                                "gba_platform_gate": False, "commercial_rom_or_bios_ingested": False},
    }
    write_json(PREFLIGHT, result)
    print(json.dumps({"status": "pass", "protected": protected["checked"],
                      "gates": result["gates"], "preflight_sha256": sha(PREFLIGHT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
