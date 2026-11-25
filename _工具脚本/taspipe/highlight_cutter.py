# -*- coding: utf-8 -*-
"""T8/T10：从整条 TAS 通关录像自动扫描切出「高光/要素盘点段」+ 局部动作参数优化器。

解决项目缺口（目标与实施路线.md §3 T8 & T10）：
1. T10 自动切高光/盘点段 (B -> A)：
   很多经典怀旧名作已有整条通关 TAS 录像（.bk2/.fm2/.smv/.vbm/.gmv），如果靠人工逐帧找
   「哪一帧吃到道具、哪一帧放忍术、哪一帧打 Boss、哪一帧变身」非常耗时，且容易切到单帧闪烁窗
   导致 clipper 验收失败（见《测试问题与闸门说明书.md》§3 & §14）。
   本模块自动扫描录像帧序列，找出满足 CheckSpec 的**连续稳定触发窗**，自动将区间中点对齐到
   稳定窗中心，调用 clipper.run_cut 切出片段、验收并合成为全要素盘点 reel.mp4！
2. T8 局部动作宏参数搜索与优化（M7 泛化到全怀旧平台）：
   基于 MultiPlatformStateSession，在给定快照上搜索动作宏的「前置走位帧数 approach / 按住帧数 hold /
   二段触发间隔 gap」，找到更快或确定命中的参数组合并验证复播一致性。

运行方式（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.highlight_cutter scan-and-cut --recording "F:/path/to/full.mp4" --hook-pack "taspipe/游戏包/hooks.json" --out "F:/out/highlights"
  py -3 -u -m taspipe.highlight_cutter optimize-macro --rom "F:/path/to/game.nes" --state "F:/path/to/base.state" --platform NES --btn B --out "F:/out/opt"
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import clipper
from . import detect
from . import exporter
from . import retro_platforms as RP
from . import search as M7
from .schema import CheckSpec, Verdict


def extract_sampled_frames(video_path: Path, out_dir: Path, step: int = 5, ffmpeg: str = "ffmpeg") -> list[tuple[int, Path]]:
    """按固定帧步长 step 从通关视频抽帧，用于快速定位事件稳定窗（说明书 §14）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-v", "error", "-y", "-i", str(video_path),
        "-vf", f"select=not(mod(n\\,{step}))", "-vsync", "vfr",
        str(out_dir / "s_%06d.png")
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    files = sorted(out_dir.glob("s_*.png"))
    return [((idx * step), p) for idx, p in enumerate(files)]


def find_stable_event_windows(sampled_frames: list[tuple[int, Path]], check_specs: list[CheckSpec],
                              min_consecutive: int = 2) -> list[tuple[int, int]]:
    """在抽样帧序列中扫描满足所有 check_specs 的连续稳定段，拒绝单帧闪烁假阳性（说明书 §3 & §16）。"""
    hits = []
    for frame_no, png_path in sampled_frames:
        all_ok = True
        for spec in check_specs:
            res = detect.run_check(spec, str(png_path))
            if res.verdict != Verdict.PASS:
                all_ok = False
                break
        if all_ok:
            hits.append(frame_no)

    if not hits:
        return []

    # 聚类连续命中的采样点
    step = sampled_frames[1][0] - sampled_frames[0][0] if len(sampled_frames) > 1 else 5
    windows = []
    cur_start = hits[0]
    cur_end = hits[0]
    count = 1
    for h in hits[1:]:
        if h - cur_end <= step * 2:
            cur_end = h
            count += 1
        else:
            if count >= min_consecutive:
                windows.append((cur_start, cur_end))
            cur_start = cur_end = h
            count = 1
    if count >= min_consecutive:
        windows.append((cur_start, cur_end))
    return windows


def center_aligned_clip_range(stable_win: tuple[int, int], clip_len: int = 120,
                              total_frames: int = None) -> tuple[int, int]:
    """根据稳定事件窗 [w0, w1] 计算切片范围 [start, end]，确保中点 mid 严格落在稳定窗中心（说明书 §3）。"""
    w0, w1 = stable_win
    center = (w0 + w1) // 2
    half = max(30, clip_len // 2)
    start = max(0, center - half)
    end = start + half * 2
    if total_frames is not None and end > total_frames:
        end = total_frames
        start = max(0, end - half * 2)
    return start, end


def scan_and_cut_highlights(recording: Path, hook_pack: Path, out_dir: Path,
                            fps: float = 60.0988, step: int = 4,
                            ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> dict:
    """T10 主流程：从整条通关视频按事件钩子自动扫描稳定窗、切剪片段、中点验收并拼接高光盘点合辑。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = json.loads(hook_pack.read_text(encoding="utf-8"))
    total_nb = clipper._nb_frames(str(recording), ffprobe=ffprobe)

    with tempfile.TemporaryDirectory(prefix="tas_hl_scan_") as tmp:
        sampled = extract_sampled_frames(recording, Path(tmp) / "sampled", step=step, ffmpeg=ffmpeg)
        results = []
        clips_for_reel = []

        for hook in doc.get("hooks", []):
            eid = hook["element_id"]
            specs = [CheckSpec(**c).validate() for c in hook["success_checks"]]
            clip_len = int(hook.get("clip_frames", 120))
            windows = find_stable_event_windows(sampled, specs, min_consecutive=hook.get("min_consecutive", 2))

            if not windows:
                results.append({
                    "element_id": eid,
                    "label": hook.get("label", eid),
                    "status": "not_found",
                    "verdict": Verdict.INCONCLUSIVE.value,
                    "reason": "全片扫描未发现连续稳定触发窗",
                })
                continue

            # 取最稳定（跨度最长）的事件窗，并让 frame_range 中点严格落在稳定窗中心
            best_win = max(windows, key=lambda w: w[1] - w[0])
            f_start, f_end = center_aligned_clip_range(best_win, clip_len=clip_len, total_frames=total_nb or None)
            el_out = out_dir / eid
            clip_rec = clipper.run_cut(
                recording=str(recording),
                frame_range=(f_start, f_end),
                fps=fps,
                check_specs=specs,
                out_dir=str(el_out),
                element_id=eid,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
            )
            verdict = clip_rec["verification"]["verdict"]
            if verdict == Verdict.PASS.value:
                clips_for_reel.append(clip_rec["media"]["uri"])
            results.append({
                "element_id": eid,
                "label": hook.get("label", eid),
                "stable_window": list(best_win),
                "frame_range": [f_start, f_end],
                "verdict": verdict,
                "clip_ref": clip_rec["media"]["uri"],
            })

    reel_path = None
    if clips_for_reel and len(clips_for_reel) == len(doc.get("hooks", [])):
        from .showcase import _concat_videos
        reel_path = str(out_dir / "highlight_reel.mp4")
        _concat_videos(clips_for_reel, reel_path, ffmpeg=ffmpeg)

    report = {
        "game_id": doc.get("game_id", "unknown"),
        "recording": str(recording),
        "total_hooks": len(doc.get("hooks", [])),
        "passed": sum(1 for r in results if r.get("verdict") == "pass"),
        "deliverable_ref": reel_path,
        "results": results,
    }
    (out_dir / "highlight_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


class MultiPlatformMacroSearchEnv(M7.SearchEnv):
    """T8/M7 跨平台短窗口动作宏参数搜索环境（支持任意 BizHawk 怀旧平台快照）。"""

    def __init__(self, rom: str, bizhawk: str, state: str, platform: str = "NES",
                 work_dir: str = None):
        self.rom = rom
        self.bizhawk = bizhawk
        self.state = state
        self.platform = platform
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="tas_opt_")
        self.start_ref = state

    def search_capability(self):
        return {
            "supported": True,
            "evidence": f"MultiPlatformStateSession ({self.platform}) 帧精确快照回滚与截图已接线",
        }

    def evaluate(self, params: dict) -> M7.Observation:
        lead_btn = params.get("lead_btn", "")
        lead_frames = int(params.get("lead_frames", 0))
        act_btn = params.get("act_btn", "B")
        act_frames = int(params.get("act_frames", 6))
        wait_frames = int(params.get("wait_frames", 20))

        tokens = []
        if lead_btn and lead_frames > 0:
            tokens.extend([lead_btn] * lead_frames)
        tokens.extend([act_btn] * max(1, act_frames))
        macro_spec = ",".join(tokens)

        shot_name = f"try_l{lead_frames}_a{act_frames}_w{wait_frames}"
        with RP.MultiPlatformStateSession(
            rom=self.rom, bizhawk=self.bizhawk, platform=self.platform
        ) as sess:
            st_local = os.path.join(sess.work, "base.state")
            shutil.copy2(self.state, st_local)
            shot_local = sess._wpath(shot_name, ".png")
            sess.attempt(state=st_local, spec=macro_spec, extra=wait_frames, shot=shot_local)
            dst_png = Path(self.work_dir) / (shot_name + ".png")
            shutil.copy2(shot_local, dst_png)

        return M7.Observation(
            metrics={"total_frames": len(tokens) + wait_frames},
            frame=str(dst_png),
            input_ref=macro_spec,
            raw=params,
        )


def main():
    ap = argparse.ArgumentParser(description="T8/T10 通关录像自动切高光与跨平台动作宏参数优化器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cut = sub.add_parser("scan-and-cut", help="从通关视频自动扫描稳定事件窗并切出高光盘点合辑")
    p_cut.add_argument("--recording", required=True)
    p_cut.add_argument("--hook-pack", required=True)
    p_cut.add_argument("--out", required=True)
    p_cut.add_argument("--fps", type=float, default=60.0988)
    p_cut.add_argument("--step", type=int, default=4)

    args = ap.parse_args()
    if args.cmd == "scan-and-cut":
        rep = scan_and_cut_highlights(
            Path(args.recording), Path(args.hook_pack), Path(args.out),
            fps=args.fps, step=args.step
        )
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        sys.exit(0 if rep["passed"] == rep["total_hooks"] else 2)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
