import sys, os
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\mega_man_usa.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = r"F:\taspipe_scratch\megaman"

def held(btn, n):
    return ",".join([btn] * n)

with SJ.StateSession(ROM, BH, work=WORK) as s:
    s.run(180)
    s.macro(held("Start", 8)); s.run(60)   # select
    for a in (0x005D, 0x0055, 0x006A):
        print("read %04X =" % a, s.read(a))
    print("weapon region 6B..72:", [s.read(a) for a in range(0x6B, 0x73)])
    print("sel_before", s.shot("j_sel_before"))
    s.write(0x005D, 0x00)
    s.macro(held("Start", 8)); s.run(120)
    print("after_clear_enter", s.shot("j_after_enter"))
    s.run(120)
    print("after_enter2", s.shot("j_after_enter2"))
    print("read 005D now =", s.read(0x005D), "life=", s.read(0x006A))
print("CLEARFLAG PROBE DONE")