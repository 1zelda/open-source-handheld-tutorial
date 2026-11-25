# -*- coding: utf-8 -*-
"""热血足球联盟 CN(jf)：球高判据必杀试探（S1 原文「足够高的时候击球」）。

probe22-26 全负根因假说：必杀判据=击球时球的高度，不是人的 apex；
人球同跳球在脚高=普通射门。S1 困难技巧原文：←AB/→AB 挑球空中→看准落点跳起空中 B=必杀。
标定：heel lift(Right+A+B 3) 与跑动 AB 各 60 帧逐帧球 y → 球顶点 P。
4 链：h1/h2 = 挑球后跳（apex 对齐球顶）B 压边 P/P+6；r1/r2 = 跑动 AB 后 B 压边 P_run/P_run+6。
12 相 bin+截图拼 sheet 判球变形。落盘 probe27_ballhigh/。用法：python soccer2_vs_ballhigh.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_ballhigh")
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe27_ballhigh")
BASE = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe22_vssweep\vs_possess.state")


def hold(btn, n, wait=0):
    return UA.hold(btn, n, wait)


def ball_y(ram):
    ys = [y for (_, y, t, a, _) in UA._oam_sprites(ram)
          if t in UA.SOCCER2_BALL_TILES and (a & 3) == 0]
    return min(ys) + 8 if ys else None


def cal(s, pb, tag, pre):
    s.load(pb)
    for m in pre:
        s.macro(m)
    ys = []
    for f in range(60):
        s.run(1)
        rp = WORK / f"{tag}{f:02d}.bin"
        s.ramdump(str(rp))
        ys.append(ball_y(rp.read_bytes()))
    valid = [(i, y) for i, y in enumerate(ys) if y is not None]
    peak = min(valid, key=lambda t: t[1]) if valid else (20, 999)
    print(tag, "BALL_Y", ys, flush=True)
    print(tag, "PEAK", peak, flush=True)
    return peak[0]


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(ROM, BH, work=str(WORK)) as s:
        pb = s.use_state(str(BASE))
        ph = cal(s, pb, "ch", [hold("Right+A+B", 3, 0)])
        pr = cal(s, pb, "cr", [hold("Right", 12, 2), hold("A+B", 6, 0)])
        chains = []
        for tag, at in (("r07", 7), ("r10", 10), ("r17", pr), ("r23", pr + 6)):
            chains.append((tag, [hold("Right", 12, 2), hold("A+B", 6, 0),
                                 ("run", max(1, at)), hold("B", 3, 18)]))
        cols = ["kick", "p01", "p03", "p05", "p07", "p09"]
        rows = []
        for tag, chain in chains:
            s.load(pb)
            for m in chain:
                if isinstance(m, tuple):
                    s.run(m[1])
                else:
                    s.macro(m)
            s.shot(str(WORK / f"{tag}_kick"))
            frames = [WORK / f"{tag}_kick.png"]
            tiles_all = []
            for j in range(12):
                s.run(3)
                bp = WORK / f"{tag}_t{j:02d}.bin"
                s.ramdump(str(bp))
                ram = bp.read_bytes()
                tiles = sorted({t for (_, _, t, a, _) in UA._oam_sprites(ram)
                                if t in UA.SOCCER2_BALL_TILES_EXTENDED and (a & 3) == 0})
                tiles_all.append(tiles)
                if j % 2 == 0:
                    s.shot(str(WORK / f"{tag}_p{j:02d}"))
                    frames.append(WORK / f"{tag}_p{j:02d}.png")
            special = [j for j, t in enumerate(tiles_all) if t and not set(t) <= UA.SOCCER2_BALL_TILES]
            print(tag, "special", special, flush=True)
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
    print("BALLHIGH_OK", flush=True)


if __name__ == "__main__":
    main()