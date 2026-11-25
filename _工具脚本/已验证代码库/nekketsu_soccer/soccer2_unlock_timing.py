# -*- coding: utf-8 -*-
"""probe37: 暂停秘技按压节奏扫 (width,wait)，抓得分框"必杀技OK"瞬态。用法：python soccer2_unlock_timing.py <jump|se>
"""
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

WHICH = sys.argv[1] if len(sys.argv) > 1 else "jump"
ROM = Path(r"F:\taspipe_scratch\netdisk_roms") / f"hack_{WHICH}.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_unlock") / WHICH
BASE = Path(r"F:\taspipe_scratch\soccer2_userroute") / WHICH / "received.state"
SEQ = ["A"] * 3 + ["B"] + ["A"] * 3 + ["B"] + ["A"] * 7


def crop(src, dst):
    from PIL import Image
    im = Image.open(src)
    w, h = im.size
    b = im.crop((int(w * 0.30), int(h * 0.76), int(w * 0.70), h))
    b = b.resize((b.width * 4, b.height * 4), Image.NEAREST)
    b.save(dst)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(str(ROM), BH, work=str(WORK)) as s:
        pb = s.use_state(str(BASE))
        for (wd, wt) in [(2, 2), (4, 4), (6, 8), (2, 6), (8, 4)]:
            tag = f"w{wd}t{wt}"
            s.load(pb)
            s.run(4)
            s.macro(UA.hold("Start", 4, 6))
            s.run(10)
            for btn in SEQ:
                s.macro(UA.hold(btn, wd, wt))
            for off in (2, 12, 30):
                s.run(off if off == 2 else off - (2 if off == 12 else 12))
                stem = WORK / f"{tag}_o{off:02d}"
                s.shot(str(stem))
                crop(Path(str(stem) + ".png"), Path(str(stem) + "_box.png"))
            s.macro(UA.hold("Start", 4, 6))
            s.run(6)
            print(tag, "done", flush=True)
    print("TIMING_OK", WHICH, flush=True)


if __name__ == "__main__":
    main()