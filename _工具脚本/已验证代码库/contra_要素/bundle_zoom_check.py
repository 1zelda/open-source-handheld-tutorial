# -*- coding: utf-8 -*-
"""把 bundle 的 5 个事件帧按知识包检测区裁出来放大，逐格看图（小图看不清弹形）。"""
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(r"F:/开源掌机教程")
B = ROOT / "04-游戏资源库/TAS输入录像库/交接包/contra_elements_d1"
RAW = Path(r"F:/taspipe_scratch/showcase_contra/clips")
T = Path(r"F:/taspipe_scratch/bundle_check")
pack = json.loads((ROOT / "_工具脚本/taspipe/游戏包/contra_weapons.showcase.json").read_text(encoding="utf-8"))
m = json.loads((B / "manifest.json").read_text(encoding="utf-8"))
by_id = {e["element_id"]: e for e in m["events"]}
pack_by_id = {e["element_id"]: e for e in pack["elements"]}

Z = 8
tiles = []
for eid, ev in by_id.items():
    a = ev["anchor_frame"]
    png = T / f"raw_{eid}_{a}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(RAW / f"{eid}.mp4"),
                    "-vf", f"select=eq(n\\,{a})", "-frames:v", "1", str(png)], check=True)
    im = Image.open(png).convert("RGB")
    W, H = im.size
    regs = [c["params"]["region"] for c in pack_by_id[eid]["detection"]["success_checks"]]
    x0 = min(int(r[0] * W) for r in regs) - 14
    y0 = min(int(r[1] * H) for r in regs) - 10
    x1 = max(int(r[2] * W) for r in regs) + 26
    y1 = max(int(r[3] * H) for r in regs) + 10
    crop = im.crop((max(0, x0), max(0, y0), min(W, x1), min(H, y1)))
    crop = crop.resize((crop.width * Z, crop.height * Z), Image.NEAREST)
    for r in regs:  # 把检测框画出来，确认判据圈的正是弹头出现的带
        dr = ImageDraw.Draw(crop)
        dr.rectangle([int((r[0] * W - x0) * Z), int((r[1] * H - y0) * Z),
                      int((r[2] * W - x0) * Z), int((r[3] * H - y0) * Z)],
                     outline=(0, 255, 0), width=2)
    tiles.append((crop, eid))
    print(eid, "anchor", a, "crop", crop.size)

HDR, GAP = 22, 6
w = max(c.width for c, _ in tiles)
h = max(c.height for c, _ in tiles)
sheet = Image.new("RGB", (w, (h + HDR + GAP) * len(tiles)), (16, 16, 20))
d = ImageDraw.Draw(sheet)
y = 0
for crop, eid in tiles:
    d.text((4, y + 5), f"{eid}  f={by_id[eid]['anchor_frame']}  绿框=知识包检测区", fill=(235, 235, 235))
    sheet.paste(crop, (0, y + HDR))
    y += h + HDR + GAP
sheet.save(T / "bundle_zoom_crops.png")
print("saved", T / "bundle_zoom_crops.png", sheet.size)
