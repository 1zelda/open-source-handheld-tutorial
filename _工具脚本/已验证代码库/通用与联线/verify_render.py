#!/usr/bin/env python3
"""gameplay.verify_render —— 成片"展示的是不是声明的那一段"逐像素闸门。

病根（2026-11-14）：渲染器 seek 钳制把短 reel 后半段的选段打回开头，S/L 两镜
展示成步枪窗；抽帧肉眼看小弹点又看不出差别，于是错片溜过验收。
对策：不靠肉眼、也不靠单一锚点相位（concat/淡入会让循环相位漂移，单点还会蹭到
无弹 idle 帧假匹配）。每个要素镜沿整镜时间轴扫 16 个相位，每相位与"声明源窗"
内所有帧逐像素比取最小；统计匹配相位占比。错窗镜在任何相位都对不上声明窗的
弹幕形态，占比塌到 0~0.12；正确镜 ≥0.88（2026-11-14 新旧片实测标定）。

只读产物（成片 mp4 + timeline + bundle），不改任何状态、不落临时文件。
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path

import numpy as np

from pipeline.gameplay import bundle_io

_FLAGS = 0x08000000 if sys.platform == "win32" else 0
# 标定（2026-11-14，16 相位）：正确镜每相位 ≤0.0015、占比 ≥0.88；
# 旧错片 spread 占比 0、laser 占比 0.125 → 阈 0.002 / 0.75 居中且留裕量。
_PHASE_MAX = 0.002
_FRAC_MIN = 0.75
_N_PHASE = 16


def _raw(cmd: list[str]) -> bytes:
    r = subprocess.run(cmd, capture_output=True, timeout=180, creationflags=_FLAGS)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {r.stderr.decode('utf-8', 'replace')[:300]}")
    return r.stdout


def _rgb2bgr(buf: bytes, w: int, h: int) -> np.ndarray:
    return np.frombuffer(buf, np.uint8).reshape(-1, h, w, 3)[..., ::-1]


def verify_render(run_dir: str | Path, bundle_dir: str | Path,
                  *, phase_max: float = _PHASE_MAX, frac_min: float = _FRAC_MIN,
                  beats: list | None = None) -> dict:
    run = Path(run_dir)
    bundle = bundle_io.load_bundle(bundle_dir)
    film = run / "video_beat.mp4"
    tl = json.loads((run / "video_beat_timeline.json").read_text(encoding="utf-8"))
    if beats is None:
        # 独立复核（runner 已收尾）才读 run_report；review 阶段该文件尚未落盘，须由调用方传 beats。
        rep = json.loads((run / "run_report.json").read_text(encoding="utf-8"))
        beats = rep["phases"]["compose"]["result"]["storyboard"]["beats"]
    starts = tl["starts"]
    reel = bundle_io.clip_by_id(bundle, "reel_full")
    pw, ph = reel.get("width", 1280), reel.get("height", 720)
    ps = max(1, min(1920 // pw, 1080 // ph))
    ox, oy = (1920 - pw * ps) // 2, (1080 - ph * ps) // 2
    crop = f"crop={pw * ps}:{ph * ps}:{ox}:{oy}"
    # 源 reel 一次解码进内存；RGB→BGR 与成片抽帧保持同通道序（曾因此红蓝互换假差异）。
    src = _rgb2bgr(_raw(["ffmpeg", "-v", "error", "-i", str(reel["_abs"]),
                         "-vf", "format=rgb24", "-f", "rawvideo", "-"]), pw, ph)
    if src.shape[0] == 0:
        raise RuntimeError("源 reel 解码为空，无法做展示窗闸门")
    H, W = ph, pw
    gx = int(W * 0.62)
    ya, yb = int(H * 0.33), int(H * 0.55)

    rows, bad = [], []
    for i, b in enumerate(beats):
        refs = b.get("fact_refs") or []
        ev = next((e for e in bundle.get("events", [])
                   if e.get("element_id") and any(r.startswith(e["element_id"]) for r in refs)), None)
        if ev is None or not b.get("loop"):
            continue
        rw = ev["reel_window"]
        s, en = int(rw["start_frame"]), int(rw["end_frame"])
        win = src[s:en, ya:yb, 0:gx].astype(np.int16)
        end = starts[i + 1] if i + 1 < len(starts) else starts[i] + float(b["duration"])
        vals = []
        for k in range(_N_PHASE):
            t = starts[i] + (end - starts[i]) * k / (_N_PHASE - 1)
            buf = b""
            for _try in range(3):
                buf = _raw(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(film),
                            "-vf", crop + ",format=rgb24", "-frames:v", "1",
                            "-f", "rawvideo", "-"])
                if buf:
                    break
            if not buf:
                # 抽不到帧按"对不上"计：闸门 fail-closed，不让瞬态空帧冒充通过。
                vals.append(1.0)
                continue
            frame = _rgb2bgr(buf, pw * ps, ph * ps)[0]
            if ps != 1:
                frame = frame[::ps, ::ps]
            ca = frame[ya:yb, 0:gx].astype(np.int16)
            d = np.abs(win - ca[None, :, :, :]).max(axis=3)
            vals.append(float((d > 24).mean(axis=(1, 2)).min()))
        frac = sum(v <= phase_max for v in vals) / len(vals)
        med = statistics.median(vals)
        ok = frac >= frac_min
        rows.append({"beat": i, "element": ev["element_id"], "frac": round(frac, 2),
                     "median": round(med, 4), "ok": ok})
        if not ok:
            bad.append(ev["element_id"])
    return {"ok": not bad, "rows": rows, "bad": bad,
            "phase_max": phase_max, "frac_min": frac_min}