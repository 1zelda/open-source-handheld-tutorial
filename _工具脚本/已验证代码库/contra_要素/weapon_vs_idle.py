"""每把武器 vs 自己不开火的对照帧：弹头数量、纵向散布、横向长度 = 可直接命名的几何特征。"""
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

FIRED = Path(r"F:/taspipe_scratch/sweep_AA/sweep")
IDLE = Path(r"F:/taspipe_scratch/sweep_AA_idle/sweep")
VALS = ["00", "01", "02", "03", "04", "05", "11", "12", "13", "14"]
BOX = (30, 60, 170, 115)
PLAYER_COLS = 20


def comps(m):
    seen = np.zeros_like(m, dtype=bool)
    out = []
    H, W = m.shape
    for y in range(H):
        for x in range(W):
            if m[y, x] and not seen[y, x]:
                q = deque([(y, x)])
                seen[y, x] = True
                pts = []
                while q:
                    cy, cx = q.popleft()
                    pts.append((cy, cx))
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < H and 0 <= nx < W and m[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            q.append((ny, nx))
                ys = [p[0] for p in pts]
                xs = [p[1] for p in pts]
                out.append((len(pts), min(ys), max(ys), min(xs), max(xs)))
    return sorted([c for c in out if c[0] >= 4], reverse=True)


tiles = []
for v in VALS:
    best = None
    for f in range(1, 26):
        a = np.array(Image.open(FIRED / f"v{v}" / f"f{f:04d}.png").convert("RGB"))
        b = np.array(Image.open(IDLE / f"v{v}" / f"f{f:04d}.png").convert("RGB"))
        m = np.abs(a.astype(int) - b.astype(int)).sum(axis=2) > 30
        m = m[BOX[1]:BOX[3], BOX[0]:BOX[2]]
        m[:, :PLAYER_COLS] = False
        cs = comps(m)
        score = sum(c[0] for c in cs)
        if best is None or score > best[0]:
            best = (score, f, cs, a, m)
    score, f, cs, a, m = best
    ys = [c[1] for c in cs] + [c[2] for c in cs]
    span = (max(ys) - min(ys)) if cs else 0
    xmax = max((c[4] for c in cs), default=0)
    kind = ("无弹头" if not cs else
            "长条(横向>=20px 且纵向<=6px)=光束" if any(c[4] - c[3] >= 20 and c[2] - c[1] <= 6 for c in cs) else
            "多路纵向散布(>=3 块且纵向跨度>=14)=散弹" if len(cs) >= 3 and span >= 14 else
            "单发直线" if len(cs) == 1 else f"{len(cs)} 块 纵向跨度 {span}")
    print(f"0x{v}: 峰值帧 f{f:02d} 弹头块 {len(cs):2d} 纵向跨度 {span:2d} 最远 x+{xmax:3d}  => {kind}")
    crop = Image.fromarray(a[BOX[1]:BOX[3], BOX[0] + PLAYER_COLS:BOX[2]])
    crop = crop.resize((crop.width * 6, crop.height * 6), Image.NEAREST)
    t = Image.new("RGB", (crop.width, crop.height + 18), (16, 16, 16))
    t.paste(crop, (0, 18))
    ImageDraw.Draw(t).text((4, 3), f"0x{v} f{f:02d}  {len(cs)} blobs  vs 同值不开火",
                           fill=(255, 255, 0))
    tiles.append(t)
w = max(t.width for t in tiles)
half = len(tiles) // 2
for name, grp in (("A", tiles[:half]), ("B", tiles[half:])):
    sheet = Image.new("RGB", (w, sum(t.height for t in grp) + 2 * len(grp)), (0, 0, 0))
    y = 0
    for t in grp:
        sheet.paste(t, (0, y))
        y += t.height + 2
    sheet.save(rf"F:/taspipe_scratch/weapon_vs_idle_{name}.png")
    print("saved", name, sheet.size)
