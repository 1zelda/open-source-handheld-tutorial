import sys, os
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\mega_man_usa.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = r"F:\taspipe_scratch\megaman"

with SJ.StateSession(ROM, BH, work=WORK) as s:
    print("ping", s.ping())
    s.run(180)
    print("s0_title", s.shot("s0_title"))
    # press Start at title
    s.macro("Start,Start,,,,")
    s.run(120)
    print("s1_after_start", s.shot("s1_after_start"))
    s.run(60)
    print("s2", s.shot("s2"))
    # try pressing Start again (stage select confirm)
    s.macro("Start,Start,,,,")
    s.run(150)
    print("s3_after_start2", s.shot("s3_after_start2"))
    s.run(60)
    print("s4", s.shot("s4"))
    print("life 0x006A =", s.read(0x006A))
print("INGAME PROBE DONE")