# -*- coding: utf-8 -*-
"""wl 追球持球 verbose 探针：从 wl_field.state 出发，逐步 parse+截图定位 None 成因。
用法：python soccer2_wl_chase.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

ROM = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_wl.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_wl")
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe30_wl")


def hold(btn, n, wait=0):
    return UA.hold(btn, n, wait)


def parse(s, tag):
    rp = WORK / f"{tag}.bin"
    s.ramdump(str(rp))
    return UA.soccer2_oam_parse(rp.read_bytes())


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(ROM, BH, work=str(WORK)) as s:
        pb = s.use_state(str(WORK / "wl_field.state"))
        s.load(pb)
        possess = None
        p = None
        for i in range(40):
            p = parse(s, f"wc{i:02d}")
            print(f"wc{i:02d}", p, flush=True)
            if i % 4 == 0:
                s.shot(str(WORK / f"wc{i:02d}"))
                shutil.copyfile(WORK / f"wc{i:02d}.png", EVID / f"wc{i:02d}.png")
            if p is None:
                s.run(12)
                continue
            if p["dist"] < UA.SOCCER2_POSSESS_DIST:
                possess = s.save(str(WORK / "wl_possess"))
                s.shot(str(WORK / "wl_possess"))
                shutil.copyfile(possess, EVID / "wl_possess.state")
                shutil.copyfile(WORK / "wl_possess.png", EVID / "wl_possess.png")
                print("POSSESS_AT", i, p, flush=True)
                pb = s.use_state(str(possess))
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
            s.shot(str(WORK / "wc_end"))
            shutil.copyfile(WORK / "wc_end.png", EVID / "wc_end.png")
            return
        chains = [
            ("g1", [hold("B", 3, 18)]),
            ("g2", [hold("B", 30, 10)]),
            ("g3", [hold("Right", 12, 2), hold("A+B", 6, 0), ("run", 8), hold("B", 3, 18)]),
            ("g4", [hold("Select", 3, 20)]),
        ]
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
            for j in range(12):
                s.run(3)
                if j % 2 == 0:
                    s.shot(str(WORK / f"{tag}_p{j:02d}"))
                    frames.append(WORK / f"{tag}_p{j:02d}.png")
            row = []
            for c, fp in zip(cols, frames):
                dst = WORK / f"{tag}_{c}.png"
                if fp != dst:
                    shutil.copyfile(fp, dst)
                row.append(dst)
            rows.append(row)
            print(tag, "done", flush=True)
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
    print("WL_CHASE_OK", flush=True)


if __name__ == "__main__":
    main()