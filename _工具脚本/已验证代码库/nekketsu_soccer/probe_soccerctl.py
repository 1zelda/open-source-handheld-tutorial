import sys, os
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = r"F:\taspipe_scratch\soccerctl"

def held(btn, n):
    return ",".join([btn] * n)

with SJ.StateSession(ROM, BH, work=WORK) as s:
    s.run(1200)
    s.macro(held("Start", 10)); s.run(60)
    s.macro(held("Start", 10)); s.run(60)
    print("c_mode", s.shot("c_mode"))
    s.macro(held("Down", 40)); s.run(20)
    print("c_down", s.shot("c_down"))
    s.macro(held("Right", 40)); s.run(20)
    print("c_right", s.shot("c_right"))
print("SOCCER CONTROL DONE")