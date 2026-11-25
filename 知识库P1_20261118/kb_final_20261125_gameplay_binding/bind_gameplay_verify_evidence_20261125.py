from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "_工具脚本/taspipe/游戏包"
PACK = GAME / "gba_aria_of_sorrow_souls.menu_catalog.json"
REGISTRY = GAME / "来源库/sources.json"
CORPUS = GAME / "知识库/corpus_map.json"
AUDIT = ROOT / "知识库P1_20261118/kb_final_20261125_menu_visual_review/gameplay_evidence_audit_20261125.json"
AUDIT_SCRIPT = Path(__file__).with_name("audit_gameplay_verify_evidence_20261125.py")
EVIDENCE = GAME / "证据/晓月圆舞曲/gameplay_verify_binding_20261125"
INVENTORY = EVIDENCE / "artifact_inventory.json"
BINDING = EVIDENCE / "gameplay_evidence_binding_20261125.json"
SOURCE_ID = "local_aria_gameplay_verify_20261125"
EXPECTED = {
    PACK: "fc3a258a9c6b245a31b159bffc7a4d141a3ef31cf46b6bc6c74afa95c414bc3e",
    REGISTRY: "456576759073e46fb303a02538e6769f9837d883b633b9c4a1cc8781fc87285f",
    CORPUS: "e49bb480ad4aa58d0ce97a47af7fabe49a7453fde90d01631350b3bf662342df",
    AUDIT: "d24cd089784213fe0048a55a8db8fe47a0ba4cace7926dd325f7c5ce56fa3d4d",
}
ELEMENT_PREFIX = {"red": "aria_red", "blue": "aria_blue", "yellow": "aria_yellow"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fingerprint(path):
    return {"path": rel(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def copy_verified(source, target, expected_sha=None, expected_bytes=None):
    data = Path(source).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha is not None:
        assert digest == expected_sha, source
    if expected_bytes is not None:
        assert len(data) == expected_bytes, source
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    assert sha(target) == digest


def source_entry(element_ids):
    return {
        "source_id": SOURCE_ID,
        "url": "",
        "status": "verified_read",
        "verified_date": "2026-11-25",
        "element_ids": element_ids,
        "evidence_report": rel(BINDING),
    }


def corpus_entry(path, note):
    return {
        "path": path.resolve().as_posix(),
        "source_id": SOURCE_ID,
        "revision": "castlevania_aria_gba",
        "kind": "table",
        "authority": "authoritative",
        "index": False,
        "reason": "本机mGBA固定路线正反例结构化取证，在册备查但不进BM25；资格只覆盖报告中明确验证的槽位、RAM结果和抽样帧差异。",
        "element_types": ["出招表", "视频验证", "帧数据"],
        "note": note,
    }


def main():
    assert not EVIDENCE.exists(), f"固化目录已存在，停止覆盖: {EVIDENCE}"
    for path, expected in EXPECTED.items():
        assert path.is_file() and sha(path) == expected, f"输入指纹变化: {rel(path)}"
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "pass" and audit["all_checks_ok"] is True
    assert len(audit["cases"]) == 19
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert len(pack["elements"]) == 114
    assert all(item["gameplay_verified"] is False for item in pack["elements"])
    assert all(item["detector_verified"] is False for item in pack["elements"])
    assert pack["visual_review"]["human_visual_review"] is False
    assert pack["catalog"]["sources"][0]["source_id"] == "local_aria_menu_catalog_20261125"
    assert pack["catalog"]["sources"][0]["status"] == "candidate"
    assert not any(item["source_id"] == SOURCE_ID for item in registry["sources"])
    old_gameplay = next(item for item in registry["sources"] if item["source_id"] == "local_gameplay_20261124")
    assert old_gameplay["status"] == "candidate" and old_gameplay["last_verified"] is None
    elements = {item["element_id"]: item for item in pack["elements"]}
    copied = []
    bound_cases = []
    element_ids = []
    report_paths = []
    for row in audit["cases"]:
        element_id = f"{ELEMENT_PREFIX[row['element']['group']]}_{row['element']['id']:03d}"
        assert element_id in elements and elements[element_id]["name_zh"] == row["element"]["name_zh"]
        source_case = (ROOT / row["report"]["path"]).parent
        target_case = EVIDENCE / row["case_id"]
        for kind in ("report", "recipe", "manifest"):
            source = source_case / f"{kind}.json"
            target = target_case / f"{kind}.json"
            copy_verified(source, target, row[kind]["sha256"], row[kind]["bytes"])
            copied.append(fingerprint(target))
        manifest = json.loads((source_case / "manifest.json").read_text(encoding="utf-8"))
        for item in manifest["evidence"]:
            source = source_case / item["path"]
            target = target_case / item["path"]
            copy_verified(source, target, item["sha256"], item["bytes"])
            copied.append(fingerprint(target))
        bound = dict(row)
        bound["element_id"] = element_id
        bound["evidence_case_dir"] = rel(target_case)
        bound["report"]["path"] = rel(target_case / "report.json")
        bound["recipe"]["path"] = rel(target_case / "recipe.json")
        bound["manifest"]["path"] = rel(target_case / "manifest.json")
        bound_cases.append(bound)
        element_ids.append(element_id)
        report_paths.append(bound["report"]["path"])
    copy_verified(AUDIT, EVIDENCE / AUDIT.name, EXPECTED[AUDIT])
    copy_verified(AUDIT_SCRIPT, EVIDENCE / AUDIT_SCRIPT.name)
    copied.extend([fingerprint(EVIDENCE / AUDIT.name), fingerprint(EVIDENCE / AUDIT_SCRIPT.name)])
    copied.sort(key=lambda item: item["path"])
    assert len(copied) == 519
    write_json(INVENTORY, {
        "schema_version": "aria_gameplay_verify_evidence_inventory/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(copied),
        "total_bytes": sum(item["bytes"] for item in copied),
        "files": copied,
    })
    binding = {
        "schema_version": "aria_gameplay_evidence_binding/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "all_checks_ok": True,
        "source_id": SOURCE_ID,
        "rom_sha1": "40AAB076A528F52E93260BB98D91A40039E0DA02",
        "actual_core": "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk",
        "scope": "19项菜单要素的固定路线本机玩法正反例绑定；不改变菜单身份来源的candidate资格。",
        "counts": {"elements_bound": 19, "gameplay_false": 95, "detector_false": 114,
                   "copied_files": len(copied), "evidence_files": 460,
                   "copied_bytes": sum(item["bytes"] for item in copied)},
        "state_revisions": sorted({row["source"]["state_revision"] for row in bound_cases}),
        "archive_revisions": sorted({row["source"]["archive_revision"] for row in bound_cases}),
        "audit": fingerprint(AUDIT),
        "inventory": fingerprint(INVENTORY),
        "input_fingerprints": {rel(path): {"sha256": sha(path), "bytes": path.stat().st_size}
                               for path in (PACK, REGISTRY, CORPUS)},
        "not_granted": {"menu_identity_candidate_upgrade": False, "detector_verified": False,
                        "platform_verified": False, "human_visual_review": False,
                        "remaining_95_gameplay_verified": False, "strict_production_default": False,
                        "dense_production_default": False},
        "cases": bound_cases,
    }
    write_json(BINDING, binding)
    for row in bound_cases:
        item = elements[row["element_id"]]
        item["gameplay_verified"] = True
        item["gameplay_evidence"] = {
            "source_id": SOURCE_ID,
            "status": "fixed_route_pass",
            "case_id": row["case_id"],
            "evidence_report": rel(BINDING),
            "report": row["report"],
            "state_revision": row["source"]["state_revision"],
            "archive_revision": row["source"]["archive_revision"],
            "slot": row["slot"],
            "metric": row["metric"],
            "captured_frames_per_arm": row["captured_frames_per_arm"],
            "comparison": row["comparison"],
            "proves": row["scope"]["proves"],
            "does_not_prove": row["scope"]["does_not_prove"],
        }
    pack["schema_version"] = "aria_soul_menu_catalog/1.2"
    pack["scope"] = "menu_identity_description_and_scoped_gameplay"
    pack["catalog"]["sources"].append(source_entry(element_ids))
    pack["gameplay_verification"] = {
        "source_id": SOURCE_ID,
        "status": "pass_with_fixed_route_scope",
        "verified_date": "2026-11-25",
        "report": rel(BINDING),
        "report_sha256": sha(BINDING),
        "elements_verified": 19,
        "elements_unverified": 95,
        "detector_verified": 0,
        "platform_verified": False,
        "state_revisions": binding["state_revisions"],
        "boundary": "只回绑报告中逐项验证的固定路线；菜单身份、其余玩法、全部检测器和平台总闸门资格不变。",
    }
    registry["sources"].append({
        "source_id": SOURCE_ID,
        "name": "晓月圆舞曲 GBA 19项魂固定路线玩法正反例（2026-11-25）",
        "kind": "local",
        "layer": "local_emu",
        "platforms": ["GBA"],
        "element_types": ["出招表", "视频验证", "帧数据"],
        "status": "verified_read",
        "last_verified": "2026-11-25",
        "urls": [],
        "evidence": [rel(BINDING)] + report_paths,
        "notes": "19份mode=verify/status=pass报告经报告、配方、manifest与460份证据逐件复算；13项红蓝魂只证明固定路线槽位保持、MP消耗和抽样帧差异，6项黄魂只证明固定受击路线末HP优势。菜单身份、其余95项玩法、全部检测器、人工签核和GBA平台总闸门不放行；不洗白local_gameplay_20261124候选。",
        "games_hit": ["CastlevaniaAriaOfSorrow_GBA", "castlevania_aria_gba"],
    })
    corpus_entries = [corpus_entry(BINDING, "19项固定路线玩法绑定总报告；逐案列出正反例、RAM、抽样帧、范围与禁止外推项。")]
    for row in bound_cases:
        note = f"{row['case_id']}：{row['scope']['proves']} {row['scope']['does_not_prove']}"
        corpus_entries.append(corpus_entry(ROOT / row["report"]["path"], note))
    corpus["entries"].extend(corpus_entries)
    write_json(PACK, pack)
    write_json(REGISTRY, registry)
    write_json(CORPUS, corpus)
    assert sum(item["gameplay_verified"] for item in pack["elements"]) == 19
    assert all(item["detector_verified"] is False for item in pack["elements"])
    assert next(item for item in registry["sources"] if item["source_id"] == "local_gameplay_20261124")["status"] == "candidate"
    print(json.dumps({
        "status": "pass", "elements_bound": 19, "gameplay_false": 95,
        "copied_files": len(copied), "copied_bytes": sum(item["bytes"] for item in copied),
        "binding": rel(BINDING), "binding_sha256": sha(BINDING),
        "pack_sha256": sha(PACK), "registry_sha256": sha(REGISTRY),
        "corpus_map_sha256": sha(CORPUS),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
