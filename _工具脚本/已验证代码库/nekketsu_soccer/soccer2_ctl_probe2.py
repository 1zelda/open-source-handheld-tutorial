import sys
from pathlib import Path
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ

ROM = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes")
BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_ctl_probe")
CAND = Path(r"F:\taspipe_scratch\soccer2_possess_cn\pass_hold_right\possess_cand.state.state")

with SJ.StateSession(ROM, BH, work=WORK) as sess:
    sess.load(str(CAND))
    sess.run(60, shot=str(WORK / "q0_idle60.png"))
    sess.macro("Start,Start,Start,Start,Start,Start,Start,Start,,,,,,,,,,",
               shot=str(WORK / "q1_start.png"))
    sess.run(60, shot=str(WORK / "q2_after_start.png"))
    sess.macro(",".join(["Right"] * 30), shot=str(WORK / "q3_right.png"))
    sess.macro("A+B,A+B,A+B,A+B,A+B,A+B,,,,,,,,,,,,,,", shot=str(WORK / "q4_jump.png"))
    sess.run(20, shot=str(WORK / "q5_apex.png"))
print("PROBE2_OK")