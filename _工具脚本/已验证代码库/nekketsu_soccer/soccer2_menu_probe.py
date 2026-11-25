import sys, shutil
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe.statejump import StateSession
from taspipe import universal_authoring as UA

ROM = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes")
BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_menu_work")
OUT = Path(r"F:\taspipe_scratch\soccer2_menu")
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe11_menu")
OUT.mkdir(parents=True, exist_ok=True)
EVID.mkdir(parents=True, exist_ok=True)


def snap(s, name):
    p = s.shot(str(OUT / name))
    shutil.copy2(p, EVID / (name + ".png"))
    return p


with StateSession(ROM, BH, work=WORK) as s:
    s.run(1200)
    for i in range(5):
        s.macro(UA.hold("Start", 10))
        s.run(60)
    snap(s, "m00_lounge")
    s.macro(UA.hold("Up", 6, 10)); snap(s, "m01_up1")
    s.macro(UA.hold("Up", 6, 10)); snap(s, "m02_up2")
    s.macro(UA.hold("A", 6, 30)); snap(s, "m03_enter_top")
    s.macro(UA.hold("B", 6, 30)); snap(s, "m04_back")
    s.macro(UA.hold("Down", 6, 10)); snap(s, "m05_down1")
    s.macro(UA.hold("A", 6, 30)); snap(s, "m06_enter_mid")
    s.macro(UA.hold("Down", 6, 10)); snap(s, "m07_sub_down")
    s.macro(UA.hold("B", 6, 30)); snap(s, "m08_back")
    s.macro(UA.hold("Right", 6, 10)); snap(s, "m09_right")
    s.macro(UA.hold("Up", 6, 10)); snap(s, "m10_up")
    s.macro(UA.hold("Up", 6, 10)); snap(s, "m11_up2")
    s.macro(UA.hold("A", 6, 30)); snap(s, "m12_enter_right")
    s.macro(UA.hold("B", 6, 30)); snap(s, "m13_back")
print("MENU_OK", flush=True)