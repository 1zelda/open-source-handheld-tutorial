# -*- coding: utf-8 -*-
"""bundle 时间映射的产物级反查（加强版）：合辑 (段起点+锚点) 帧 与 该要素独立段锚点帧 必须同一张图。

判据配三格：
  1) 对位格 —— sha256 必须相等（不是"差不多"）；
  2) 错帧格 —— 同段偏移 +20 帧，必须不等；
  3) 跨要素格 —— 拿别的武器的锚点帧来比，必须差得明显（证明这度量有分辨力，不是恒绿）。
"""
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

B = Path(r"F:/开源掌机教程/04-游戏资源库/TAS输入录像库/交接包/contra_elements_d1")
T = Path(r"F:/taspipe_scratch/bundle_check")
T.mkdir(parents=True, exist_ok=True)
m = json.loads((B / "manifest.json").read_text(encoding="utf-8"))
by_id = {c["clip_id"]: B / c["path"] for c in m["clips"]}
reel = by_id["reel_full"]


def frame(mp4, n, tag):
    out = T / f"{tag}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4),
                    "-vf", f"select=eq(n\\,{n})", "-frames:v", "1", str(out)], check=True)
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    return sha, np.asarray(Image.open(out).convert("RGB"), dtype=np.int16)


anchors = {e["element_id"]: frame(reel, e["reel_window"]["start_frame"] + e["anchor_frame"],
                                  f"reel_{e['element_id']}") for e in m["events"]}
print("格 1 对位（合辑 vs 独立段，同锚点）")
all_same = True
for e in m["events"]:
    a = e["anchor_frame"]
    sha_seg, _ = frame(by_id[e["clip_id"]], a, f"seg_{e['element_id']}")
    same = sha_seg == anchors[e["element_id"]][0]
    all_same &= same
    print(f"  {e['element_id']:<18} anchor={a:<3} {'一致' if same else '不一致 <-- 映射错'}")

print("格 2 错帧（同段 +20 帧，应当不等）")
for e in m["events"]:
    a = e["anchor_frame"]
    sha_off, _ = frame(by_id[e["clip_id"]], a + 20, "off")
    print(f"  {e['element_id']:<18} {'不等(对)' if sha_off != anchors[e['element_id']][0] else '相等(该帧纹丝不动,分辨力存疑)'}")

print("格 3 跨要素（只量画面区：两帧差异像素的并集框内平均差）")
ids = list(anchors)
diffs = []
for i in range(len(ids)):
    for j in range(i + 1, len(ids)):
        d = np.abs(anchors[ids[i]][1] - anchors[ids[j]][1]).max(axis=2)
        ys, xs = np.where(d > 8)                      # 游戏内容会变，边框/封面是死的
        if len(ys) == 0:
            diffs.append(0.0)
            continue
        box = d[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        diffs.append(float(box.mean()))
print("  内容区最小两两差 =", round(min(diffs), 3), " 平均 =", round(sum(diffs) / len(diffs), 3),
      "（整帧平均只有 1.4，因为封面底图占大半画面，那是度量假象）")
print("\n结论:", "映射逐帧对位成立" if all_same and min(diffs) > 2 else "不成立，别当已验证")
