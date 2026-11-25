# -*- coding: utf-8 -*-
"""哪个 .state 真在场上？逐个 load + 立刻截图 + 探针，不靠离线猜偏移。"""
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, r"F:\taspipe_scratch")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA
from soccer2_ramhunt import _probe

BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
OUT = Path(r"F:\taspipe_scratch\soccer2_statecheck")
CASES = [
    (r"F:\taspipe_scratch\soccer2_possess_cn\soccer2.nes",
     r"F:\taspipe_scratch\soccer2_possess_cn\kickoff.state", "jf_kickoff"),
    (r"F:\taspipe_scratch\soccer2_possess_cn\soccer2.nes",
     r"F:\taspipe_scratch\soccer2_possess_cn\possess_base.state", "jf_possess"),
    (r"F:\taspipe_scratch\netdisk_roms\hack_jump.nes",
     r"F:\taspipe_scratch\soccer2_hack\jump\hack_field.state", "hack_field"),
    (r"F:\taspipe_scratch\netdisk_roms\hack_jump.nes",
     r"F:\taspipe_scratch\soccer2_hack\jump\hack_possess.state", "hack_possess"),
]

for rom, st, tag in CASES:
    w = OUT / tag
    w.mkdir(parents=True, exist_ok=True)
    rp, sp = w / "ram.bin", w / "shot"      # shot() 自己补 .png，这里给无后缀名

    with SJ.StateSession(rom, BH, work=str(w)) as s:
        local = s.use_state(st)
        s.load(local)
        s.ramdump(str(rp))
        p0 = _probe(rp.read_bytes())
        s.shot(str(sp))
        s.macro(",".join([UA.hold("Right", 20), UA.hold("Down", 20)]))
        s.ramdump(str(rp))
        p1 = _probe(rp.read_bytes())
    print(f"{tag:12} 载入即探针={p0}")
    print(f"{'':12} 跑 40 帧后={p1}  (截图 {w / 'shot.png'})", flush=True)
