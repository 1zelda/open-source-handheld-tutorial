import sys, os
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\mega_man_usa.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = r"F:\taspipe_scratch\megaman"

with SJ.StateSession(ROM, BH, work=WORK) as s:
    s.run(180)
    s.macro("Start,Start,,,,"); s.run(60)   # stage select, cursor CUTMAN
    s.macro("Right,Right,,,,"); s.run(30)   # cursor -> GUTSMAN
    print("sel_guts", s.shot("h_sel_guts"))
    fd = os.path.join(WORK, "gutsdump")
    n = s.dump(fd, spec="Start,Start", extra=240)
    print("dump frames", n)
print("GUTS PROBE DONE")