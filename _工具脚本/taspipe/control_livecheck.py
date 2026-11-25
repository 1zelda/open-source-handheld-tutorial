"""Explicit real-emulator acceptance through the production control entry point."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import io
import json
import zipfile
from pathlib import Path
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taspipe import control
from taspipe import movie_converters as MC
from taspipe.schema import sha256_file
from taspipe.statejump import compare_state_core
from PIL import Image

PACKS = Path(__file__).resolve().parent / "游戏包"


def source_snapshot(doc, base):
    normalized, _ = control.normalize(doc, base)
    paths = {Path(p) for p in control._inputs(normalized)}
    emulator = Path(normalized["profile"]["bizhawk"])
    paths.update(p for p in emulator.rglob("*") if p.is_file() and
                 (p.suffix.lower() in (".exe", ".dll") or p.name == "config.ini"))
    return {str(p): {"sha256": sha256_file(p), "bytes": p.stat().st_size} for p in sorted(paths)}


def pixels(path):
    return hashlib.sha256(subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        check=True, capture_output=True, timeout=30).stdout).hexdigest()


def decode_framebuffer(data, bizhawk=None):
    if data.startswith(MC.ZSTD_FRAME_MAGIC):
        data = MC._zstd_decompress(data, bizhawk)
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGBA")


def run_case(case, out):
    source = "contra_control.control.json" if case in ("contra", "assert_fail") else (
        "donkeykong_full.control.json" if case == "movie_end" else "nova_full.control.json")
    doc, base = control.load_spec(PACKS / source)
    doc = deepcopy(doc)
    doc["id"] = "live_" + case
    if case == "assert_fail":
        doc["steps"] = [
            {"id": "bad", "op": "assert", "checks": [
                {"id": "impossible", "domain": "RAM", "addr": "0xAA", "cmp": "eq", "value": 255}]},
            {"id": "must_not_run", "op": "advance", "frames": 1}]
        doc["record"]["video"] = False
    if case == "movie_takeover":
        doc["purpose"] = "control"
        doc["steps"] = [
            {"id": "prefix", "op": "replay", "frames": 180},
            {"id": "before", "op": "checkpoint", "name": "before"},
            {"id": "own", "op": "takeover"},
            {"id": "right", "op": "input", "segments": [{"frames": 12, "players": {"1": ["Right"]}}]}]
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    before = source_snapshot(doc, base)
    control.write_json(out / "inputs_before.json", before)
    control.write_json(out / "recipe.json", doc)
    checks = []

    def check(name, passed, detail=None):
        checks.append({"name": name, "status": "pass" if passed else "fail", "detail": detail})

    result = control.run(doc, base, out / "run", timeout=300)
    runtime = result.get("runtime", {})
    negative = case == "assert_fail"
    check("execution", runtime.get("execution") == ("fail" if negative else "pass"), result.get("reason"))
    check("completion_not_invented", result["verification"]["completion"] == "inconclusive")
    check("sync_not_invented", result["verification"]["sync"] == "unverified")
    if negative:
        check("expected_assertion_failure", "assertion failed" in runtime.get("reason", ""))
        check("no_step_after_failure", not any(e.get("step_id") == "must_not_run" for e in runtime.get("events", [])))
        check("no_advance_on_failure", runtime.get("frames_advanced") == 0)
    elif runtime.get("execution") == "pass":
        if case == "contra":
            cps = runtime["checkpoints"]
            cmp = compare_state_core(cps["shot_a"]["state"], cps["shot_b"]["state"])
            check("branch_core_match", cmp["match"] and cmp["core_identity_match"], cmp)
            ha, hb = pixels(cps["shot_a"]["screenshot"]), pixels(cps["shot_b"]["screenshot"])
            check("branch_pixels_match", ha == hb, {"a": ha, "b": hb})
            ram_a, ram_b = Path(cps["shot_a"]["ram"]["path"]), Path(cps["shot_b"]["ram"]["path"])
            check("branch_ram_match", ram_a.read_bytes() == ram_b.read_bytes())
            check("exact_explicit_advances", runtime["frames_advanced"] == 48, runtime["frames_advanced"])
            states = runtime.get("state_checks", [])
            check("state_admission", len(states) == 3 and all(s["admitted"] for s in states), states)
            check("video_count", runtime.get("video", {}).get("frames") == 48, runtime.get("video"))
            from PIL import Image
            frame_pairs = {name: (cp["state"], cp["screenshot"]) for name, cp in cps.items()}
            runtime_dir = Path(result["attempt_dir"]) / "runtime"
            frame_pairs["final"] = (runtime_dir / "final.state", runtime_dir / "final.png")
            for name, (state, shot) in frame_pairs.items():
                with zipfile.ZipFile(state) as z:
                    fb = decode_framebuffer(z.read("Framebuffer.bmp"), doc["profile"]["bizhawk"])
                png = Image.open(shot).convert("RGBA")
                check("state_screenshot_alignment_" + name, fb.size == png.size and fb.tobytes() == png.tobytes())
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", runtime["video"]["path"],
                            "-vf", "select=eq(n\\,47)", "-frames:v", "1", str(out / "video_last.png")],
                           check=True, capture_output=True, timeout=30)
        else:
            movie = runtime.get("movie", {})
            check("movie_consumption", movie.get("consumed_inputs") == (180 if case == "movie_takeover" else movie.get("expected_inputs")), movie)
            check("actual_advances", runtime.get("frames_advanced") == (192 if case == "movie_takeover" else movie.get("expected_inputs")))
            if case == "movie_end":
                check("full_playback_not_win_claim", result["status"] == "inconclusive")
        files = {r["uri"]: (Path(r["uri"]).stat().st_mtime_ns, sha256_file(r["uri"])) for r in result["artifacts"]}
        again = control.run(doc, base, out / "run", timeout=300)
        check("cache_reused", again.get("reused") is True and again["attempt_dir"] == result["attempt_dir"])
        check("cache_artifacts_unchanged", all((Path(p).stat().st_mtime_ns, sha256_file(p)) == v for p, v in files.items()))
    after = source_snapshot(doc, base)
    check("all_source_bytes_unchanged", before == after, {"files_checked": len(before)})
    report = {"case": case, "checks": checks, "counts": dict(Counter(c["status"] for c in checks)),
              "source_before": before, "source_after": after, "control_manifest": str(out / "run" / "control.json")}
    control.write_json(out / "acceptance.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=["contra", "movie_takeover", "movie_end", "assert_fail"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = run_case(args.case, args.out)
    print(json.dumps({"case": report["case"], "counts": report["counts"], "checks": report["checks"]}, ensure_ascii=False, indent=2))
    return 0 if not report["counts"].get("fail") else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
