# -*- coding: utf-8 -*-
"""视觉检测器标定、时间轴审计与配置入口离线自检。"""
import json
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from . import detect
from . import detector_calibration as DC
from . import universal_authoring as UA
from .schema import CheckSpec, Verdict

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition)))
    print(f"{'PASS' if condition else 'FAIL'} {name}" + (f" | {detail}" if detail and not condition else ""))


def _background(w=96, h=64, seed=0):
    image = np.zeros((h, w, 3), dtype=np.uint8)
    image[:32] = (18 + seed * 3, 24 + seed * 5, 32 + seed * 7)
    image[:32, :, 0] = np.arange(w, dtype=np.uint8) * 2
    image[:32, :, 1] = (np.arange(w, dtype=np.uint8) * 7 + seed * 11) % 180
    image[32:] = (8 + seed, 10 + seed * 2, 14 + seed * 3)
    return image


def _save(path, array):
    Image.fromarray(array.astype(np.uint8), "RGB").save(path)


def _aligned_series(root, effect=True, flash=False, seed=0):
    pos_dir, neg_dir = root / "aligned_pos", root / "aligned_neg"
    pos_dir.mkdir(parents=True)
    neg_dir.mkdir()
    base = _background(seed=seed)
    for index in range(4):
        _save(neg_dir / f"f{index:04d}.png", base)
        current = np.roll(base, 3, axis=1)
        if effect and index in (1, 2):
            current[40:52, 30:42] = (240, 70, 90)
        if flash and index == 3:
            current[:] = 255
        _save(pos_dir / f"f{index:04d}.png", current)
    return pos_dir, neg_dir


def _color_series(root, seed=0):
    pos_dir, neg_dir = root / "color_pos", root / "color_neg"
    pos_dir.mkdir(parents=True)
    neg_dir.mkdir()
    base = np.zeros((64, 96, 3), dtype=np.uint8)
    base[:] = (seed * 2, seed * 3, seed * 5)
    for index in range(4):
        _save(neg_dir / f"f{index:04d}.png", base)
        current = base.copy()
        if index in (1, 2):
            current[34:46, 42:54] = (49, 107, 255)
        _save(pos_dir / f"f{index:04d}.png", current)
    return pos_dir, neg_dir


def _aligned_case(pos_dir, neg_dir, case_id="aligned", accept_pos_dir=None, accept_neg_dir=None):
    accept_pos_dir = accept_pos_dir or pos_dir
    accept_neg_dir = accept_neg_dir or neg_dir
    return {
        "case_id": case_id,
        "method": "aligned_difference",
        "separation_method": "independent_capture",
        "calibration_sample_set_id": f"{case_id}_calibration",
        "acceptance_sample_set_id": f"{case_id}_acceptance",
        "calib_pos_dir": str(pos_dir),
        "calib_neg_dir": str(neg_dir),
        "accept_pos_dir": str(accept_pos_dir),
        "accept_neg_dir": str(accept_neg_dir),
        "primary_frame": 1,
        "region": [0.25, 0.5, 0.75, 1.0],
        "alignment_region": [0.0, 0.0, 1.0, 0.5],
        "frame_range": [1, 2],
        "max_shift": 4,
        "max_dy": 0,
        "max_global_changed_fraction": 0.25,
        "controls": [
            {"label": "attack", "side": "positive", "frame": 1, "reference_frame": 1, "expect": "pass"},
            {"label": "flash", "side": "positive", "frame": 3, "reference_frame": 3, "expect": "fail"},
            {"label": "empty", "side": "negative", "frame": 1, "reference_frame": 1, "expect": "fail"},
        ],
        "timeline": {
            "negative_all_fail": True,
            "expectations": [
                {"label": "attack", "side": "positive", "start": 1, "end": 2, "expect": "all_pass"},
                {"label": "flash", "side": "positive", "start": 3, "end": 3, "expect": "all_fail"},
            ],
        },
    }


def _color_case(pos_dir, neg_dir, case_id="color", accept_pos_dir=None, accept_neg_dir=None):
    accept_pos_dir = accept_pos_dir or pos_dir
    accept_neg_dir = accept_neg_dir or neg_dir
    return {
        "case_id": case_id,
        "method": "color_region",
        "separation_method": "independent_capture",
        "calibration_sample_set_id": f"{case_id}_calibration",
        "acceptance_sample_set_id": f"{case_id}_acceptance",
        "calib_pos_dir": str(pos_dir),
        "calib_neg_dir": str(neg_dir),
        "accept_pos_dir": str(accept_pos_dir),
        "accept_neg_dir": str(accept_neg_dir),
        "primary_frame": 1,
        "region": [0.4, 0.5, 0.6, 0.75],
        "frame_range": [1, 2],
        "controls": [
            {"label": "before", "side": "positive", "frame": 0, "expect": "fail"},
            {"label": "popup", "side": "positive", "frame": 1, "expect": "pass"},
            {"label": "empty", "side": "negative", "frame": 1, "expect": "fail"},
        ],
        "timeline": {
            "negative_all_fail": True,
            "expectations": [
                {"label": "before", "side": "positive", "start": 0, "end": 0, "expect": "all_fail"},
                {"label": "popup", "side": "positive", "start": 1, "end": 2, "expect": "all_pass"},
                {"label": "after", "side": "positive", "start": 3, "end": 3, "expect": "all_fail"},
            ],
        },
    }


def _capture_pair(root, label, pos_dir, neg_dir, process_id, force=True, acceptance=False):
    report_path = root / f"{label}_report.json"
    started = "2026-11-25T10:00:00+00:00"
    finished = "2026-11-25T10:01:00+00:00"
    report = {
        "schema_version": "ram_calibration/1.0",
        "mode": "verify" if acceptance else "scout",
        "game_id": "synthetic",
        "case_id": label,
        "rom_sha1": "00",
        "system": "NES",
        "core": "NesHawk",
        "status": "pass" if acceptance else "candidates_only",
        "base_state": {"name": "base", "path": str(root / "base.state")},
        "capture_provenance": {
            "run_id": label,
            "process_id": process_id,
            "started_at": started,
            "finished_at": finished,
            "force": force,
            "out_dir": str(root.resolve()),
            "implementation_sha256": "00",
        },
        "arms": {},
    }
    for side, directory in (("pos", pos_dir), ("neg", neg_dir)):
        report["arms"][side] = {"steps": [{
            "index": 0,
            "frames_dir": str(directory.resolve()),
            "captured_frames": 4,
            "attempt": {"ok": True},
        }]}
    report_path.write_text(json.dumps(report), encoding="utf-8")
    report_sha = DC._sha256(report_path)
    for side, directory in (("pos", pos_dir), ("neg", neg_dir)):
        manifest = {
            "schema_version": "detector_capture/1.0",
            "capture_id": f"{label}:{side}:0",
            "run_id": label,
            "process_id": process_id,
            "started_at": started,
            "finished_at": finished,
            "force": force,
            "source_report": str(report_path.resolve()),
            "source_report_sha256": report_sha,
            "source_report_status": report["status"],
            "game_id": "synthetic",
            "rom_sha1": "00",
            "system": "NES",
            "core": "NesHawk",
            "base_state": report["base_state"],
            "arm": side,
            "step_index": 0,
            "frames_dir": str(directory.resolve()),
            "captured_frames": 4,
            "frames": [{"destination_frame": index,
                        "sha256": DC._sha256(directory / f"f{index:04d}.png")}
                       for index in range(4)],
        }
        (directory / "capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def t_aligned(root):
    pos_dir, neg_dir = _aligned_series(root, effect=True, flash=True)
    calibration = UA.calibrate_aligned_element_detector(
        pos_dir, neg_dir, [0.25, 0.5, 0.75, 1.0],
        alignment_region=[0.0, 0.0, 1.0, 0.5], frame_range=[1, 2],
        max_shift=4, max_dy=0, max_global_changed_fraction=0.25,
    )
    check("D1 平移背景下的局部效果可标定", calibration["shift"] == [3, 0]
          and calibration["pos_fraction"] >= 0.05 and calibration["neg_fraction"] == 0.0,
          str(calibration))
    detection = DC.build_detection("aligned", calibration)
    params = detection["success_checks"][0]["params"]
    flash = detect.run_check(CheckSpec(**detection["success_checks"][0]), str(pos_dir / "f0003.png"))
    check("D2 全屏闪白被全局上限拒绝", flash.verdict == Verdict.FAIL and "global_fraction=1.0000" in flash.reason,
          flash.reason)
    audit = DC.audit_case(_aligned_case(pos_dir, neg_dir), detection)
    check("D3 全时间轴正例窗口与闪白反证均通过", audit["pass"]
          and audit["positive_counts"] == {"fail": 2, "pass": 2}
          and audit["negative_counts"] == {"fail": 4}, str(audit["counts"] if "counts" in audit else audit))

    camera_pos, camera_neg = _aligned_series(root / "camera", effect=False)
    metrics = detect.aligned_difference_metrics(
        detect._arr(camera_pos / "f0001.png"), detect._arr(camera_neg / "f0001.png"),
        [0.25, 0.5, 0.75, 1.0], [0.0, 0.0, 1.0, 0.5], max_shift=4,
    )
    check("D4 纯镜头平移对齐后不留下局部假签名", metrics["dx"] == 3
          and metrics["local_changed_fraction"] == 0.0, str(metrics))
    try:
        UA.calibrate_aligned_element_detector(
            camera_pos, camera_neg, [0.25, 0.5, 0.75, 1.0],
            alignment_region=[0.0, 0.0, 1.0, 0.5], max_shift=4,
        )
        rejected = False
    except RuntimeError:
        rejected = True
    check("D5 纯镜头平移不能标定出要素检测器", rejected)

    same_pos, same_neg = _aligned_series(root / "same", effect=True)
    for path in same_pos.glob("f*.png"):
        Image.open(path).save(same_neg / path.name)
    try:
        UA.calibrate_aligned_element_detector(
            same_pos, same_neg, [0.25, 0.5, 0.75, 1.0],
            alignment_region=[0.0, 0.0, 1.0, 0.5], max_shift=4,
        )
        rejected = False
    except RuntimeError:
        rejected = True
    check("D6 正反例完全相同必须拒绝标定", rejected)

    invalid = dict(params)
    invalid["region"] = [0.9, 0.1, 0.2, 0.8]
    result = detect.run_check(CheckSpec(**{**detection["success_checks"][0], "params": invalid}),
                              str(pos_dir / "f0001.png"))
    check("D7 非法区域返回 inconclusive 而不是通过", result.verdict == Verdict.INCONCLUSIVE,
          result.reason)


def t_color(root):
    pos_dir, neg_dir = _color_series(root)
    calibration = UA.calibrate_region_color_detector(
        pos_dir, neg_dir, [0.4, 0.5, 0.6, 0.75], frame_range=[1, 2],
    )
    check("D8 局部回血提示颜色可标定", calibration["rgb"] == [49, 107, 255]
          and calibration["pos_fraction"] > calibration["min_fraction"] > calibration["neg_fraction"],
          str(calibration))
    detection = DC.build_detection("color", calibration)
    audit = DC.audit_case(_color_case(pos_dir, neg_dir), detection)
    check("D9 颜色检测器全时间轴正反例验收通过", audit["pass"]
          and audit["positive_counts"] == {"fail": 2, "pass": 2}
          and audit["negative_counts"] == {"fail": 4}, str(audit))


def t_recipe(root):
    calib_pos, calib_neg = _color_series(root / "recipe" / "calibration", seed=1)
    accept_pos, accept_neg = _color_series(root / "recipe" / "acceptance", seed=2)
    _capture_pair(root, "calibration", calib_pos, calib_neg, process_id=101)
    _capture_pair(root, "acceptance", accept_pos, accept_neg, process_id=202, acceptance=True)
    case = _color_case(calib_pos, calib_neg, accept_pos_dir=accept_pos, accept_neg_dir=accept_neg)
    recipe = {"schema_version": DC.SCHEMA_VERSION, "game_id": "synthetic", "cases": [case]}
    recipe_path = root / "recipe.json"
    out_path = root / "out" / "report.json"
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
    report = DC.run_recipe(recipe_path, out_path)
    check("D10 分离样本配置入口真实写出 JSON/Markdown 且全帧审计通过", report["status"] == "pass"
          and out_path.is_file() and out_path.with_suffix(".md").is_file()
          and report["cases"][0]["timeline_audit"]["paired_frames"] == 4
          and report["calibration_acceptance_separated"] is True
          and report["cases"][0]["sample_isolation"]["independent_runs"]["calibration"]["pos"]["process_id"] == 101
          and report["cases"][0]["sample_isolation"]["independent_runs"]["acceptance"]["pos"]["process_id"] == 202,
          str(report["counts"]))
    check("D11 报告不冒充玩法、语义身份、平台或未采集时间轴验收",
          report["gameplay_verified"] is False and report["semantic_identity_verified"] is False
          and report["platform_verified"] is False and report["full_game_timeline_verified"] is False)
    check("D12 主验收帧来自验收集而非标定集",
          Path(report["cases"][0]["verification"]["primary"]["positive"]["frame"]).parent == accept_pos.resolve()
          and Path(report["cases"][0]["detection"]["success_checks"][0]["params"].get(
              "reference_frame", report["cases"][0]["verification"]["primary"]["positive"]["frame"]
          )).parent == accept_pos.resolve())

    bad = json.loads(json.dumps(recipe))
    bad["cases"][0]["controls"][0]["expect"] = "maybe"
    try:
        DC.validate_recipe(bad)
        rejected = False
    except ValueError:
        rejected = True
    check("D13 非法控制期望在加载期拒绝", rejected)

    bad = json.loads(json.dumps(recipe))
    bad["cases"][0]["timeline"]["expectations"][0]["end"] = 99
    try:
        DC.validate_recipe(bad)
        rejected = False
    except ValueError:
        rejected = True
    check("D14 越界时间窗在加载期拒绝", rejected)

    bad = json.loads(json.dumps(recipe))
    bad["cases"][0]["acceptance_sample_set_id"] = bad["cases"][0]["calibration_sample_set_id"]
    try:
        DC.validate_recipe(bad)
        rejected = False
    except ValueError:
        rejected = True
    check("D15 同一 sample_set_id 不能同时用于标定和验收", rejected)

    copied_pos = root / "copied_accept_pos"
    copied_neg = root / "copied_accept_neg"
    copied_pos.mkdir()
    copied_neg.mkdir()
    for source, target in ((calib_pos, copied_pos), (calib_neg, copied_neg)):
        for path in source.glob("f*.png"):
            Image.open(path).save(target / path.name)
    bad = json.loads(json.dumps(recipe))
    bad["cases"][0].update(accept_pos_dir=str(copied_pos), accept_neg_dir=str(copied_neg))
    try:
        DC.validate_recipe(bad)
        rejected = False
    except ValueError:
        rejected = True
    check("D16 复制标定帧目录不能冒充独立验收集", rejected)

    legacy = json.loads(json.dumps(recipe))
    legacy["schema_version"] = "detector_calibration/1.0"
    try:
        DC.validate_recipe(legacy)
        rejected = False
    except ValueError:
        rejected = True
    check("D17 旧同集标定验收配方不再产生通过报告", rejected)

    bad = json.loads(json.dumps(recipe))
    bad["cases"][0]["separation_method"] = "disjoint_frame_partition"
    try:
        DC.validate_recipe(bad)
        rejected = False
    except ValueError:
        rejected = True
    check("D18 帧分区配方必须提供来源映射", rejected)

    for directory in (calib_pos, calib_neg, accept_pos, accept_neg):
        rows = [{"destination_frame": index, "source_frame": index,
                 "sha256": DC._sha256(directory / f"f{index:04d}.png")}
                for index in range(4)]
        (directory / "source_mapping.json").write_text(json.dumps({
            "source_dir": "F:/synthetic/source", "frames": rows,
        }), encoding="utf-8")
    try:
        DC.validate_recipe(bad)
        rejected = False
    except ValueError:
        rejected = True
    check("D19 来源帧重叠的分区不能冒充不重叠验收", rejected)

    broken_calib_pos, broken_calib_neg = _aligned_series(root / "isolation" / "calibration", effect=True)
    for path in broken_calib_pos.glob("f*.png"):
        Image.open(path).save(broken_calib_neg / path.name)
    broken_accept_pos, broken_accept_neg = _aligned_series(root / "isolation" / "acceptance", effect=True, seed=1)
    _capture_pair(root / "isolation", "broken_calibration", broken_calib_pos, broken_calib_neg, process_id=303)
    _capture_pair(root / "isolation", "broken_acceptance", broken_accept_pos, broken_accept_neg,
                  process_id=404, acceptance=True)
    isolated = {
        "schema_version": DC.SCHEMA_VERSION,
        "game_id": "synthetic",
        "cases": [case, _aligned_case(
            broken_calib_pos, broken_calib_neg, "broken",
            accept_pos_dir=broken_accept_pos, accept_neg_dir=broken_accept_neg,
        )],
    }
    isolated_path = root / "isolation.json"
    isolated_out = root / "isolation_report.json"
    isolated_path.write_text(json.dumps(isolated), encoding="utf-8")
    isolated_report = DC.run_recipe(isolated_path, isolated_out)
    check("D20 单案例标定失败不中断其他案例且总报告失败",
          isolated_report["counts"] == {"pass": 1, "error": 1}
          and isolated_report["status"] == "failed", str(isolated_report["counts"]))

    manifest_path = accept_pos / "capture_manifest.json"
    original_manifest = manifest_path.read_bytes()
    manifest_path.unlink()
    try:
        DC.validate_recipe(recipe)
        rejected = False
    except ValueError:
        rejected = True
    finally:
        manifest_path.write_bytes(original_manifest)
    check("D21 independent_capture 缺运行清单时拒绝", rejected)

    _capture_pair(root, "calibration", calib_pos, calib_neg, process_id=202)
    try:
        DC.validate_recipe(recipe)
        rejected = False
    except ValueError:
        rejected = True
    finally:
        _capture_pair(root, "calibration", calib_pos, calib_neg, process_id=101)
    check("D22 标定与验收来自同一进程时拒绝", rejected)

    _capture_pair(root, "calibration", calib_pos, calib_neg, process_id=101, force=False)
    try:
        DC.validate_recipe(recipe)
        rejected = False
    except ValueError:
        rejected = True
    finally:
        _capture_pair(root, "calibration", calib_pos, calib_neg, process_id=101)
    check("D23 非 --force 的缓存运行不能充当独立采集", rejected)

    calibration_report = root / "calibration_report.json"
    original_report = calibration_report.read_bytes()
    calibration_report.write_bytes(original_report + b"\n")
    try:
        DC.validate_recipe(recipe)
        rejected = False
    except ValueError:
        rejected = True
    finally:
        calibration_report.write_bytes(original_report)
    check("D24 源报告漂移后 manifest 指纹失配并拒绝", rejected)

    frame_path = accept_pos / "f0001.png"
    original_frame = frame_path.read_bytes()
    Image.new("RGB", (96, 64), "black").save(frame_path)
    try:
        DC.validate_recipe(recipe)
        rejected = False
    except ValueError:
        rejected = True
    finally:
        frame_path.write_bytes(original_frame)
    check("D25 验收帧被替换后逐帧 SHA256 闸门拒绝", rejected)


def main():
    with tempfile.TemporaryDirectory(prefix="taspipe_detector_selftest_") as td:
        root = Path(td)
        t_aligned(root)
        t_color(root)
        t_recipe(root)
    failed = [name for name, passed in RESULTS if not passed]
    print(f"DETECTOR CALIBRATION SELFTEST {len(RESULTS) - len(failed)}/{len(RESULTS)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
