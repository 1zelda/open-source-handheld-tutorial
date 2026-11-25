"""武器标定读数：每个值给「不同帧数 / 弹头包围盒 / 弹头块数 / 主色」，把形状变成可比数字。"""
import hashlib
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(r"F:/taspipe_scratch/sweep_AA/sweep")
VALS = ["00", "01", "02", "03", "04", "05", "11", "12", "13", "14"]
BOX = (30, 60, 130, 110)          # 玩家前方一块，弹头都出现在这里
PLAYER = (30, 60, 52, 110)        # 玩家本体所在，算差异时排除


def load(v, f):
    return np.array(Image.open(ROOT / f"v{v}" / f"f{f:04d}.png").convert("RGB"))


for v in VALS:
    hashes = [hashlib.sha1((ROOT / f"v{v}" / f"f{i:04d}.png").read_bytes()).hexdigest()
              for i in range(30)]
    uniq = len(set(hashes))
    # 以 0x00 同帧为参照，统计弹头区差异
    best = (0, None)
    for f in range(2, 20):
        cur = load(v, f)[BOX[1]:BOX[3], BOX[0]:BOX[2]].astype(int)
        ref = load("00", f)[BOX[1]:BOX[3], BOX[0]:BOX[2]].astype(int)
        m = np.abs(cur - ref).sum(axis=2) > 30
        m[:, : PLAYER[2] - BOX[0]] = False        # 去掉玩家本体列
        n = int(m.sum())
        if n > best[0]:
            ys, xs = np.nonzero(m)
            best = (n, (f, ys.min(), ys.max(), xs.min() + BOX[0], xs.max() + BOX[0], cur.copy(), m.copy()))
    line = f"0x{v}: 30 帧里不同画面 {uniq:2d} 种"
    if best[1] is None:
        print(line, "与 0x00 无弹头差异（没打出东西）")
        continue
    f, y0, y1, x0, x1, cur, m = best[1]
    h, w = y1 - y0 + 1, x1 - x0 + 1
    # 连通块数 = 同屏弹头数（简单按行分段近似）
    cols = np.nonzero(m.any(axis=0))[0]
    gaps = np.nonzero(np.diff(cols) > 1)[0]
    blobs = len(gaps) + 1
    px = cur[m]
    rgb = px.mean(axis=0).astype(int)
    print(line + f" 峰值帧 f{f:02d} 差异 {int(m.sum()):4d}px 包围盒 {w}x{h} 分段 {blobs} 主色 rgb{tuple(rgb)}")
