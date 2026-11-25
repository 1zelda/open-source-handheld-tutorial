# -*- coding: utf-8 -*-
"""mode 屏难度变量判别：←→ / Down 前后 RAM 逐字节 diff，找随 ←→ 变化的地址。
用法：python soccer2_diff_ram.py <jf|wl|jump|se>
"""
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

WHICH = sys.argv[1] if len(sys.argv) > 1 else "jf"
ROMS = {
    "jf": r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes",
    "wl": r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_wl.nes",
    "jump": r"F:\taspipe_scratch\netdisk_roms\hack_jump.nes",
    "se": r"F:\taspipe_scratch\netdisk_roms\hack_se.nes",
}
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_diff") / WHICH


def hold(btn, n, wait=0):
    return UA.hold(btn, n, wait)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(ROMS[WHICH], BH, work=str(WORK)) as s:
        def dump(tag):
            rp = WORK / f"{tag}.bin"
            s.ramdump(str(rp))
            return rp.read_bytes()

        s.run(1200)
        s.macro(hold("Start", 10))
        s.run(60)
        s.macro(hold("Start", 10))
        s.run(60)
        s.shot(str(WORK / "d0_mode"))
        a = dump("d0")
        s.run(20)
        a2 = dump("d0b")
        noise = {i for i in range(min(len(a), len(a2))) if a[i] != a2[i]}
        print("NOISE", len(noise), sorted(noise)[:40], flush=True)
        s.macro(hold("Right", 3, 20))
        s.run(20)
        s.shot(str(WORK / "d1_right"))
        b = dump("d1")
        s.macro(hold("Right", 3, 20))
        s.run(20)
        s.shot(str(WORK / "d2_right"))
        c = dump("d2")
        s.macro(hold("Left", 3, 20))
        s.run(20)
        s.shot(str(WORK / "d3_left"))
        d = dump("d3")
        s.macro(hold("Down", 3, 20))
        s.run(20)
        s.shot(str(WORK / "d4_down"))
        e = dump("d4")
        for name, x, y in (("R1", a, b), ("R2", b, c), ("L1", c, d), ("D1", d, e)):
            diffs = [(i, x[i], y[i]) for i in range(min(len(x), len(y)))
                     if x[i] != y[i] and i not in noise]
            print(name, "ndiff", len(diffs), diffs[:40], flush=True)
    print("DIFF_OK", WHICH, flush=True)


if __name__ == "__main__":
    main()