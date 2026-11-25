"""一次性 author 探针：从 base(=STAGE 1 卡) 之后扫空跑长度，找第一个真受控帧。跑完即删。"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe.universal_authoring import check_controllability

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\contra_u.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
BASE = "F:/taspipe_scratch/nav_boot_1/base_stage1.state"
W = Path("F:/taspipe_scratch/settle_sweep")


def sha(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()[:12]


s = SJ.StateSession(rom=ROM, bizhawk=BH, work=str(W))
s.start()
src = Path(s.work) / "base.state"
shutil.copyfile(BASE, src)
for n in (0, 60, 90, 120, 150, 180, 240, 300, 360, 480):
    cand = Path(s.work) / f"settle{n:04d}.state"
    ref = Path(s.work) / f"settle{n:04d}.png"
    r = s.attempt(str(src), spec="-", extra=n, shot=str(ref), save=str(cand))
    ctrl = check_controllability(s, cand, Path(s.work) / f"c{n:04d}")
    rb = (Path(s.work) / f"c{n:04d}" / "ram_neutral.bin").read_bytes()
    print(json.dumps({
        "settle": n, "fc": r["data"], "ref": sha(ref),
        "ram_AA": rb[0xAA], "ram_AC": rb[0xAC],
        "neu": sha(ctrl["screenshots"]["neutral"]),
        "act": sha(ctrl["screenshots"]["action"]),
        "men": sha(ctrl["screenshots"]["menu"]),
        "act_eff": ctrl["action_effective"], "men_eff": ctrl["menu_effective"],
        "ram_diff": ctrl["ram_diff_bytes"], "controllable": ctrl["controllable"],
    }, ensure_ascii=False))
s.close()
