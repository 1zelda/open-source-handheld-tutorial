"""一次性探针：冻结点之后画面/RAM 随帧号的变化曲线。跑完即可删。"""
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\contra_u.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
W = Path("F:/taspipe_scratch/anim_probe")
BASE = "F:/taspipe_scratch/nav_boot_1/base_stage1.state"
REF = "F:/taspipe_scratch/nav_boot_1/nav_ref.png"


def sha(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()[:12]


print("nav_ref", sha(REF))
s = SJ.StateSession(rom=ROM, bizhawk=BH, work=str(W))
s.start()
dst = Path(s.work) / "in.state"
shutil.copyfile(BASE, dst)
prev = None
for n in (0, 15, 30, 60, 90, 120, 180, 240, 300, 420):
    shot = W / f"n{n:04d}.png"
    ram = W / f"r{n:04d}.bin"
    r = s.attempt(str(dst), spec="-", extra=n, shot=str(shot), ram=str(ram))
    print(f"neutral extra={n:4d} fc={r['data']:>5} shot={sha(shot)} "
          f"ram0xAA={ram.read_bytes()[0xAA]} ram0xAC={ram.read_bytes()[0xAC]}")
for n in (30, 120, 300):
    shot = W / f"act{n:04d}.png"
    r = s.attempt(str(dst), spec=SJ.parse_macro("Right+A+B" + ",Right+A+B" * (n - 1)),
                  extra=0, shot=str(shot))
    print(f"action {n:4d} frames fc={r['data']:>5} shot={sha(shot)}")
    shot2 = W / f"men{n:04d}.png"
    spec = ",".join(["Start"] * 4 + [""] * (n - 4))
    r2 = s.attempt(str(dst), spec=SJ.parse_macro(spec), extra=0, shot=str(shot2))
    print(f"menu   {n:4d} frames fc={r2['data']:>5} shot={sha(shot2)}")
s.close()
