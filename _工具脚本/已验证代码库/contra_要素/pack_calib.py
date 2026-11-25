"""按知识包原样的 trigger/negative 输入跑一遍逐帧截图，量候选检测器在
「开火帧 / 空按对照帧」上的颜色占比，把 region/rgb/tol/frame/min_fraction 定成实测数。"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import showcase as SC  # noqa: E402
from taspipe import statejump as SJ  # noqa: E402

PACK = Path(r"F:\开源掌机教程\_工具脚本\taspipe\游戏包\contra_weapons.showcase.json")
WORK = Path(r"F:/taspipe_scratch/pack_calib")
OUT = Path(r"F:/taspipe_scratch/pack_calib_frames")

doc = json.loads(PACK.read_text(encoding="utf-8"))
ROM, BH = doc["rom"], doc["bizhawk"]
BASE = Path(WORK / "base.state")
WORK.mkdir(parents=True, exist_ok=True)
import shutil  # noqa: E402
shutil.copyfile(doc["base_state"], BASE)  # 中文资产路径先落到 ASCII 工作目录（Lua io 坑）

REGIONS = {
    "muzzle":   [0.230, 0.372, 0.320, 0.408],
    "mid":      [0.320, 0.372, 0.550, 0.408],
    "far":      [0.450, 0.360, 0.720, 0.420],
    "upper":    [0.250, 0.280, 0.480, 0.372],
    "lower":    [0.250, 0.408, 0.480, 0.520],
    "fan_all":  [0.230, 0.240, 0.650, 0.560],
    "band_all": [0.230, 0.360, 0.720, 0.420],
}
COLORS = {"warm": ([254, 130, 112], 40), "white": ([254, 254, 254], 30)}


def fractions(frames_dir, total):
    """返回 {(region,color): [每帧占比]}"""
    imgs = [np.asarray(Image.open(Path(frames_dir) / f"f{i:04d}.png").convert("RGB"),
                      dtype=np.int32) for i in range(total)]
    h, w = imgs[0].shape[:2]
    res = {}
    for rn, rg in REGIONS.items():
        box = (int(rg[1] * h), int(rg[3] * h), int(rg[0] * w), int(rg[2] * w))
        for cn, (rgb, tol) in COLORS.items():
            v = []
            for a in imgs:
                sub = a[box[0]:box[1], box[2]:box[3]]
                v.append(float((np.abs(sub - np.asarray(rgb, dtype=np.int32)).max(axis=2)
                                <= tol).mean()))
            res[f"{rn}/{cn}"] = v
    return res


report = {}
with SJ.StateSession(ROM, BH, core=doc["core"], system=doc["system"], work=str(WORK)) as s:
    for el in doc["elements"]:
        trig, ctrl = el["trigger"], el["negative_control"]
        total = SC._macro_frames(trig["macro"], "NES") + int(trig.get("extra", 0))
        rows = {}
        for side, spec, patches, extra in (
                ("positive", trig["macro"], trig["patches"], int(trig.get("extra", 0))),
                ("negative", None, ctrl["patches"], total)):
            fd = OUT / el["element_id"] / side
            n = int(s.dump(str(fd), spec=spec or "-", extra=extra,
                           state=str(BASE), patches=patches))
            assert n == total, (n, total)
            rows[side] = fractions(fd, total)
        report[el["element_id"]] = rows

Path(r"F:/taspipe_scratch/pack_calib.json").write_text(
    json.dumps(report, ensure_ascii=False), encoding="utf-8")

print(f"{'element':18s} {'键':14s} {'空按max':>9s} {'开火mean':>9s} {'开火max':>9s}  峰值帧")
for eid, rows in report.items():
    for key in rows["positive"]:
        neg = max(rows["negative"][key])
        pos = rows["positive"][key]
        peak = int(np.argmax(pos))
        print(f"{eid:18s} {key:14s} {neg:9.4f} {float(np.mean(pos)):9.4f} "
              f"{max(pos):9.4f}  f{peak}")
    print()
