# -*- coding: utf-8 -*-
"""热血足球联盟 CN(jf)：带难度设定的导航 → kickoff → 生产求解器持球 base。

模式屏（第 2 次 Start 后）插入难度操作：Left x2 归零（简单），再 Right xN 选档。
N=0 简单 / 1 普通 / 2 困难；default=不操作（对照）。CN hack 难度标记不可见（f 探针像素级证实），
故用行为反证：普通档必杀应触发、简单档同窗口应不触发（S1 难度规则）。
用法：python soccer2_base_diffnav.py normal|easy|hard|default
证据落盘：验证/t3_soccer2_moves/probe16_<mode>/
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

ROM = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes")
BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
MODE = sys.argv[1] if len(sys.argv) > 1 else "normal"
WORK = Path(r"F:\taspipe_scratch") / f"soccer2_nav_{MODE}"
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves") / f"probe16_{MODE}"
RIGHTS = {"easy": 0, "normal": 1, "hard": 2, "default": None}[MODE]


def hold(btn, n):
    return ",".join([btn] * n)


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(str(ROM), str(BH), work=str(WORK)) as s:
        s.run(1200)
        s.macro(hold("Start", 10))
        s.run(60)
        s.macro(hold("Start", 10))
        s.run(60, shot=s._wpath("n_mode", ".png"))
        shutil.copyfile(s._wpath("n_mode", ".png"), EVID / "n_mode.png")
        if RIGHTS is not None:
            s.macro(hold("Left", 3))
            s.run(20)
            s.macro(hold("Left", 3))
            s.run(20)
            for _ in range(RIGHTS):
                s.macro(hold("Right", 3))
                s.run(20)
            s.run(20, shot=s._wpath("n_diff", ".png"))
            shutil.copyfile(s._wpath("n_diff", ".png"), EVID / "n_diff.png")
        for i in range(3, 6):
            s.macro(hold("Start", 10))
            s.run(60, shot=s._wpath(f"n{i}", ".png"))
            shutil.copyfile(s._wpath(f"n{i}", ".png"), EVID / f"n{i}.png")
        s.macro(hold("A", 6))
        s.run(180, shot=s._wpath("n_kick", ".png"))
        shutil.copyfile(s._wpath("n_kick", ".png"), EVID / "n_kick.png")
        w, h, raw = UA._load_rgb_grid(EVID / "n_kick.png")
        y0 = int(h * 0.82)
        orange = sum(1 for y in range(y0, h) for x in range(w)
                     if raw[(y * w + x) * 3] > 200
                     and 120 < raw[(y * w + x) * 3 + 1] < 200
                     and raw[(y * w + x) * 3 + 2] < 100)
        if orange <= 100:
            raise RuntimeError(f"未达 KICK OFF 冻结态 orange={orange}，核查 n*.png")
        kick = s.save("kickoff")
        shutil.copyfile(kick, EVID / "kickoff.state")
        s.shot("kickoff")
        shutil.copyfile(s._wpath("kickoff", ".png"), EVID / "kickoff.png")
    res = UA.solve_soccer2_possession_base(ROM, BH, EVID / "kickoff.state",
                                          Path(r"F:\taspipe_scratch") / f"soccer2_possess_{MODE}")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    for k in ("possess_base_state", "possess_base_png"):
        if res.get(k):
            shutil.copyfile(res[k], EVID / Path(res[k]).name)
    (EVID / "solve_report.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    print("NAV_DIFF_OK", MODE, res.get("status"))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())