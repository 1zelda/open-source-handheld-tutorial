# -*- coding: utf-8 -*-
"""热血足球联盟 CN(wl) hack 判别探针：Select 换人抢球 / B 直发必杀。

小鸡模拟器 hack 说明：①Select 切换角色并马上抢球、B 发必杀球技；②上/下加/减比赛时间。
roms_verify 有 cn_jf 与 cn_wl 两版；jf 全链必杀全灭 ⇒ 疑 hack 实为 wl。
本探针（wl ROM）：导航对战 → 持球 → g1 地面 B3 / g2 地面 B30 / g3 跑动 AB+apex B3；
另 s1：持球时 Select 3 帧 → 截图+HUD 判换人。落盘 probe30_wl/。
用法：python soccer2_wl_probe.py
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
    WORK.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(ROM, BH, work=str(WORK)) as s:
        def step(tag, macro=None, run=60, do_parse=False):
            if macro:
                s.macro(macro)
            if run:
                s.run(run)
            s.shot(str(WORK / tag))
            shutil.copyfile(WORK / f"{tag}.png", EVID / f"{tag}.png")
            if do_parse:
                print(tag, "PARSE", parse(s, tag), flush=True)
            else:
                print(tag, "shot", flush=True)

        s.run(1200)
        step("w00_title", hold("Start", 10))
        step("w01_mode", hold("Start", 10))
        step("w02_down1", hold("Down", 3, 20), run=20)
        step("w03_start", hold("Start", 10))
        step("w04_a", hold("A", 6, 10))
        step("w05_a", hold("A", 6, 10))
        step("w06_a", hold("A", 6, 10))
        step("w07_start", hold("Start", 10))
        step("w08_start", hold("Start", 10), do_parse=True)
        rel = None
        onfield = False
        for key in ("Start", "A", "B"):
            tag = f"w09_rel_{key.lower()}"
            step(tag, hold(key, 3, 10), do_parse=True)
            if parse(s, tag) is not None:
                rel = key
                onfield = True
                print("RELEASE_KEY", key, flush=True)
                break
        if not onfield:
            step("w09_wait", run=180, do_parse=True)
            onfield = parse(s, "w09_wait") is not None
        if not onfield:
            for key in ("A", "Start"):
                tag = f"w10_kick_{key.lower()}"
                step(tag, hold(key, 3, 10), do_parse=True)
                if parse(s, tag) is not None:
                    onfield = True
                    print("KICKOFF_KEY", key, flush=True)
                    break
        if not onfield:
            step("w10_wait", run=120, do_parse=True)
            onfield = parse(s, "w10_wait") is not None
        if not onfield:
            print("WL_NO_FIELD", flush=True)
            return
        s.save(str(WORK / "wl_field"))
        shutil.copyfile(WORK / "wl_field.state", EVID / "wl_field.state")
        # 追球持球
        possess = None
        p = None
        for i in range(40):
            p = parse(s, f"wp{i:02d}")
            if p is None:
                s.run(12)
                continue
            if p["dist"] < UA.SOCCER2_POSSESS_DIST:
                possess = s.save(str(WORK / "wl_possess"))
                s.shot(str(WORK / "wl_possess"))
                shutil.copyfile(possess, EVID / "wl_possess.state")
                shutil.copyfile(WORK / "wl_possess.png", EVID / "wl_possess.png")
                print("POSSESS_AT", i, p, flush=True)
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
        # Select 换人判别
        s.load(pb)
        s.macro(hold("Select", 3, 20))
        s.shot(str(WORK / "s1_select"))
        shutil.copyfile(WORK / "s1_select.png", EVID / "s1_select.png")
        print("s1_select PARSE", parse(s, "s1_select"), flush=True)
        chains = [
            ("g1", [hold("B", 3, 18)]),
            ("g2", [hold("B", 30, 10)]),
            ("g3", [hold("Right", 12, 2), hold("A+B", 6, 0), ("run", 8), hold("B", 3, 18)]),
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
    print("WL_OK", flush=True)


if __name__ == "__main__":
    main()