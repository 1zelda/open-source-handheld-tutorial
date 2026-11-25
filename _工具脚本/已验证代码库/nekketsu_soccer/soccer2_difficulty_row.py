# -*- coding: utf-8 -*-
"""难度行可达性：Down 梯走到 简单/普通/困难 行，再 ←→ 看高亮与 RAM 变量。
用法：python soccer2_difficulty_row.py <jf|jump>
"""
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

WHICH = sys.argv[1] if len(sys.argv) > 1 else "jf"
ROMS = {
    "jf": r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes",
    "jump": r"F:\taspipe_scratch\netdisk_roms\hack_jump.nes",
}
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_diffrow") / WHICH


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
        s.shot(str(WORK / "m0"))
        prev = dump("m0")
        for k in range(1, 7):
            s.macro(hold("Down", 3, 20))
            s.run(20)
            s.shot(str(WORK / f"m{k}_down"))
            cur = dump(f"m{k}")
            d = [(i, prev[i], cur[i]) for i in range(min(len(prev), len(cur)))
                 if prev[i] != cur[i]]
            print(f"D{k} cursor93={cur[93]} ndiff={len(d)}", d[:16], flush=True)
            prev = cur
        # now presumably on difficulty row; exercise left/right
        for tag, btn in (("r1", "Right"), ("r2", "Right"), ("l1", "Left")):
            s.macro(hold(btn, 3, 20))
            s.run(20)
            s.shot(str(WORK / f"{tag}_{btn.lower()}"))
            cur = dump(tag)
            d = [(i, prev[i], cur[i]) for i in range(min(len(prev), len(cur)))
                 if prev[i] != cur[i]]
            print(f"{tag} cursor93={cur[93]} ndiff={len(d)}", d[:16], flush=True)
            prev = cur
    print("DIFFROW_OK", WHICH, flush=True)


if __name__ == "__main__":
    main()