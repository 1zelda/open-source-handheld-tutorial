# -*- coding: utf-8 -*-
"""热血足球联盟 CN(jf)：对战干净实验室 × 持球 × 必杀触发窗决定性扫掠。

probe21 实测：对战 2P 挂机 = 全场冻结/无逼抢（360 帧坐标全同）；休息室开球确认键=Start（联赛=A）。
流程：vs_field3 冻结场 → 解除键试探(A3/B3/Start8，以 RAM 活性判) → 追球控制器求持球 base
→ 7 链必杀窗：静止 apex+0/6/12/18/24 + 跑动助跑 apex+0/6。每链 12 相 bin+截图拼 sheet。
真阳性（球变形≠旋转常态）用于标定必杀闸门。落盘 probe22_vssweep/。
用法：python soccer2_vs_sweep.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_vssweep")
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe22_vssweep")
BASE = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe21_vs\vs_field3.state")


def hold(btn, n, wait=0):
    return UA.hold(btn, n, wait)


def parse(s, tag):
    rp = WORK / f"{tag}.bin"
    s.ramdump(str(rp))
    return UA.soccer2_oam_parse(rp.read_bytes())


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(ROM, BH, work=str(WORK)) as s:
        base = s.use_state(str(BASE))
        s.load(base)
        # 解除仪式：以 2 帧 RAM 活性判
        live = False
        for tag, m in [("rel_a", hold("A", 3, 10)), ("rel_b", hold("B", 3, 10)),
                       ("rel_start", hold("Start", 8, 10))]:
            s.macro(m)
            ra = WORK / "la.bin"
            rb = WORK / "lb.bin"
            s.ramdump(str(ra)); s.run(2); s.ramdump(str(rb))
            live = ra.read_bytes() != rb.read_bytes()
            print(tag, "LIVE", live, flush=True)
            if live:
                break
        if not live:
            print("NO_RELEASE_KEY", flush=True)
            return
        st = s.save(str(WORK / "vs_live2"))
        shutil.copyfile(st, EVID / "vs_live2.state")
        # 追球控制器求持球
        possess = None
        p = None
        for i in range(40):
            p = parse(s, f"pos{i:02d}")
            if p is None:
                s.run(12)
                continue
            if p["dist"] < UA.SOCCER2_POSSESS_DIST:
                q = parse(s, f"poschk{i:02d}")
                if q and q["dist"] < UA.SOCCER2_POSSESS_DIST:
                    possess = s.save(str(WORK / "vs_possess"))
                    s.shot(str(WORK / "vs_possess"))
                    shutil.copyfile(possess, EVID / "vs_possess.state")
                    shutil.copyfile(WORK / "vs_possess.png", EVID / "vs_possess.png")
                    print("POSSESS_AT", i, q, flush=True)
                    break
            d = UA.soccer2_dir_toward(*p["cap"], *p["ball"])
            if p["holder_team"] == 1:
                s.macro(UA.chain_macros(hold("A", 6, 6), hold("", 12)))
            elif p["dist"] < 24 and d:
                s.macro(UA.chain_macros(hold(d, 10), hold("B", 6, 6)))
            elif d:
                s.macro(hold(d, 14, 4))
            else:
                s.macro(hold("B", 6, 6))
        if possess is None:
            print("NO_POSSESS", p, flush=True)
            return
        pb = s.use_state(str(possess))
        chains = []
        for off in (0, 6, 12, 18, 24):
            chains.append((f"st{off:02d}", [hold("A+B", 6, 14)] + [None] * (off // 6) + [hold("B", 6, 15)]))
        chains.append(("run0", [hold("Right", 12, 2), hold("A+B", 6, 14), hold("B", 6, 15)]))
        chains.append(("run6", [hold("Right", 12, 2), hold("A+B", 6, 14), None, hold("B", 6, 15)]))
        cols = ["kick", "p01", "p03", "p05", "p07", "p09"]
        sheet_rows = []
        for tag, chain in chains:
            s.load(pb)
            q0 = parse(s, f"{tag}_pre")
            for m in chain:
                if m is None:
                    s.run(6)
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
            print(tag, "dist_pre", q0["dist"] if q0 else None, "special", special, flush=True)
            row = []
            for c, fp in zip(cols, frames):
                dst = WORK / f"{tag}_{c}.png"
                if fp != dst:
                    shutil.copyfile(fp, dst)
                row.append(dst)
            sheet_rows.append(row)
        from PIL import Image
        ims = [[Image.open(p) for p in row] for row in sheet_rows]
        w, h = ims[0][0].size
        sheet = Image.new("RGB", (w * len(cols), h * len(ims)))
        for r, row in enumerate(ims):
            for c, im in enumerate(row):
                sheet.paste(im, (c * w, r * h))
        sheet.save(WORK / "sweep_sheet.png")
        shutil.copyfile(WORK / "sweep_sheet.png", EVID / "sweep_sheet.png")
        for row in sheet_rows:
            for p in row:
                shutil.copyfile(p, EVID / p.name)
    print("VSSWEEP_OK", len(chains), flush=True)


if __name__ == "__main__":
    main()