"""弹头形状对照：裁玩家前方 x30-120 / y65-105，把每个武器值的连续 6 帧排成一行。"""
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
ROOT = r"F:/taspipe_scratch/sweep_AA/sweep"
VALS = ["00", "01", "02", "03", "04", "05", "11", "12", "13", "14"]
BOX = (30, 65, 120, 105)
FRAMES = range(3, 10)
SCALE, PAD = 5, 16

tiles = []
for v in VALS:
    row = Image.new("RGB", ((BOX[2] - BOX[0]) * SCALE * len(list(FRAMES)),
                            (BOX[3] - BOX[1]) * SCALE + PAD), (18, 18, 18))
    d = ImageDraw.Draw(row)
    d.text((3, 2), f"0x{v}", fill=(255, 255, 0))
    for i, f in enumerate(FRAMES):
        im = Image.open(f"{ROOT}/v{v}/f{f:04d}.png").convert("RGB").crop(BOX)
        im = im.resize((im.width * SCALE, im.height * SCALE), Image.NEAREST)
        row.paste(im, (i * im.width + 4, PAD))
    tiles.append(row)
w = max(t.width for t in tiles)
h = sum(t.height for t in tiles) + len(tiles) * 2
sheet = Image.new("RGB", (w, h), (0, 0, 0))
y = 0
for t in tiles:
    sheet.paste(t, (0, y))
    y += t.height + 2
sheet.save(r"F:/taspipe_scratch/weapon_bullets.png")
print("saved", sheet.size, "frames", list(FRAMES), "box", BOX)
