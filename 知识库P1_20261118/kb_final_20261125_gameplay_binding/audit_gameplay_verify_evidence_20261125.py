from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "知识库P1_20261118/kb_final_20261125_menu_visual_review/gameplay_evidence_audit_20261125.json"
OLD = ROOT / "04-游戏资源库/TAS输入录像库/状态资产/castlevania_aria_gba/aria_us_40aab076/r20261125T040115/calibration"
NEW = ROOT / "04-游戏资源库/TAS输入录像库/状态资产/castlevania_aria_gba/aria_us_40aab076/r20261125T153709/calibration"
ROM = "40AAB076A528F52E93260BB98D91A40039E0DA02"
CORE = "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk"
SLOTS = {"red": 78429, "blue": 78430, "yellow": 78431}
CASES = [
    ("red_soul_4_verify_vs_empty", "red", 4, "半鱼人", 67, 80, 90, 0, OLD),
    ("red_soul_5_verify_vs_empty", "red", 5, "斧装甲", 59, 80, 90, 0, OLD),
    ("red_soul_12_verify_vs_empty", "red", 12, "小恶魔", 63, 80, 90, 0, OLD),
    ("red_soul_24_verify_vs_empty", "red", 24, "魔鸟", 56, 80, 90, 0, OLD),
    ("red_soul_31_verify_vs_empty", "red", 31, "噩梦", 51, 80, 90, 0, OLD),
    ("red_soul_37_verify_vs_empty", "red", 37, "比夫隆", 46, 80, 90, 0, OLD),
    ("blue_soul_2_verify_vs_empty", "blue", 2, "大蝙蝠", 22, 80, 120, 0, OLD),
    ("blue_soul_4_verify_vs_empty", "blue", 4, "布艾尔", 72, 80, 120, 0, OLD),
    ("blue_soul_6_verify_vs_empty", "blue", 6, "大鬼魂", 72, 80, 120, 0, OLD),
    ("blue_soul_13_verify_vs_empty", "blue", 13, "幻魔士", 72, 80, 120, 0, OLD),
    ("blue_soul_22_verify_vs_empty", "blue", 22, "子恶魔", 76, 80, 120, 0, OLD),
    ("red_soul_35_resource_verify", "red", 35, "虎人", 41, 80, 90, 0, NEW),
    ("red_soul_47_resource_verify", "red", 47, "圆盘装甲", 1, 80, 90, 0, NEW),
    ("yellow_soul_10_hp_advantage", "yellow", 10, "巨虫", 302, 292, 226, 0, NEW),
    ("yellow_soul_15_hp_advantage", "yellow", 15, "蛇尾鸟", 300, 292, 226, 0, NEW),
    ("yellow_soul_26_hp_advantage", "yellow", 26, "白骨龙", 300, 292, 226, 0, NEW),
    ("yellow_soul_27_hp_advantage", "yellow", 27, "古代龙神", 308, 292, 226, 0, NEW),
    ("yellow_soul_28_hp_advantage", "yellow", 28, "石化牛", 316, 292, 226, 0, NEW),
    ("yellow_soul_29_hp_advantage", "yellow", 29, "死亡十字军", 316, 292, 226, 0, NEW),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifact(path):
    path = Path(path).resolve()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)}


def value(expect, addr):
    rows = [row for row in expect if row["addr"] == addr]
    assert len(rows) == 1, (addr, rows)
    return rows[0]["got"]


def audit_case(spec):
    case_id, group, soul_id, name, pos_value, neg_value, frames, initial_equal_frames, archive = spec
    case_dir = archive / case_id
    report_path = case_dir / "report.json"
    recipe_path = case_dir / "recipe.json"
    manifest_path = case_dir / "manifest.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == recipe["schema_version"] == manifest["schema_version"] == "ram_calibration/1.0"
    assert report["mode"] == manifest["mode"] == "verify"
    assert recipe["schema_version"] == "ram_calibration/1.0"
    assert report["status"] == manifest["status"] == "pass"
    assert report["game_id"] == recipe["game_id"] == manifest["game_id"] == "castlevania_aria_gba"
    assert report["case_id"] == manifest["case_id"] == case_id
    assert report["rom_sha1"] == ROM
    assert recipe["profile"]["rom_sha1"].upper() == ROM
    assert manifest["report_sha256"] == sha(report_path)
    assert manifest["recipe_sha256"] == sha(recipe_path)
    assert recipe["profile"]["state_package"]["game_id"] == "castlevania_aria_gba"
    assert recipe["profile"]["state_package"]["profile_id"] == "aria_us_40aab076"
    assert len(report["checks"]) == 6 and all(report["checks"].values()), report["checks"]
    assert isinstance(report["arms"], dict) and len(report["arms"]) == 2
    pos_name = f"{group}_{soul_id}"
    neg_name = f"{group}0"
    assert set(report["arms"]) == {pos_name, neg_name}
    slot = SLOTS[group]
    metric = 78446 if group == "yellow" else 78448
    for arm_name, arm in report["arms"].items():
        assert arm["steps"]
        for step in arm["steps"]:
            assert step["expect"] and all(row["pass"] for row in step["expect"])
            assert step["actual_core"] == CORE
            assert step["attempt"]["ok"] is True
        first = arm["steps"][0]
        patches = first["patches"]
        assert len(patches) == 1 and patches[0]["addr"] == slot
        assert patches[0]["value"] == (soul_id if arm_name == pos_name else 0)
        last = arm["steps"][-1]
        assert value(last["expect"], slot) == (soul_id if arm_name == pos_name else 0)
        assert last["captured_frames"] == frames
        if arm_name == pos_name:
            assert value(last["expect"], metric) == pos_value
        else:
            assert value(last["expect"], metric) == neg_value
    if group == "yellow":
        for arm_name in (pos_name, neg_name):
            assert value(report["arms"][arm_name]["steps"][0]["expect"], 78448) == 80
    assert report["comparisons"]
    for comparison in report["comparisons"]:
        assert comparison["left"] == pos_name and comparison["right"] == neg_name
        assert comparison["relation"] == "different"
        assert comparison["pass"] is True
        assert comparison["frames"] and all(row["pass"] for row in comparison["frames"])
        equal_frames = sum(row["equal"] for row in comparison["frames"])
        assert equal_frames == initial_equal_frames, (case_id, equal_frames)
        assert any(not row["equal"] for row in comparison["frames"])
    assert manifest["evidence"] and report["evidence"]
    evidence = []
    for row in manifest["evidence"]:
        path = case_dir / row["path"]
        assert path.is_file(), path
        assert path.stat().st_size == row["bytes"], path
        assert sha(path) == row["sha256"], path
        evidence.append(row)
    assert len(report["evidence"]) == len(evidence)
    assert set(map(str, report["evidence"])) == {row["source"] for row in evidence}
    revision = recipe["profile"]["state_package"]["revision"]
    assert archive.name == "calibration"
    return {
        "case_id": case_id,
        "element": {"group": group, "id": soul_id, "name_zh": name},
        "source": {"archive_revision": archive.parent.name, "state_revision": revision},
        "rom_sha1": ROM,
        "actual_core": CORE,
        "slot": {"addr": slot, "positive": soul_id, "negative": 0},
        "metric": {"addr": metric, "positive": pos_value, "negative": neg_value,
                   "name": "current_hp" if group == "yellow" else "current_mp"},
        "captured_frames_per_arm": frames,
        "comparison": {"equal_frames": initial_equal_frames,
                       "different_frames": frames - initial_equal_frames,
                       "pass": True},
        "report": artifact(report_path),
        "recipe": artifact(recipe_path),
        "manifest": artifact(manifest_path),
        "evidence_files": len(evidence),
        "evidence_bytes": sum(row["bytes"] for row in evidence),
        "verified_fields": report["verified_fields"],
    }


def scope_for(row):
    if row["element"]["group"] in ("red", "blue"):
        return {
            "proves": "固定战斗初态只改对应槽位并执行角色宏；目标槽保持、MP低于80，空槽保持80，抽样帧存在真实差异。",
            "does_not_prove": "不证明伤害、射程、全部招式语义、中文菜单装备流程或任意场景稳定性。",
        }
    if row["element"]["id"] == 10:
        return {
            "proves": "固定受击路线末HP为302，空槽对照为292；正例末帧高于空魂。",
            "does_not_prove": "不把蓝魂10的表现外推为其他黄魂，不单凭末HP判定完整机制。",
        }
    return {
        "proves": "固定受击路线末HP高于空魂对照292；只证明该ID在该路线中的末HP优势。",
        "does_not_prove": "不证明防御升降、CON精确点数或单次受击伤害；同路线末HP相同的项目不得据此区分机制。",
    }


def main():
    rows = [audit_case(spec) for spec in CASES]
    for row in rows:
        row["scope"] = scope_for(row)
    checks = {
        "cases_19": len(rows) == 19,
        "unique_cases_19": len({row["case_id"] for row in rows}) == 19,
        "red_blue_13": sum(row["element"]["group"] in ("red", "blue") for row in rows) == 13,
        "yellow_6": sum(row["element"]["group"] == "yellow" for row in rows) == 6,
        "all_verify_pass": all(row["comparison"]["pass"] for row in rows),
        "evidence_460": sum(row["evidence_files"] for row in rows) == 460,
        "all_report_manifest_hashes": True,
        "all_recipe_manifest_hashes": True,
        "actual_core_uniform": {row["actual_core"] for row in rows} == {CORE},
        "rom_uniform": {row["rom_sha1"] for row in rows} == {ROM},
        "no_detector_or_platform_claim": True,
    }
    assert all(checks.values()), checks
    data = {
        "schema_version": "aria_gameplay_verify_evidence_audit/1.0",
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "all_checks_ok": True,
        "checks": checks,
        "scope": "只读逐案复核19份正式玩法正反例；通过后才可把对应19项菜单目录回绑为限定路线gameplay_verified=true。",
        "not_granted": {"detector_verified": False, "platform_verified": False,
                        "human_visual_review": False, "strict_production_default": False,
                        "dense_production_default": False},
        "cases": rows,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": data["status"], "cases": len(rows),
                      "evidence_files": sum(row["evidence_files"] for row in rows),
                      "evidence_bytes": sum(row["evidence_bytes"] for row in rows),
                      "output": OUT.relative_to(ROOT).as_posix(),
                      "output_sha256": sha(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
