import sys, os, json
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\mega_man_usa.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = r"F:\taspipe_scratch\megaman"

with SJ.StateSession(ROM, BH, work=WORK) as s:
    f0, mode = s.ping()
    print("boot ping frame=", f0, "mode=", mode)
    s.run(240)
    title = s.shot("title")
    print("title shot ->", title)
    # ramdump test
    rp = os.path.join(WORK, "ram.bin")
    n = s.ramdump(rp, 2048)
    print("ramdump n=", n, "filesize=", os.path.getsize(rp))
    # dump test: 20 neutral frames
    fd = os.path.join(WORK, "testdump")
    fbefore, _ = s.ping()
    cnt = s.dump(fd, spec=None, extra=20)
    fafter, _ = s.ping()
    pngs = sorted(x for x in os.listdir(fd) if x.endswith(".png"))
    print("dump returned=", cnt, "png_count=", len(pngs), "frame_before=", fbefore, "frame_after=", fafter)
    # life-bar anchor 0x006A (documented) - read to confirm RAM domain
    print("read 0x006A (life?) =", s.read(0x006A))
    print("read 0x0000 =", s.read(0x0000))
print("PROBE DONE")