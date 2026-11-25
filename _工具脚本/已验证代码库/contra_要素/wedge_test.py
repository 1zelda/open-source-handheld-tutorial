"""0x00AA=5 到底是「武器」还是「卡死」：写值后看帧号/RAM/画面还动不动。"""
import hashlib
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\contra_u.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
BASE = "F:/taspipe_scratch/sweep_AA/sweep/base.state"
W = Path("F:/taspipe_scratch/wedge_test2")

s = SJ.StateSession(rom=ROM, bizhawk=BH, work=str(W))
s.start()
st = s.use_state(BASE)
for val in (0, 5, 4):
    s.attempt(st, spec="-", extra=0, shot=str(W / f"v{val}_start.png"))
    s.write(0xAA, val)
    r0 = s.ramdump(str(W / f"v{val}_ram0.bin"), 2048)
    fc0 = s.ping()[0]
    run = s.run(120)
    fc1 = s.ping()[0]
    s.ramdump(str(W / f"v{val}_ram1.bin"), 2048)
    s.attempt(st, spec="-", extra=0, shot=str(W / f"v{val}_x.png"))
    s.write(0xAA, val)
    s.run(120)
    end = Path(s.shot(f"v{val}_end"))
    a = (W / f"v{val}_ram0.bin").read_bytes()
    b = (W / f"v{val}_ram1.bin").read_bytes()
    print(f"写 0xAA={val}: 120 帧里 framecount {fc0}->{fc1} (差 {fc1-fc0}) "
          f"RAM 变化 {sum(1 for x, y in zip(a, b) if x != y)} 字节 "
          f"末帧画面 {hashlib.sha1(Path(end).read_bytes()).hexdigest()[:12]}")
s.close()
