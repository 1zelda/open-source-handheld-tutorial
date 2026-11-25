"""标定读数：找出各武器值与 0x00 的差异区域，裁同一块拼成对照图并标名字。"""
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")

ROOT = r"F:/taspipe_scratch/sweep_AA/sweep"
VALS = ["00", "01", "02", "03", "04", "05", "11", "12", "13"]
FRAME = 5

imgs = {v: np.array(Image.open(f"{ROOT}/v{v}/f{FRAME:04d}.png").convert("RGB")) for v in VALS}
base = imgs["00"]
ys, xs = [], []
for v in VALS[1:]:
    d = np.abs(imgs[v].astype(int) - base.astype(int)).sum(axis=2) > 24
    yy, xx = np.nonzero(d)
    if len(yy):
        ys += [yy.min(), yy.max()]
        xs += [xx.min(), xx.max()]
        print(f"v{v} 差异像素 {len(yy):5d}  bbox y{yy.min()}-{yy.max()} x{xx.min()}-{xx.max()}")
    else:
        print(f"v{v} 与 0x00 逐像素相同")
y0, y1 = max(0, min(ys) - 6), min(base.shape[0], max(ys) + 7)
x0, x1 = max(0, min(xs) - 6), min(base.shape[1], max(xs) + 7)
print(f"合并裁块 y{y0}-{y1} x{x0}-{x1}")

SCALE, PAD = 6, 18
tiles = []
for v in VALS:
    crop = Image.fromarray(imgs[v][y0:y1, x0:x1]).resize(((x1 - x0) * SCALE, (y1 - y0) * SCALE),
                                                          Image.NEAREST)
    t = Image.new("RGB", (crop.width, crop.height + PAD), (20, 20, 20))
    t.paste(crop, (0, PAD))
    ImageDraw.Draw(t).text((3, 3), f"0x{v}", fill=(255, 255, 255))
    tiles.append(t)
cols, rows = 3, 3
w = max(t.width for t in tiles) * cols
h = max(t.height for t in tiles) * rows
sheet = Image.new("RGB", (w, h), (0, 0, 0))
for i, t in enumerate(tiles):
    sheet.paste(t, ((i % cols) * max(tt.width for tt in tiles),
                    (i // cols) * max(tt.height for tt in tiles)))
sheet.save(r"F:/taspipe_scratch/weapon_sheet2.png")
print("saved", sheet.size)
