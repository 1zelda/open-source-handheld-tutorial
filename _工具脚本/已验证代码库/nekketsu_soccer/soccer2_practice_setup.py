# -*- coding: utf-8 -*-
"""练习态底稿：按已验证导航走到 KICK OFF 冻结，存 field.state 并确认"看得见球和人"。

复用出处：_工具脚本/已验证代码库/nekketsu_soccer/soccer2_base_cn.py（5×Start + A 确认开球）。
产物：F:\\taspipe_scratch\\soccer2_practice\\field.state + field.png + 证据副本。
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, r"F:\taspipe_scratch")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA
from soccer2_ramhunt import _probe

ROM = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes")
BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_practice")
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe45_practice")


def hold(btn, n):
    return ",".join([btn] * n)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)
    rp = WORK / "ram.bin"
    with SJ.StateSession(str(ROM), str(BH), work=str(WORK)) as s:
        s.run(1200)
        for i in range(2, 7):
            s.macro(hold("Start", 10))
            s.run(60, shot=s._wpath(f"nav{i}", ".png"))
            shutil.copyfile(s._wpath(f"nav{i}", ".png"), EVID / f"nav{i}.png")
            s.ramdump(str(rp))
            p = _probe(rp.read_bytes())
            print(f"nav{i} 探针={p}", flush=True)
        s.macro(hold("A", 6))
        s.run(180, shot=s._wpath("nav7", ".png"))
        shutil.copyfile(s._wpath("nav7", ".png"), EVID / "nav7.png")
        w, h, raw = UA._load_rgb_grid(EVID / "nav7.png")
        y0 = int(h * 0.82)
        orange = sum(1 for y in range(y0, h) for x in range(w)
                     if raw[(y * w + x) * 3] > 200 and 120 < raw[(y * w + x) * 3 + 1] < 200
                     and raw[(y * w + x) * 3 + 2] < 100)
        print(f"KICK OFF 横幅橙字像素={orange}")
        if orange <= 100:
            raise RuntimeError("未达 KICK OFF 冻结态，核查 nav7.png")
        st = s.save("field")
        shutil.copyfile(st, EVID / "field.state")
        s.ramdump(str(rp))
        print("冻结即探针 =", _probe(rp.read_bytes()))
        s.shot("field0")
        # 放开 60 帧看是否真在踢（AI 会自己动）
        s.run(60, shot=s._wpath("field60", ".png"))
        s.ramdump(str(rp))
        p60 = _probe(rp.read_bytes())
        print("60 帧后探针 =", p60)
        for name in ("field0", "field60"):
            src = s._wpath(name, ".png")
            if Path(src).is_file():
                shutil.copyfile(src, EVID / f"{name}.png")
        print(f"底稿：{st}")
        if not p60 or "ball" not in p60:
            raise SystemExit("场上看不见球，反查底稿不合格")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
