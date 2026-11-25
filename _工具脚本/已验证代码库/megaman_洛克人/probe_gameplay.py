import sys, os
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\mega_man_usa.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = r"F:\taspipe_scratch\megaman"

with SJ.StateSession(ROM, BH, work=WORK) as s:
    s.run(180)
    s.macro("Start,Start,,,,"); s.run(60)     # -> stage select
    s.macro("Start,Start,,,,"); s.run(60)     # -> enter Cut Man
    for i, n in enumerate((120, 120, 120, 120)):
        s.run(n)
        print("g%d" % i, s.shot("g%d" % i), "life=", s.read(0x006A))
    rp = os.path.join(WORK, "ram_gameplay.bin")
    print("ramdump", s.ramdump(rp, 2048))
    print("base state", s.save("base"))
print("GAMEPLAY PROBE DONE")