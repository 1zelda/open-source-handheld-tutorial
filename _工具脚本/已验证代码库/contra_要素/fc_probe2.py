"""一次性探针：base 状态载入后机器到底有没有在推帧。跑完即可删。"""
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\contra_u.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
W = Path("F:/taspipe_scratch/fc_probe2")


def sha(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()[:12]


s = SJ.StateSession(rom=ROM, bizhawk=BH, work=str(W))
s.start()
print("boot ping", s.ping())
dst = Path(s.work) / "in.state"
shutil.copyfile("F:/taspipe_scratch/nav_boot_1/base_stage1.state", dst)
for lbl, st in (("root", "F:/taspipe_scratch/nav_boot_1/boot_root.state"), ("base", str(dst))):
    live0 = s.attempt(st, spec="-", extra=0, ram=str(W / f"r0_{lbl}.bin"))
    live1 = s.attempt(st, spec="-", extra=1, ram=str(W / f"r1_{lbl}.bin"))
    live300 = s.attempt(st, spec="-", extra=300,
                        ram=str(W / f"r3_{lbl}.bin"), shot=str(W / f"sh_{lbl}.png"))
    b0 = (W / f"r0_{lbl}.bin").read_bytes()
    b1 = (W / f"r1_{lbl}.bin").read_bytes()
    b3 = (W / f"r3_{lbl}.bin").read_bytes()
    print(f"{lbl}: fc0={live0['data']} fc1={live1['data']} fc300={live300['data']} "
          f"ram(0v1)={sum(1 for x, y in zip(b0, b1) if x != y)} "
          f"ram(0v300)={sum(1 for x, y in zip(b0, b3) if x != y)} "
          f"shot={sha(W / f'sh_{lbl}.png')}")
print("live ping", s.ping())
s.close()
