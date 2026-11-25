# -*- coding: utf-8 -*-
"""热血足球联盟 CN(jf) ：导航到 KICK OFF → 生产求解器求活 play 持球+全必杀解锁 base。

复用入口：taspipe.statejump.StateSession + taspipe.universal_authoring.solve_soccer2_possession_base
证据落盘：验证/t3_soccer2_moves/probe9_cn/（导航逐轮截图 + kickoff + possess base）
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
WORK = Path(r"F:\taspipe_scratch\soccer2_cn_base")
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe9_cn")


def hold(btn, n):
    return ",".join([btn] * n)


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(str(ROM), str(BH), work=str(WORK)) as s:
        s.run(1200)
        # 11-14 实测：CN(jf) 5 次 Start 到休息室菜单；休息室「开球」项须 A 确认（Start 无效）。
        for i in range(2, 7):
            s.macro(hold("Start", 10))
            s.run(60, shot=s._wpath(f"nav{i}", ".png"))
            shutil.copyfile(s._wpath(f"nav{i}", ".png"), EVID / f"nav{i}.png")
        s.macro(hold("A", 6))
        s.run(180, shot=s._wpath("nav7", ".png"))  # KICK OFF 仪式 → 冻结（横幅保留到首个有效输入）
        shutil.copyfile(s._wpath("nav7", ".png"), EVID / "nav7.png")
        # 11-14 实测：联赛首场场地是土场（橙），绿茵判据误杀；横幅橙字=仪式/冻结态标志。
        w, h, raw = UA._load_rgb_grid(EVID / "nav7.png")
        y0 = int(h * 0.82)
        orange = sum(1 for y in range(y0, h) for x in range(w)
                     if raw[(y * w + x) * 3] > 200
                     and 120 < raw[(y * w + x) * 3 + 1] < 200
                     and raw[(y * w + x) * 3 + 2] < 100)
        if orange <= 100:
            raise RuntimeError(f"未达 KICK OFF 冻结态 orange={orange}，核查 nav*.png")
        kick = s.save("kickoff")
        shutil.copyfile(kick, EVID / "kickoff.state")
        s.shot("kickoff")
        shutil.copyfile(s._wpath("kickoff", ".png"), EVID / "kickoff.png")
    res = UA.solve_soccer2_possession_base(ROM, BH, EVID / "kickoff.state",
                                          Path(r"F:\taspipe_scratch\soccer2_possess_cn"))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if res.get("status") == "ready":
        for k in ("possess_base_state", "possess_base_png", "apex_shot_preview"):
            shutil.copyfile(res[k], EVID / Path(res[k]).name)
        (EVID / "solve_report.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    return 0 if res.get("status") == "ready" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())