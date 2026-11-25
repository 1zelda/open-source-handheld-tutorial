"""检测器候选矩阵：对 5 个包内武器值 + 空按基线，量出每个 (region, rgb, tol) 组合的
绝对颜色占比，选出自武器高、他武器低、空按最低的判据。数据来自本轮实测帧，不再跑模拟器。"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

HOLD = Path(r"F:/taspipe_scratch/sweep_AA_hold/sweep")
IDLE = Path(r"F:/taspipe_scratch/sweep_AA_idle/sweep/v00")
N = 30

TRIPLE = {
    "band_white":     ([0.234, 0.370, 0.570, 0.410], [248, 248, 248], 20),
    "band_warm":      ([0.234, 0.370, 0.570, 0.410], [248, 128, 112], 24),
    "arc_warm":       ([0.230, 0.300, 0.530, 0.480], [248, 128, 112], 24),
    "fan_warm":       ([0.230, 0.240, 0.580, 0.550], [248, 128, 112], 24),
    "far_warm":       ([0.450, 0.370, 0.700, 0.410], [248, 128, 112], 24),
    "far_white":      ([0.450, 0.370, 0.700, 0.410], [248, 248, 248], 20),
    "fan_white":      ([0.230, 0.240, 0.580, 0.550], [248, 248, 248], 20),
}
VALS = {"00": "Rifle", "11": "MG+R", "12": "Fireball+R", "13": "Spread+R", "14": "Laser+R"}


def sub(path, region, ):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.int32)
    h, w = a.shape[:2]
    x0, y0, x1, y1 = region
    return a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def frac(a, rgb, tol):
    return float((np.abs(a - np.asarray(rgb, dtype=np.int32)).max(axis=2) <= tol).mean())


matrix = {}
for tid, (region, rgb, tol) in TRIPLE.items():
    row = {}
    idle = [frac(sub(IDLE / f"f{i:04d}.png", region), rgb, tol) for i in range(N)]
    row["idle"] = {"max": round(max(idle), 5), "mean": round(float(np.mean(idle)), 5)}
    for v, name in VALS.items():
        fs = [frac(sub(HOLD / f"v{v}" / f"f{i:04d}.png", region), rgb, tol) for i in range(N)]
        row[name] = {"max": round(max(fs), 5), "min": round(min(fs), 5),
                     "mean": round(float(np.mean(fs)), 5),
                     "p25": round(float(np.percentile(fs, 25)), 5)}
    matrix[tid] = {"triple": {"region": region, "rgb": rgb, "tol": tol}, "stats": row}

Path(r"F:/taspipe_scratch/detector_matrix.json").write_text(
    json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")

for tid, d in matrix.items():
    r = d["stats"]
    line = " | ".join(f"{k} {v['mean']:.4f}/{v['max']:.4f}" for k, v in r.items())
    print(f"{tid:11s} {line}")
