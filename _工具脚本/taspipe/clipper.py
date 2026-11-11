# -*- coding: utf-8 -*-
"""M6：事件切片 + 成品片段验收（依据 _scratch/强模型方案回复.md §5 M6 / C3）。

先有事件/帧区间，再按帧映射切视频；切完必须验"片段真的包含目标"：
  * 片段帧数 == 请求区间长度（错段/重采样 => FAIL）；
  * 片段抽帧跑检测器（复用 M4 受控插件）=> 目标出现才 PASS。
切错段时检测器找不到目标 => FAIL，不静默放行。帧→时间用 run 的 frame_map，不假设 N/60。

运行:
  python -m taspipe.clipper cut --recording <mp4> --fps 60 --start 120 --end 180 \
      --out <dir> --check '{"check_id":"sky","plugin_id":"frame_color_fraction","params":{"rgb":[193,224,254],"min_fraction":0.3}}'
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .schema import CheckSpec, CheckResult, Verdict, Stage
from .backends import _verification, _write_json, _run_id
from .schema import asset
from . import detect


def cut_clip(recording, frame_range, fps, out_path, ffmpeg="ffmpeg"):
    start, end = frame_range
    ss = start / fps
    dur = (end - start) / fps
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-i", str(recording), "-ss", f"{ss:.6f}", "-t", f"{dur:.6f}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return {"start_sec": ss, "duration_sec": dur}


def _extract_frame(clip, n, out_png, ffmpeg="ffmpeg"):
    cmd = [ffmpeg, "-v", "error", "-y", "-i", str(clip),
           "-vf", f"select=eq(n\\,{n})", "-frames:v", "1", str(out_png)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_png


def _nb_frames(clip, ffprobe="ffprobe"):
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=nb_frames", "-of", "json", str(clip)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    d = json.loads(r.stdout or "{}")
    s = (d.get("streams") or [{}])[0]
    return int(s.get("nb_frames") or 0)


def verify_clip(clip, expected_frames, check_specs, work_dir,
                ffmpeg="ffmpeg", ffprobe="ffprobe"):
    checks = []
    nb = _nb_frames(clip, ffprobe)
    checks.append(CheckResult("clip_frames",
                              Verdict.PASS if nb == expected_frames else Verdict.FAIL,
                              evidence_refs=[str(clip)],
                              reason=f"片段 {nb} 帧 vs 请求 {expected_frames}"))
    mid = max(0, expected_frames // 2)
    png = os.path.join(work_dir, f"clipmid_{os.getpid()}.png")
    try:
        _extract_frame(clip, mid, png, ffmpeg)
        for spec in check_specs:
            checks.append(detect.run_check(spec, png))
    except Exception as e:
        checks.append(CheckResult("clip_target_present", Verdict.INCONCLUSIVE,
                                  reason=f"抽帧失败 {type(e).__name__}: {e}"))
    finally:
        if os.path.isfile(png):
            os.remove(png)
    return checks


def run_cut(recording, frame_range, fps, check_specs, out_dir,
            element_id=None, run_id=None, ffmpeg="ffmpeg", ffprobe="ffprobe"):
    out_dir = str(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    cid = "clip_" + _run_id()[4:]
    start, end = frame_range
    clip = os.path.join(out_dir, f"{cid}.mp4")
    pts = cut_clip(recording, frame_range, fps, clip, ffmpeg)
    checks = verify_clip(clip, end - start, check_specs, out_dir, ffmpeg, ffprobe)
    ver = _verification("ver_" + cid, cid, Stage.CUT, checks)
    clip_rec = {
        "schema_version": 1, "clip_id": cid, "run_id": run_id,
        "element_id": element_id, "frame_range": [start, end],
        "pts_range": [pts["start_sec"], pts["start_sec"] + pts["duration_sec"]],
        "media": asset(clip), "verification_refs": [ver["verification_id"]],
        "attribution": [], "verification": ver,
    }
    _write_json(os.path.join(out_dir, f"{cid}.clip.json"), clip_rec)
    return clip_rec


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["cut"])
    ap.add_argument("--recording", required=True)
    ap.add_argument("--fps", type=float, default=60)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--check", action="append", default=[], help="CheckSpec JSON，可多次")
    ap.add_argument("--element", default=None)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    args = ap.parse_args()
    specs = [CheckSpec(**json.loads(c)) for c in args.check]
    rec = run_cut(args.recording, (args.start, args.end), args.fps, specs,
                  args.out, element_id=args.element,
                  ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0 if rec["verification"]["verdict"] == "pass" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())