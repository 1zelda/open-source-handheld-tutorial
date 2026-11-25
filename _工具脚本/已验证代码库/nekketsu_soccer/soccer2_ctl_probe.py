import sys, shutil
from pathlib import Path
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes")
BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_ctl_probe")
CAND = Path(r"F:\taspipe_scratch\soccer2_possess_cn\pass_hold_right\possess_cand.state.state")

WORK.mkdir(parents=True, exist_ok=True)
with SJ.StateSession(ROM, BH, work=WORK) as sess:
    sess.load(str(CAND))
    sess.run(10, shot=str(WORK / "p0_loaded.png"))
    sess.macro("Right,Right,Right,Right,Right,Right,Right,Right,Right,Right,"
               "Right,Right,Right,Right,Right,Right,Right,Right,Right,Right,"
               "Right,Right,Right,Right,Right,Right,Right,Right,Right,Right",
               shot=str(WORK / "p1_right30.png"))
    sess.run(20, shot=str(WORK / "p2_settle.png"))
    sess.macro("A+B,A+B,A+B,A+B,A+B,A+B,,,,,,,,,,", shot=str(WORK / "p3_jump.png"))
    sess.run(10, shot=str(WORK / "p4_jump_apex.png"))
    sess.macro("B,B,B,B,B,B,,,,,,,,,,,,,,,,,,,,", shot=str(WORK / "p5_b.png"))
    sess.run(30, shot=str(WORK / "p6_after.png"))
print("PROBE_OK")