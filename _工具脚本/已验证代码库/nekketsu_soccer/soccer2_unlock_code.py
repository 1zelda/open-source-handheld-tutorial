# -*- coding: utf-8 -*-
"""probe36: 正确复核暂停秘技 A3 B1 A3 B1 A7 -> 得分框"必杀技OK" -> 解锁全员必杀。
只验证解锁签名(得分框文字)，不触发必杀。用法：python soccer2_unlock_code.py <jump|se>
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


def crop_scorebox(src, dst):
    from PIL import Image
    im = Image.open(src)
    w, h = im.size
    box = im.crop((int(w * 0.30), int(h * 0.76), int(w * 0.70), h))
    box = box.resize((box.width * 4, box.height * 4), Image.NEAREST)
    box.save(dst)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(str(ROM), BH, work=str(WORK)) as s:
        pb = s.use_state(str(BASE))
        s.load(pb)
        s.run(4)
        s.shot(str(WORK / "before_full"))
        crop_scorebox(WORK / "before_full.png", WORK / "before_box.png")
        # pause
        s.macro(UA.hold("Start", 4, 6))
        s.run(10)
        # code while paused
        for btn in SEQ:
            s.macro(UA.hold(btn, 4, 6))
        s.run(20)
        s.shot(str(WORK / "coded_full"))
        crop_scorebox(WORK / "coded_full.png", WORK / "coded_box.png")
        # unpause
        s.macro(UA.hold("Start", 4, 6))
        s.run(10)
        s.shot(str(WORK / "unpaused_full"))
        crop_scorebox(WORK / "unpaused_full.png", WORK / "unpaused_box.png")
        s.save(str(WORK / "unlocked"))
    print("UNLOCK_PROBE_OK", WHICH, flush=True)


if __name__ == "__main__":
    main()