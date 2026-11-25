import sys, shutil
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe.statejump import StateSession
from taspipe import universal_authoring as UA

ROM = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes")
BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_menu2_work")
OUT = Path(r"F:\taspipe_scratch\soccer2_menu2")
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe11_menu")
OUT.mkdir(parents=True, exist_ok=True)


def snap(s, name):
    p = s.shot(str(OUT / name))
    shutil.copy2(p, EVID / (name + ".png"))


with StateSession(ROM, BH, work=WORK) as s:
    s.run(1200)
    for i in range(5):
        s.macro(UA.hold("Start", 10))
        s.run(60)
    s.macro(UA.hold("Up", 6, 10))
    s.macro(UA.hold("Up", 6, 10))
    s.macro(UA.hold("A", 6, 30))
    snap(s, "e00_tactics")
    s.macro(UA.hold("Start", 8, 20)); snap(s, "e01_start")
    s.macro(UA.hold("B", 6, 20)); snap(s, "e02_b")
    s.macro(UA.hold("A", 6, 20)); snap(s, "e03_a")
    s.macro(UA.hold("Down", 6, 10)); snap(s, "e04_down")
    s.macro(UA.hold("Down", 6, 10)); snap(s, "e05_down")
    s.macro(UA.hold("Down", 6, 10)); snap(s, "e06_down")
    s.macro(UA.hold("A", 6, 20)); snap(s, "e07_a")
    s.macro(UA.hold("Down", 6, 10)); snap(s, "e08_down")
    s.macro(UA.hold("Right", 6, 10)); snap(s, "e09_right")
    s.macro(UA.hold("A", 6, 20)); snap(s, "e10_a")
    s.macro(UA.hold("B", 6, 20)); snap(s, "e11_b")
    s.macro(UA.hold("Start", 8, 20)); snap(s, "e12_start")
    s.macro(UA.hold("Down", 6, 10)); snap(s, "e13_down")
    s.macro(UA.hold("A", 6, 30)); snap(s, "e14_a")
    s.macro(UA.hold("Down", 6, 10)); snap(s, "e15_down")
    s.macro(UA.hold("Down", 6, 10)); snap(s, "e16_down")
    s.macro(UA.hold("A", 6, 20)); snap(s, "e17_a")
print("MENU2_OK", flush=True)