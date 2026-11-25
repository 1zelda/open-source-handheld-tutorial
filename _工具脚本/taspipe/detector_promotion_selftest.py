# -*- coding: utf-8 -*-
"""检测器晋升生产入口离线自检。"""
import copy
import hashlib
import json
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import detector_calibration as DC
from . import detector_promotion as DP
from . import showcase

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition)))
    print(f"{'PASS' if condition else 'FAIL'} {name}" + (f" | {detail}" if detail and not condition else ""))


def _write_json(path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _fixture(root, aligned=False):
    root.mkdir(parents=True)
    pos_dir, neg_dir = root / "pos", root / "neg"
    pos_dir.mkdir()
    neg_dir.mkdir()
    state = root / "base.state"
    state.write_bytes(b"STATE")
    (root / "bizhawk").mkdir()
    if aligned:
        base = np.zeros((64, 96, 3), dtype=np.uint8)
        base[:32] = (20, 30, 40)
        base[:32, :, 0] = np.arange(96, dtype=np.uint8) * 2
        base[32:] = (8, 10, 14)
        negative = Image.fromarray(base, "RGB")
        positive = Image.fromarray(np.roll(base, 2, axis=1), "RGB")
        ImageDraw.Draw(positive).rectangle((30, 40, 41, 51), fill=(240, 70, 90))
        detection = {
            "frame": 1,
            "success_checks": [{
                "check_id": "synthetic_aligned_visual",
                "plugin_id": "frame_pair_aligned_region_difference",
                "params": {
                    "region": [0.25, 0.5, 0.75, 1.0],
                    "alignment_region": [0.0, 0.0, 1.0, 0.5],
                    "max_shift": 4,
                    "max_dy": 0,
                    "diff_threshold": 42,
                    "min_changed_fraction": 0.02,
                    "max_global_changed_fraction": 0.25,
                },
                "required": True,
            }],
        }
    else:
        negative = Image.new("RGB", (96, 64), "black")
        positive = Image.new("RGB", (96, 64), "black")
        ImageDraw.Draw(positive).rectangle((24, 16, 71, 47), fill=(255, 0, 0))
        detection = {
            "frame": 1,
            "success_checks": [{
                "check_id": "synthetic_color_visual",
                "plugin_id": "frame_region_color_fraction",
                "params": {
                    "region": [0.25, 0.25, 0.75, 0.75],
                    "rgb": [255, 0, 0],
                    "tol": 4,
                    "min_fraction": 0.05,
                },
                "required": True,
            }],
        }
    positive.save(pos_dir / "f0001.png")
    negative.save(neg_dir / "f0001.png")
    positive.save(pos_dir / "f0000.png")
    negative.save(neg_dir / "f0000.png")

    rom_sha1 = "0" * 40
    base_pack = root / "base.showcase.json"
    _write_json(base_pack, {
        "schema_version": 1,
        "kind": "statejump_showcase",
        "game_id": "synthetic",
        "platform": "GBA",
        "core": "mGBA",
        "system": "GBA",
        "rom": str(root / "game.gba"),
        "rom_sha1": rom_sha1,
        "bizhawk": str(root / "bizhawk"),
        "base_state": str(state),
        "fps": 59.7275,
        "catalog": {"status": "complete", "expected_total": 1, "sources": [{"source_id": "synthetic"}]},
        "elements": [],
    })
    case = {
        "case_id": "synthetic_aligned" if aligned else "synthetic_color",
        "method": "aligned_difference" if aligned else "color_region",
        "status": "pass",
        "detection": detection,
        "verification": {"pass": True},
        "timeline_audit": {
            "pass": True,
            "scope": "all_available_acceptance_dump_frames",
            "paired_frames": 1,
            "positive_counts": {"pass": 1},
            "negative_counts": {"fail": 1},
            "negative_all_fail": True,
            "negative_control_kind": "same_empty_frame_self_difference" if aligned else "target_color_absent",
            "expectations": [],
        },
        "sample_isolation": {
            "method": "disjoint_frame_partition",
            "source_partition": {
                "pos": {"overlap": []},
                "neg": {"overlap": []},
            },
        },
    }
    report_path = root / "calibration_report.json"
    _write_json(report_path, {
        "schema_version": DC.SCHEMA_VERSION,
        "status": "pass",
        "detector_impl_sha256": showcase._detector_impl_sha(),
        "cases": [case],
    })
    registry_path = root / "sources.json"
    _write_json(registry_path, {
        "schema_version": 1,
        "updated": "2026-11-25",
        "note": "离线合成来源库夹具",
        "sources": [{
            "source_id": "synthetic_calibration",
            "name": "合成检测器标定候选",
            "kind": "local",
            "layer": "local_emu",
            "platforms": ["GBA"],
            "element_types": ["帧数据"],
            "status": "candidate",
            "last_verified": None,
            "urls": [],
            "evidence": [str(report_path)],
            "notes": "只证明合成画面差异。",
        }],
        "absence_claims": [],
    })
    action_checks = copy.deepcopy(detection["success_checks"])
    for check in action_checks:
        check["check_id"] += "_action"
    element = {
        "case_id": case["case_id"],
        "element_id": case["case_id"],
        "label": "Synthetic aligned" if aligned else "Synthetic color",
        "kind": "skill",
        "base_state": str(state),
        "trigger": {"macro": "B", "extra": 1, "patches": []},
        "negative_control": {"macro": "B", "patches": []},
        "capture_frame": 1,
        "action_checks": action_checks,
        "effect_requirement": "not_applicable",
        "effect_checks": [],
        "capture_checks": [{
            "check_id": case["case_id"] + "_capture",
            "plugin_id": "frame_luma_range",
            "params": {"min": 0, "max": 255},
            "required": True,
        }],
        "positive_source_dir": str(pos_dir),
        "negative_source_dir": str(neg_dir),
        "identity": {"name_zh": "测试要素"},
        "note": "离线合成夹具，不证明真实游戏机制。",
    }
    if aligned:
        element["reference_asset"] = str(root / "assets" / "negative_f0001.png")
    recipe_path = root / "promotion.json"
    _write_json(recipe_path, {
        "schema_version": DP.SCHEMA_VERSION,
        "kind": "visual_detector_promotion",
        "rom_sha1": rom_sha1,
        "source_report": str(report_path),
        "base_pack": str(base_pack),
        "bizhawk": str(root / "bizhawk"),
        "base_state": str(state),
        "output_pack": str(root / "out.showcase.json"),
        "output_report": str(root / "out.report.json"),
        "registry_path": str(registry_path),
        "verification": {"status": "synthetic_detector_verified"},
        "catalog": {
            "status": "complete",
            "expected_total": 1,
            "sources": [{
                "source_id": "synthetic_calibration",
                "status": "candidate",
                "verified_date": None,
                "evidence_report": str(report_path),
                "element_ids": [case["case_id"]],
            }],
        },
        "elements": [element],
    })
    return recipe_path, report_path


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _reject(name, fn):
    try:
        fn()
    except ValueError:
        check(name, True)
    except Exception as exc:
        check(name, False, f"异常类型错误: {type(exc).__name__}: {exc}")
    else:
        check(name, False, "应拒绝但通过")


def t_valid_color(root):
    recipe_path, _ = _fixture(root / "color")
    result = DP.promote(recipe_path)
    pack = _load(result["output_pack"])
    element = pack["elements"][0]
    check("P1 合法2.0报告可晋升并保留原始label/kind",
          result["status"] == "pass" and element["label"] == "Synthetic color" and element["kind"] == "skill"
          and bool(element["action_checks"]) and bool(element["capture_checks"])
          and pack["catalog"]["sources"][0]["status"] == "candidate"
          and result["elements"][0]["frame_verification"]["acceptance"]["verdict"] == "pass")
    check("P2 晋升不冒充玩法/语义/全时间轴/平台验收",
          all(result[key] is False for key in (
              "gameplay_verified", "semantic_identity_verified", "full_game_timeline_verified", "platform_verified")))
    check("P3 GBA平台闸门仍保持blocked",
          result["showcase_plan"]["status"] == "blocked"
          and result["showcase_plan"]["blockers"][0]["code"] == "unsupported_capability")


def t_valid_aligned(root):
    recipe_path, _ = _fixture(root / "aligned", aligned=True)
    result = DP.promote(recipe_path)
    element = _load(result["output_pack"])["elements"][0]
    reference = Path(element["detection"]["success_checks"][0]["params"]["reference_frame"])
    check("P4 对齐检测器冻结负例参考帧且正反例复验通过",
          result["status"] == "pass" and reference.is_file()
          and _sha256(reference) == element["detector_provenance"]["reference_asset_sha256"])
    _reject("P5 非overwrite重复晋升拒绝覆盖", lambda: DP.promote(recipe_path))
    result = DP.promote(recipe_path, overwrite=True)
    check("P6 overwrite仅复用同哈希参考帧并允许幂等重生成", result["status"] == "pass")


def t_rejections(root):
    recipe_path, report_path = _fixture(root / "legacy")
    report = _load(report_path)
    report["schema_version"] = "detector_calibration/1.0"
    _write_json(report_path, report)
    _reject("P7 旧1.0同集报告不得晋升", lambda: DP.promote(recipe_path))

    recipe_path, report_path = _fixture(root / "overlap")
    report = _load(report_path)
    report["cases"][0]["sample_isolation"]["source_partition"]["pos"]["overlap"] = [1]
    _write_json(report_path, report)
    _reject("P8 标定/验收源帧重叠不得晋升", lambda: DP.promote(recipe_path))

    recipe_path, report_path = _fixture(root / "fingerprint")
    report = _load(report_path)
    report["detector_impl_sha256"] = "0" * 64
    _write_json(report_path, report)
    _reject("P9 detect.py实现指纹漂移后必须重新标定", lambda: DP.promote(recipe_path))

    recipe_path, report_path = _fixture(root / "missing_reference", aligned=True)
    recipe = _load(recipe_path)
    recipe["elements"][0].pop("reference_asset")
    _write_json(recipe_path, recipe)
    _reject("P10 对齐检测器缺冻结参考帧资产时拒绝", lambda: DP.promote(recipe_path))

    recipe_path, report_path = _fixture(root / "frame_fail")
    report = _load(report_path)
    report["cases"][0]["detection"]["success_checks"][0]["params"]["rgb"] = [0, 255, 0]
    _write_json(report_path, report)
    _reject("P11 正式采集帧正反例复验失败不得写包", lambda: DP.promote(recipe_path))

    recipe_path, _ = _fixture(root / "missing_acceptance")
    recipe = _load(recipe_path)
    recipe["elements"][0].pop("capture_checks")
    _write_json(recipe_path, recipe)
    _reject("P12 缺拍摄验收声明不得晋升", lambda: DP.promote(recipe_path))

    recipe_path, _ = _fixture(root / "capture_fail")
    recipe = _load(recipe_path)
    recipe["elements"][0]["capture_checks"][0]["params"] = {"min": 250, "max": 255}
    _write_json(recipe_path, recipe)
    _reject("P13 拍摄验收失败不得写包", lambda: DP.promote(recipe_path))

    recipe_path, _ = _fixture(root / "late_capture_fail")
    recipe = _load(recipe_path)
    element = recipe["elements"][0]
    element["capture_checks"][0]["plugin_id"] = "frame_region_color_fraction"
    element["capture_checks"][0]["params"] = {
        "region": [0.0, 0.0, 1.0, 1.0], "rgb": [255, 0, 0],
        "tol": 4, "min_fraction": 0.05,
    }
    _write_json(recipe_path, recipe)
    Image.new("RGB", (96, 64), "black").save(Path(element["positive_source_dir"]) / "f0000.png")
    _reject("P14 主验收帧合格但其他正例帧拍摄失败不得晋升", lambda: DP.promote(recipe_path))

    recipe_path, _ = _fixture(root / "outside_capture_window")
    recipe = _load(recipe_path)
    element = recipe["elements"][0]
    element["capture_checks"][0]["plugin_id"] = "frame_region_color_fraction"
    element["capture_checks"][0]["params"] = {
        "region": [0.0, 0.0, 1.0, 1.0], "rgb": [255, 0, 0],
        "tol": 4, "min_fraction": 0.05,
    }
    _write_json(recipe_path, recipe)
    Image.new("RGB", (96, 64), "black").save(Path(element["positive_source_dir"]) / "f0002.png")
    result = DP.promote(recipe_path)
    check("P15 侦察目录中交付窗口之外的帧不参与拍摄晋升",
          result["status"] == "pass"
          and result["elements"][0]["frame_verification"]["acceptance"]["dimensions"]["capture"]["checked_frames"] == 2)

    recipe_path, _ = _fixture(root / "missing_capture_frame")
    (Path(_load(recipe_path)["elements"][0]["positive_source_dir"]) / "f0000.png").unlink()
    _reject("P16 正式采集窗口内缺帧不得晋升", lambda: DP.promote(recipe_path))


def t_source_rejections(root):
    recipe_path, _ = _fixture(root / "wild_source")
    recipe = _load(recipe_path)
    recipe["catalog"]["sources"][0]["source_id"] = "unregistered_calibration"
    _write_json(recipe_path, recipe)
    _reject("P17 未登记来源不得写入 showcase", lambda: DP.promote(recipe_path))

    recipe_path, _ = _fixture(root / "status_drift")
    recipe = _load(recipe_path)
    recipe["catalog"]["sources"][0].update({"status": "verified_read", "verified_date": "2026-11-25"})
    _write_json(recipe_path, recipe)
    _reject("P18 包来源状态与主数据不一致时拒绝", lambda: DP.promote(recipe_path))

    recipe_path, _ = _fixture(root / "unregistered_evidence")
    recipe = _load(recipe_path)
    recipe["catalog"]["sources"][0]["evidence_report"] = recipe["base_pack"]
    _write_json(recipe_path, recipe)
    _reject("P19 取证报告未登记到来源 evidence 时拒绝", lambda: DP.promote(recipe_path))

    recipe_path, _ = _fixture(root / "missing_coverage")
    recipe = _load(recipe_path)
    recipe["catalog"]["sources"][0]["element_ids"] = []
    _write_json(recipe_path, recipe)
    _reject("P20 要素缺来源支撑时不得写包", lambda: DP.promote(recipe_path))

    recipe_path, _ = _fixture(root / "calibration_promotion")
    recipe = _load(recipe_path)
    registry = _load(recipe["registry_path"])
    registry["sources"][0].update({"status": "verified_read", "last_verified": "2026-11-25"})
    _write_json(Path(recipe["registry_path"]), registry)
    recipe["catalog"]["sources"][0].update({"status": "verified_read", "verified_date": "2026-11-25"})
    _write_json(recipe_path, recipe)
    _reject("P21 检测器标定报告不得自升 verified_read", lambda: DP.promote(recipe_path))

    recipe_path, _ = _fixture(root / "verified_identity")
    recipe = _load(recipe_path)
    identity_report = Path(recipe["registry_path"]).parent / "identity.json"
    _write_json(identity_report, {"name_zh": "测试要素"})
    registry = _load(recipe["registry_path"])
    registry["sources"].append({
        "source_id": "synthetic_identity",
        "name": "合成身份来源",
        "kind": "local",
        "layer": "local_emu",
        "platforms": ["GBA"],
        "element_types": ["基础档案"],
        "status": "verified_read",
        "last_verified": "2026-11-25",
        "urls": [],
        "evidence": [str(identity_report)],
        "notes": "独立身份夹具。",
    })
    _write_json(Path(recipe["registry_path"]), registry)
    recipe["catalog"]["sources"].append({
        "source_id": "synthetic_identity",
        "status": "verified_read",
        "verified_date": "2026-11-25",
        "evidence_report": str(identity_report),
        "element_ids": [recipe["elements"][0]["element_id"]],
    })
    _write_json(recipe_path, recipe)
    result = DP.promote(recipe_path)
    sources = {row["source_id"]: row for row in _load(result["output_pack"])["catalog"]["sources"]}
    check("P22 独立 verified 来源按主数据保留不被降级",
          result["status"] == "pass"
          and sources["synthetic_identity"]["status"] == "verified_read"
          and sources["synthetic_calibration"]["status"] == "candidate")


def main():
    with tempfile.TemporaryDirectory(prefix="taspipe_promotion_selftest_") as td:
        root = Path(td)
        t_valid_color(root)
        t_valid_aligned(root)
        t_rejections(root)
        t_source_rejections(root)
    failed = [name for name, passed in RESULTS if not passed]
    print(f"DETECTOR PROMOTION SELFTEST {len(RESULTS) - len(failed)}/{len(RESULTS)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
