# -*- coding: utf-8 -*-
"""热血足球联盟 CN(jf)：对战干净实验室 × 跑动人球同跳 × apex 对齐扫掠。

probe22 实测：静止 AB=脚跟挑球（球独升、人不跳）；跑动 AB 才人球同跳；
OAM 队长 y 时间线定 apex ≈ AB 后 29-38 帧（空中盲 zone 21 帧）。
本扫掠：Right12 助跑 + AB(6,14) + off∈{8,12,16,20,24} → B 落在 28-44 帧覆盖 apex。
每链 12 相 bin+截图+队长 y 时间线；sheet 判球变形（坚果椭圆=国夫 nuts 真阳性）。
落盘 probe23_vsapex/。用法：python soccer2_vs_apex.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_vsapex")
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe23_vsapex")
BASE = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe22_vssweep\vs_possess.state")


def hold(btn, n, wait=0):
    return UA.hold(btn, n, wait)


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(ROM, BH, work=str(WORK)) as s:
        pb = s.use_state(str(BASE))
        cols = ["kick", "p01", "p03", "p05", "p07", "p09"]
        rows = []
        for off in (8, 12, 16, 20, 24):
            tag = f"ap{off:02d}"
            s.load(pb)
            s.macro(hold("Right", 12, 2))
            s.macro(hold("A+B", 6, 14))
            if off:
                s.run(off)
            s.macro(hold("B", 6, 15), shot=str(WORK / f"{tag}_kick.png"))
            frames = [WORK / f"{tag}_kick.png"]
            tiles_all, ys = [], []
            for j in range(12):
                s.run(3)
                bp = WORK / f"{tag}_t{j:02d}.bin"
                s.ramdump(str(bp))
                ram = bp.read_bytes()
                q = UA.soccer2_oam_parse(ram)
                ys.append(q["cap"][1] if q else None)
                tiles = sorted({t for (_, _, t, a, _) in UA._oam_sprites(ram)
                                if t in UA.SOCCER2_BALL_TILES_EXTENDED and (a & 3) == 0})
                tiles_all.append(tiles)
                if j % 2 == 0:
                    s.shot(str(WORK / f"{tag}_p{j:02d}"))
                    frames.append(WORK / f"{tag}_p{j:02d}.png")
            special = [j for j, t in enumerate(tiles_all) if t and not set(t) <= UA.SOCCER2_BALL_TILES]
            print(tag, "B_at", 20 + off, "special", special, "capY", ys, flush=True)
            row = []
            for c, fp in zip(cols, frames):
                dst = WORK / f"{tag}_{c}.png"
                if fp != dst:
                    shutil.copyfile(fp, dst)
                row.append(dst)
            rows.append(row)
        from PIL import Image
        ims = [[Image.open(p) for p in row] for row in rows]
        w, h = ims[0][0].size
        sheet = Image.new("RGB", (w * len(cols), h * len(ims)))
        for r, row in enumerate(ims):
            for c, im in enumerate(row):
                sheet.paste(im, (c * w, r * h))
        sheet.save(WORK / "sweep_sheet.png")
        shutil.copyfile(WORK / "sweep_sheet.png", EVID / "sweep_sheet.png")
        for row in rows:
            for p in row:
                shutil.copyfile(p, EVID / p.name)
    print("VSAPEX_OK", flush=True)


if __name__ == "__main__":
    main()