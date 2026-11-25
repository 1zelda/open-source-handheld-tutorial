"""连发下的同屏弹头数：步枪/机枪的分界就在这。对照 = 同值不开火。"""
from collections import deque

import numpy as np
from PIL import Image, ImageDraw

HOLD = r"F:/taspipe_scratch/sweep_AA_hold/sweep"
IDLE = r"F:/taspipe_scratch/sweep_AA_idle/sweep"
VALS = ["00", "01", "02", "03", "04", "05", "11", "12", "13", "14"]
BOX = (30, 60, 175, 118)
PLAYER_COLS = 22


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
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < H and 0 <= nx < W and m[ny, nx] and not seen[ny, nx]:
                                seen[ny, nx] = True
                                q.append((ny, nx))
                ys = [p[0] for p in pts]
                xs = [p[1] for p in pts]
                out.append((len(pts), min(ys), max(ys), min(xs), max(xs)))
    return [c for c in out if c[0] >= 4]


rows = []
for v in VALS:
    per = []
    peak = (0, None, None, None)
    for f in range(1, 30):
        a = np.array(Image.open(f"{HOLD}/v{v}/f{f:04d}.png").convert("RGB"))
        b = np.array(Image.open(f"{IDLE}/v{v}/f{f:04d}.png").convert("RGB"))
        m = np.abs(a.astype(int) - b.astype(int)).sum(axis=2) > 30
        m = m[BOX[1]:BOX[3], BOX[0]:BOX[2]]
        m[:, :PLAYER_COLS] = False
        cs = comps(m)
        per.append(len(cs))
        if peak[0] < len(cs):
            peak = (len(cs), f, cs, a)
    n, f, cs, a = peak
    cs = cs or []
    if a is None:                       # 全程没弹头（如 0x05）：拿第 1 帧照样出图，别中断整轮标定
        f = 1
        a = np.array(Image.open(f"{HOLD}/v{v}/f0001.png").convert("RGB"))
    ys = sorted((c[1] + c[2]) // 2 for c in cs)
    span = (ys[-1] - ys[0]) if len(ys) > 1 else 0
    print(f"0x{v}: 连发同屏弹头峰值 {n} 个 (帧 f{f:02d}) 纵向跨度 {span:2d}  "
          f"30 帧平均 {sum(per)/len(per):.1f}  逐帧 {per[:14]}")
    crop = Image.fromarray(a[BOX[1]:BOX[3], BOX[0] + PLAYER_COLS:BOX[2]])
    crop = crop.resize((crop.width * 6, crop.height * 6), Image.NEAREST)
    t = Image.new("RGB", (crop.width, crop.height + 18), (16, 16, 16))
    t.paste(crop, (0, 18))
    ImageDraw.Draw(t).text((4, 3), f"0x{v} f{f:02d}  同屏 {n} 发  跨度 {span}", fill=(255, 255, 0))
    rows.append(t)
for name, grp in (("A", rows[:5]), ("B", rows[5:10])):
    sheet = Image.new("RGB", (max(t.width for t in grp),
                              sum(t.height for t in grp) + 2 * len(grp)), (0, 0, 0))
    y = 0
    for t in grp:
        sheet.paste(t, (0, y))
        y += t.height + 2
    sheet.save(rf"F:/taspipe_scratch/weapon_hold_{name}.png")
    print("saved", name, sheet.size)
