"""用真实（未量化）调色板量每个武器的弹头颜色，供检测器取 rgb/tol。"""
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

HOLD = Path(r"F:/taspipe_scratch/sweep_AA_hold/sweep")
IDLE = Path(r"F:/taspipe_scratch/sweep_AA_idle/sweep/v00")
VALS = {"00": "Rifle", "11": "MG+R", "12": "Fireball+R", "13": "Spread+R", "14": "Laser+R"}
X0 = 60  # 玩家右侧

for v, name in VALS.items():
    cols, rows = Counter(), []
    for i in range(30):
        cur = np.asarray(Image.open(HOLD / f"v{v}" / f"f{i:04d}.png").convert("RGB"), dtype=int)
        ref = np.asarray(Image.open(IDLE / f"f{i:04d}.png").convert("RGB"), dtype=int)
        m = np.abs(cur - ref).max(axis=2) > 24
        m[:, :X0] = False
        if m.sum() < 8:
            continue
        px = cur[m]
        cols.update(map(tuple, px))
        ys, xs = np.nonzero(m)
        rows.append((i, int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()), int(m.sum())))
    top = cols.most_common(8)
    print(f"\n== {v} {name}  命中帧 {len(rows)}/30 ==")
    print("  主色:", [f"#{r:03d},{g:03d},{b:03d}x{n}" for (r, g, b), n in top])
    for r in rows[:6]:
        print(f"  f{r[0]:02d} x {r[1]}-{r[2]} y {r[3]}-{r[4]} n={r[5]}"
              f"  归一 [{r[1]/256:.3f},{r[3]/224:.3f},{r[2]/256:.3f},{r[4]/224:.3f}]")
