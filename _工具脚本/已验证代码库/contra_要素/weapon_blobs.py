"""弹头拓扑：对差异掩码做 2D 连通块计数（列分段会把扇形弹压成一段），并裁出峰值帧大图。"""
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(r"F:/taspipe_scratch/sweep_AA/sweep")
VALS = ["00", "01", "02", "03", "04", "05", "11", "12", "13", "14"]
BOX = (30, 60, 140, 115)
PLAYER_COLS = 22          # 裁块左起 22 列是玩家本体，排除


def mask_diff(a, b):
    return np.abs(a.astype(int) - b.astype(int)).sum(axis=2) > 30


def components(m):
    seen = np.zeros_like(m, dtype=bool)
    boxes = []
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
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < H and 0 <= nx < W and m[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            q.append((ny, nx))
                ys = [p[0] for p in pts]
                xs = [p[1] for p in pts]
                boxes.append((len(pts), min(ys), max(ys), min(xs), max(xs)))
    return sorted(boxes, reverse=True)


tiles = []
for v in VALS:
    best = None
    for f in range(2, 22):
        cur = np.array(Image.open(ROOT / f"v{v}" / f"f{f:04d}.png").convert("RGB"))
        ref = np.array(Image.open(ROOT / "v00" / f"f{f:04d}.png").convert("RGB"))
        m = mask_diff(cur[BOX[1]:BOX[3], BOX[0]:BOX[2]], ref[BOX[1]:BOX[3], BOX[0]:BOX[2]])
        m[:, :PLAYER_COLS] = False
        comps = [c for c in components(m) if c[0] >= 4]      # 忽略 1-3 px 噪声
        score = sum(c[0] for c in comps)
        if best is None or score > best[0]:
            best = (score, f, comps, cur)
    score, f, comps, cur = best
    sizes = ",".join(f"{c[0]}px@y{c[1]}-{c[2]}x{c[3]}-{c[4]}" for c in comps[:5])
    print(f"0x{v}: 峰值帧 f{f:02d} 连通块 {len(comps)} 个  总差异 {score}px   {sizes}")
    crop = Image.fromarray(cur[BOX[1]:BOX[3], BOX[0] + PLAYER_COLS:BOX[2]])
    crop = crop.resize((crop.width * 8, crop.height * 8), Image.NEAREST)
    t = Image.new("RGB", (crop.width, crop.height + 18), (16, 16, 16))
    t.paste(crop, (0, 18))
    ImageDraw.Draw(t).text((4, 3), f"0x{v}  f{f:02d}  {len(comps)} blobs", fill=(255, 255, 0))
    tiles.append(t)

w = max(t.width for t in tiles)
h = sum(t.height for t in tiles) + 2 * len(tiles)
sheet = Image.new("RGB", (w, h), (0, 0, 0))
y = 0
for t in tiles:
    sheet.paste(t, (0, y))
    y += t.height + 2
sheet.save(r"F:/taspipe_scratch/weapon_blobs.png")
print("saved", sheet.size)
