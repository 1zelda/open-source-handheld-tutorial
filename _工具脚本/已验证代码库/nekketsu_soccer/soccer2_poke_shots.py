# -*- coding: utf-8 -*-
"""给候选地址起名字：逐个 +0x40 写入并截图，看图就知道它是球/哪个人/镜头。

走生产会话（StateSession），每轮都从 field.state 重来 ⇒ 图与图之间只差这一处写入。
用法：python soccer2_poke_shots.py
产物：F:\\taspipe_scratch\\soccer2_practice\\shots\\<addr>.png + 证据副本
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, r"F:\taspipe_scratch")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA
from soccer2_ramhunt import _probe

BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
ROM = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes")
WORK = Path(r"F:\taspipe_scratch\soccer2_practice")
SHOTS = WORK / "shots"
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe45_practice\shots")
ADDRS = [0x0F0, 0x0F2, 0x059, 0x064, 0x314, 0x315, 0x316, 0x327, 0x328, 0x329,
         0x34D, 0x34E, 0x34F, 0x360, 0x386, 0x399, 0x42E, 0x430, 0x459, 0x45A, 0x4D6, 0x568]

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    SHOTS.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)
    rp = WORK / "shot_ram.bin"
    with SJ.StateSession(str(ROM), str(BH), work=str(WORK)) as s:
        st = s.use_state(str(WORK / "field.state"))
        s.load(st)
        s.run(12)
        s.ramdump(str(rp))
        base = _probe(rp.read_bytes())
        s.shot("base")
        shutil.copyfile(s._wpath("base", ".png"), EVID / "base.png")
        print(f"base 探针={base}", flush=True)
        for a in ADDRS:
            s.load(st)
            s.run(12)
            s.ramdump(str(rp))
            orig = rp.read_bytes()[a]
            s.write(a, (orig + 0x40) & 0xFF)
            s.run(6)
            s.ramdump(str(rp))
            p = _probe(rp.read_bytes())
            name = f"a{a:03X}"
            s.shot(name)
            src = s._wpath(name, ".png")
            shutil.copyfile(src, SHOTS / f"{name}.png")
            shutil.copyfile(src, EVID / f"{name}.png")
            db = (p["ball"][0] - base["ball"][0], p["ball"][1] - base["ball"][1]) \
                if p and "ball" in p and "ball" in base else None
            print(f"  ${a:04X} {orig:#04x}->{(orig + 0x40) & 0xFF:#04x} 球Δ={db} "
                  f"探针={p and (p.get('n_sprites'), p.get('n_groups'), p.get('left_x'), p.get('right_x'))}",
                  flush=True)
