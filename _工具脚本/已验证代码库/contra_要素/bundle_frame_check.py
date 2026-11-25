# -*- coding: utf-8 -*-
"""抽 bundle 成片的 5 个事件帧，拼带标签对照条（人工看图复核，不只看数值闸门）。"""
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

B = Path(r"F:/开源掌机教程/04-游戏资源库/TAS输入录像库/交接包/contra_elements_d1")
OUT = Path(r"F:/taspipe_scratch/bundle_check")
OUT.mkdir(parents=True, exist_ok=True)
m = json.loads((B / "manifest.json").read_text(encoding="utf-8"))
reel = next(c for c in m["clips"] if c["clip_id"] == "reel_full")
reel_path = B / reel["path"]
den, num = reel["media_fps"]["den"], reel["media_fps"]["num"]
tiles = []
for e in m["events"]:
    w = e["reel_window"]
    af = w["event_frame"]
    png = OUT / f"ev_{af:04d}_{e['element_id']}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(reel_path),
                    "-vf", f"select=eq(n\\,{af})", "-frames:v", "1", str(png)], check=True)
    seconds = af * den / num
    tiles.append((png, f"{e['label']}  f={af}  {seconds:.2f}s  win {w['start_frame']}-{w['end_frame']}"))
    print(png.name, e["label"], "frame", af, f"{seconds:.3f}s")

imgs = [(Image.open(p).convert("RGB"), cap) for p, cap in tiles]
S = 3
tw, th = imgs[0][0].size
sw, sh = tw // S, th // S
HDR = 26
sheet = Image.new("RGB", (sw * len(imgs), sh + HDR), (18, 18, 22))
d = ImageDraw.Draw(sheet)
for i, (im, cap) in enumerate(imgs):
    sheet.paste(im.resize((sw, sh), Image.NEAREST), (i * sw, HDR))
    d.text((i * sw + 4, 7), cap[:46], fill=(235, 235, 235))
    d.rectangle([i * sw, HDR, i * sw + sw - 1, HDR + sh - 1], outline=(90, 90, 100))
sheet.save(OUT / "bundle_event_strip.png")
print("saved", OUT / "bundle_event_strip.png", sheet.size)
