# -*- coding: utf-8 -*-
"""probe40: 在 wl 基版(256KB,非无限跳跃/群殴 gimmick)复核暂停秘技 A3B1A3B1A7 -> 得分框"必杀技OK"。
用法：python soccer2_wl_unlock.py
"""
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

ROM = Path(r"F:\taspipe_scratch\soccer2_wl\rom.nes")
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_wl_unlock")
BASE = Path(r"F:\taspipe_scratch\soccer2_wl\wl_field.state")
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
        for (wd, wt) in [(4, 6), (2, 2), (6, 8)]:
            tag = f"w{wd}t{wt}"
            s.load(pb)
            s.run(4)
            s.macro(UA.hold("Start", 4, 6))
            s.run(10)
            for btn in SEQ:
                s.macro(UA.hold(btn, wd, wt))
            s.run(12)
            stem = WORK / f"{tag}_coded"
            s.shot(str(stem))
            crop(Path(str(stem) + ".png"), Path(str(stem) + "_box.png"))
            s.macro(UA.hold("Start", 4, 6))
            s.run(6)
            print(tag, "done", flush=True)
    print("WL_UNLOCK_OK", flush=True)


if __name__ == "__main__":
    main()