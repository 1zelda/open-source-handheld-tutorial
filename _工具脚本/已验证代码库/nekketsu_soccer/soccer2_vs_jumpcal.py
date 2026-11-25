# -*- coding: utf-8 -*-
"""热血足球联盟 CN(jf)：1 帧分辨率跳跃标定 + apex 压边 B 试探。

probe23 实测：B 压边 28/32=普通射门、36+=落地空放 ⇒ 必杀窗窄且 B 按压边判。
标定：跑动+AB 后 60 帧逐帧 ramdump，腿_tuck 盲 zone=[a,b] → apex≈(a+b)/2。
再 3 链：B 3 帧压边落在 apex-2/apex/apex+2。12 相 bin+截图判球变形。
落盘 probe24_jumpcal/。用法：python soccer2_vs_jumpcal.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_jumpcal")
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe24_jumpcal")
BASE = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe22_vssweep\vs_possess.state")


def hold(btn, n, wait=0):
    return UA.hold(btn, n, wait)


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(ROM, BH, work=str(WORK)) as s:
        pb = s.use_state(str(BASE))
        s.load(pb)
        s.macro(hold("Right", 12, 2))
        s.macro(hold("A+B", 6, 0))
        blind = []
        for f in range(60):
            s.run(1)
            rp = WORK / f"cal{f:02d}.bin"
            s.ramdump(str(rp))
            q = UA.soccer2_oam_parse(rp.read_bytes())
            blind.append(q is None)
        runs = []
        start = None
        for i, b in enumerate(blind):
            if b and start is None:
                start = i
            if not b and start is not None:
                runs.append((start, i - 1))
                start = None
        if start is not None:
            runs.append((start, 59))
        print("BLIND_RUNS", runs, flush=True)
        long = max(runs, key=lambda r: r[1] - r[0]) if runs else (20, 40)
        apex = (long[0] + long[1]) // 2 + 6  # +6 = AB hold 6 帧偏移（blind 从 AB 后计）
        print("APEX_EST", apex, flush=True)
        cols = ["kick", "p01", "p03", "p05", "p07", "p09"]
        rows = []
        for delta in (-2, 0, 2):
            tag = f"bx{delta+2:02d}"
            at = apex + delta
            s.load(pb)
            s.macro(hold("Right", 12, 2))
            s.macro(hold("A+B", 6, 0))
            s.run(max(1, at - 6))
            s.macro(hold("B", 3, 18), shot=str(WORK / f"{tag}_kick.png"))
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
            print(tag, "B_edge_at", at, "special", special, flush=True)
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
    print("JUMPCAL_OK", flush=True)


if __name__ == "__main__":
    main()