# -*- coding: utf-8 -*-
"""用户空中连段假说：不跑动 第一次AB挑球→第二次AB接球→空中及时按B/AB。扫时序看必杀视觉。
用法：python soccer2_aerial_combo.py <jump|se>
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

WHICH = sys.argv[1] if len(sys.argv) > 1 else "jump"
ROM = Path(r"F:\taspipe_scratch\netdisk_roms") / f"hack_{WHICH}.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_aerial") / WHICH
BASE = Path(r"F:\taspipe_scratch\soccer2_userroute") / WHICH / "received.state"


def hold(btn, n, wait=0):
    return UA.hold(btn, n, wait)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    rows = []
    labels = []
    with SJ.StateSession(str(ROM), BH, work=str(WORK)) as s:
        pb = s.use_state(str(BASE))
        times = [6, 10, 14, 18, 24, 30]
        for d2 in (2, 4, 6):
            for d3 in (2, 4):
                for aerial in ("B", "A+B"):
                    tag = f"d{d2}_a{d3}_{aerial.replace('+','')}"
                    s.load(pb)
                    s.macro(hold("A+B", 6, 0))     # 1st AB: toss
                    s.run(d2)
                    s.macro(hold("A+B", 6, 0))     # 2nd AB: catch jump
                    s.run(d3)
                    s.macro(hold(aerial, 3, 0))    # aerial press
                    frames = []
                    prev = 0
                    for t in times:
                        s.run(t - prev); prev = t
                        stem = WORK / f"{tag}_t{t:02d}"
                        s.shot(str(stem))
                        frames.append(Path(str(stem) + ".png"))
                    rows.append(frames)
                    labels.append(tag)
                    print(tag, "done", flush=True)
    w, h = Image.open(rows[0][0]).size
    sheet = Image.new("RGB", (w * len(times), h * len(rows)))
    for r, row in enumerate(rows):
        for c, fp in enumerate(row):
            sheet.paste(Image.open(fp), (c * w, r * h))
    sheet.save(WORK / "aerial_sheet.png")
    (WORK / "labels.txt").write_text("\n".join(labels), encoding="utf-8")
    print("AERIAL_OK", WHICH, "rows", len(rows), flush=True)


if __name__ == "__main__":
    main()