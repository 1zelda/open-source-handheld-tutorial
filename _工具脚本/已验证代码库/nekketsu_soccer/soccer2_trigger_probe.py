import sys
from pathlib import Path
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

ROM = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes")
BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_trigger_probe")
BASE = Path(r"F:\taspipe_scratch\soccer2_possess_cn\possess_base.state")
WORK.mkdir(parents=True, exist_ok=True)

SHOT = UA.chain_macros(UA.hold("A+B", 6, 14), UA.hold("B", 6, 15))
BLANK = ",".join([""] * 41)

with SJ.StateSession(ROM, BH, work=WORK) as sess:
    sess.load(str(BASE))
    sess.macro(",".join(["Right"] * 20), shot=str(WORK / "r1_right20.png"))
    sess.macro(",".join(["Right"] * 20), shot=str(WORK / "r2_right40.png"))
    n_pos = sess.dump(str(WORK / "pos"), spec=SHOT, extra=40, state=str(BASE))
    n_neg = sess.dump(str(WORK / "neg"), spec=BLANK, extra=40, state=str(BASE))
print("DUMP_OK", n_pos, n_neg)