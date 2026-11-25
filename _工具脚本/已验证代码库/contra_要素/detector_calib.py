"""按「按住 B vs 完全空按」逐帧差分，把弹头像素从玩家姿态变化里剥出来，
给 showcase 检测器提供实测的 region / rgb / tol / min_fraction。"""
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

HOLD = Path(r"F:/taspipe_scratch/sweep_AA_hold/sweep")
IDLE = Path(r"F:/taspipe_scratch/sweep_AA_idle/sweep")
NAMES = {"00": "Rifle", "01": "MachineGun", "02": "Fireball", "03": "Spread",
         "04": "Laser", "11": "MG+R", "12": "FB+R", "13": "SG+R", "14": "LS+R"}
W, H = 256, 224
PLAYER_X = 60          # 玩家本体所在列，差分里剔掉


def arr(d, v, f):
    return np.array(Image.open(d / f"v{v}" / f"f{f:04d}.png").convert("RGB")).astype(int)


out = {}
for v in sorted(NAMES):
    counts, boxes, cols = [], [], Counter()
    for f in range(30):
        cur, ref = arr(HOLD, v, f), arr(IDLE, "00", f)
        m = np.abs(cur - ref).sum(axis=2) > 60
        m[:, :PLAYER_X] = False                    # 只留玩家右侧
        n = int(m.sum())
        counts.append(n)
        if n >= 8:
            ys, xs = np.nonzero(m)
            boxes.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
            for px in cur[m][:: max(1, n // 40)]:
                cols[tuple(int(x) // 8 * 8 for x in px)] += 1
    out[v] = {
        "name": NAMES[v],
        "frames_with_bullets": sum(1 for c in counts if c >= 8),
        "avg_pixels": round(sum(counts) / 30, 1),
        "max_pixels": max(counts),
        "bbox_union": [min(b[0] for b in boxes), min(b[1] for b in boxes),
                       max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None,
        "bbox_union_norm": None,
        "top_colors": [list(c) + [n] for c, n in cols.most_common(6)],
    }
    if boxes:
        u = out[v]["bbox_union"]
        out[v]["bbox_union_norm"] = [round(u[0] / W, 3), round(u[1] / H, 3),
                                    round(u[2] / W, 3), round(u[3] / H, 3)]

Path(r"F:/taspipe_scratch/weapon_detector_calib.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
for v, d in out.items():
    print(f"{v} {d['name']:11s} 有弹帧 {d['frames_with_bullets']:2d}/30 "
          f"均像素 {d['avg_pixels']:6.1f} 峰值 {d['max_pixels']:5d} "
          f"框 {d['bbox_union_norm']} 主色 {d['top_colors'][:3]}")
