import sys
from pathlib import Path
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

ROM = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes")
BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_dribble_probe")
KICK = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe9_cn\kickoff.state")
WORK.mkdir(parents=True, exist_ok=True)

with SJ.StateSession(ROM, BH, work=WORK) as sess:
    kick = sess.use_state(KICK)
    sess.load(kick)
    sess.macro(",".join(["Right"] * 30), shot=str(WORK / "k1_right30.png"))
    sess.macro(",".join(["Right"] * 30), shot=str(WORK / "k2_right60.png"))
    sess.macro(UA.chain_macros(UA.hold("A+B", 6, 14)), shot=str(WORK / "k3_jump.png"))
    sess.macro(UA.hold("B", 6, 15), shot=str(WORK / "k4_b.png"))
    sess.run(20, shot=str(WORK / "k5_flight.png"))
print("PROBE4_OK")