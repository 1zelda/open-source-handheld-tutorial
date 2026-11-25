# -*- coding: utf-8 -*-
"""probe41: 逐帧看静止双AB接球连段：AB挑->隔2f AB接跳->隔2f B，t=1..20 每帧抽，看"人球同在空中"是否成形。
用法：python soccer2_catch_fine.py <jump|se>
"""
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

WHICH = sys.argv[1] if len(sys.argv) > 1 else "jump"
ROM = Path(r"F:\taspipe_scratch\netdisk_roms") / f"hack_{WHICH}.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_catch") / WHICH
BASE = Path(r"F:\taspipe_scratch\soccer2_userroute") / WHICH / "received.state"


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    frames = []
    with SJ.StateSession(str(ROM), BH, work=str(WORK)) as s:
        pb = s.use_state(str(BASE))
        s.load(pb)
        s.macro(UA.hold("A+B", 6, 0))   # 1st AB toss
        s.run(2)
        s.macro(UA.hold("A+B", 6, 0))   # 2nd AB catch jump
        s.run(2)
        s.macro(UA.hold("B", 3, 0))     # then B
        for t in range(1, 21):
            s.run(1)
            stem = WORK / f"f{t:02d}"
            s.shot(str(stem))
            frames.append(Path(str(stem) + ".png"))
    w, h = Image.open(frames[0]).size
    cols = 5
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (w * cols, h * rows))
    for i, fp in enumerate(frames):
        sheet.paste(Image.open(fp), ((i % cols) * w, (i // cols) * h))
    sheet.save(WORK / "catch_fine.png")
    print("CATCH_FINE_OK", WHICH, flush=True)


if __name__ == "__main__":
    main()