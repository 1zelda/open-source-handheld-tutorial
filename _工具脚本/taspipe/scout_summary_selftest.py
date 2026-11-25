import json
import tempfile
from pathlib import Path

from . import scout_summary as SS

RESULTS = []


def check(condition, label):
    RESULTS.append((label, bool(condition)))


def frame(number, changed, passes):
    return {
        "frame": number,
        "changed_pixels": changed,
        "changed_fraction": changed / 38400,
        "equal": changed == 0,
        "pass": passes,
    }


def make_report(case_id, comparisons, evidence):
    return {
        "case_id": case_id,
        "status": "candidates_only",
        "cache_key": "synthetic",
        "evidence": [str(evidence)],
        "arms": {
            "yellow_10": {"steps": [{
                "index": 1,
                "captured_frames": 226,
                "expect": [{"pass": True}],
                "screen": {"pass": True},
                "actual_core": SS.GBA_MGBA_CORE_TYPE,
            }]},
            "yellow0": {"steps": [{
                "index": 1,
                "captured_frames": 226,
                "expect": [{"pass": True}],
                "screen": {"pass": True},
                "actual_core": SS.GBA_MGBA_CORE_TYPE,
                "ram": str(evidence),
                "shot": str(evidence),
            }]},
        },
        "candidate_comparisons": comparisons,
        "ram_diffs": [{"left": "yellow_10", "right": "yellow0", "changed_bytes": 2, "addresses": ["0x1325F", "0x1326E"]}],
    }


def main():
    with tempfile.TemporaryDirectory(prefix="scout_summary_selftest_") as td:
        root = Path(td)
        evidence = root / "evidence.bin"
        evidence.write_bytes(b"evidence")
        reports = {
            "all_pass": make_report("all_pass", [{"left": "yellow_10", "right": "yellow0", "relation": "different", "pass": True, "frames": [frame(120, 112, True), frame(164, 50, True)]}], evidence),
            "partial": make_report("partial", [{"left": "yellow_10", "right": "yellow0", "relation": "different", "pass": False, "frames": [frame(86, 0, False), frame(120, 112, True)]}], evidence),
            "equal_fail": make_report("equal_fail", [
                {"left": "yellow_10", "right": "yellow0", "relation": "equal", "pass": False, "frames": [frame(80, 1148, False)]},
                {"left": "yellow_10", "right": "yellow0", "relation": "different", "pass": True, "frames": [frame(120, 112, True)]},
            ], evidence),
            "no_visual": make_report("no_visual", [{"left": "yellow_10", "right": "yellow0", "relation": "different", "pass": False, "frames": [frame(120, 0, False), frame(164, 0, False)]}], evidence),
        }
        for case_id, report in reports.items():
            case_dir = root / "run" / case_id
            case_dir.mkdir(parents=True)
            (case_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
        recipe = root / "recipe.json"
        recipe.write_text(json.dumps({"cases": [{"id": case_id} for case_id in [*reports, "missing"]]}), encoding="utf-8")
        output = SS.build_summary(recipe, root / "run")
        check(output["total"] == 5 and output["counts"] == {"candidates_only": 4, "error": 1}, "S01 汇总覆盖全部预期case并逐格计数")
        check(output["classification_counts"] == {"visual_candidate": 1, "partial_visual_candidate": 2, "no_visual_change": 1, "error": 1}, "S02 全通过/部分视觉/无视觉分类逐格计数")
        check(output["partial_visual_candidate_count"] == 2, "S03 部分差异帧通过不会被压成纯RAM")
        check(output["equal_baseline_fail_count"] == 1, "S04 相等基线失败单独计数")
        check(output["ram_only_count"] == 1 and output["ram_plus_partial_visual_count"] == 2, "S05 纯RAM与RAM加部分视觉分开")
        check(output["visual_candidate_count"] == 1 and output["combined_candidate_count"] == 1, "S06 全比较通过仍保持原视觉候选口径")
        check(output["integrity_bad"] == [] and output["negative_inconsistent"] == [], "S07 完整证据与一致负例不误报")
        out = root / "summary.json"
        SS.write_summary(output, out)
        check(out.is_file() and out.with_suffix(".md").is_file(), "S08 汇总实际写出JSON与Markdown")
    failed = [label for label, ok in RESULTS if not ok]
    print(json.dumps({"status": "pass" if not failed else "failed", "checks": len(RESULTS), "failed": failed}, ensure_ascii=False))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
