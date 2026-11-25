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
    print("t_title", s.shot("i_title"))
    s.run(240)  # NO input control: does title auto-advance?
    print("t_noinput", s.shot("i_noinput"))
    s.macro(held("Start", 8)); s.run(60)
    print("t_start", s.shot("i_start"))
    s.macro(held("Right", 40)); s.run(20)
    print("t_right", s.shot("i_right"))
    s.macro(held("Down", 40)); s.run(20)
    print("t_down", s.shot("i_down"))
print("INPUT EFFICACY DONE")