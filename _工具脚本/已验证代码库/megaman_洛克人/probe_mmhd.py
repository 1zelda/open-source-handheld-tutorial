import sys, os
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\megamanhd.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = r"F:\taspipe_scratch\mmhd"

def held(btn, n):
    return ",".join([btn] * n)

with SJ.StateSession(ROM, BH, work=WORK) as s:
    s.run(180)
    print("hd_title", s.shot("hd_title"))
    s.macro(held("Start", 8)); s.run(60)
    print("hd_sel", s.shot("hd_sel"))
    s.macro(held("Right", 40)); s.run(20)
    print("hd_right", s.shot("hd_right"))
print("MMHD PROBE DONE")