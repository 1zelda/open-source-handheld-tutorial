"""五区域 × 白/暖色 在 10 段实测 clip 上的逐帧分布，作为手写互斥判据的依据。"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(r"F:/taspipe_scratch/pack_calib_frames")
ELS = ["default_rifle", "machine_gun_m", "fire_thrower_f", "spread_gun_s", "laser_gun_l"]
COLORS = {"white": ([254, 254, 254], 30), "warm": ([254, 130, 112], 40)}
REG = {"muzzle": [0.23, 0.375, 0.42, 0.42],
       "mid":    [0.42, 0.375, 0.58, 0.42],
       "far":    [0.58, 0.375, 0.72, 0.42],
       "upper":  [0.28, 0.26, 0.46, 0.375],
       "lower":  [0.28, 0.42, 0.46, 0.52]}

data = {}
for e in ELS:
    for side in ("positive", "negative"):
        paths = sorted((OUT / e / side).glob("f*.png"))
        imgs = np.asarray([np.asarray(Image.open(p).convert("RGB"), dtype=np.int16)
                           for p in paths])
        h, w = imgs.shape[1:3]
        d = {}
        for rn, rg in REG.items():
            sub = imgs[:, int(rg[1] * h):int(rg[3] * h), int(rg[0] * w):int(rg[2] * w)]
            for cn, (rgb, tol) in COLORS.items():
                d[f"{rn}/{cn}"] = ((np.abs(sub - np.asarray(rgb, dtype=np.int32))
                                    .max(axis=3) <= tol).mean(axis=(1, 2)))
        data[f"{e}/{side}"] = d

Path(r"F:/taspipe_scratch/detector_dist.json").write_text(
    json.dumps({k: {kk: [round(float(x), 5) for x in vv] for kk, vv in d.items()}
                for k, d in data.items()}), encoding="utf-8")

print(f"{'clip':30s} " + " ".join(f"{k:>13s}" for k in REG) + "   (暖色: 峰值 | 帧分布 p50/p90)")
for key, d in data.items():
    parts = []
    for rn in REG:
        warm, white = d[f"{rn}/warm"], d[f"{rn}/white"]
        parts.append(f"{warm.max():.4f}|{np.median(warm):.4f}/{np.percentile(warm, 90):.4f}")
    print(f"{key:30s} " + " ".join(f"{p:>26s}" for p in parts))
print()
print("白/暖 比值（步枪=inf）")
for key, d in data.items():
    if "negative" in key:
        continue
    row = []
    for rn in REG:
        w, wa = d[f"{rn}/white"].max(), d[f"{rn}/warm"].max()
        row.append(f"{rn}:{'inf' if wa == 0 else round(w / wa, 2)}")
    print(f"{key:30s} " + "  ".join(row))
