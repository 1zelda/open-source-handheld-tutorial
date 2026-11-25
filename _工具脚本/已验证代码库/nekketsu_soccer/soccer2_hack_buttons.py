# -*- coding: utf-8 -*-
"""wl 系 hack 按钮判别：同一起点分别 B3 / A3 / AB6 / Select3，连帧看球轨迹判射门/传球/跳。
用法：python soccer2_hack_buttons.py <jump|se>
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

WHICH = sys.argv[1] if len(sys.argv) > 1 else "jump"
ROM = Path(r"F:\taspipe_scratch\netdisk_roms") / f"hack_{WHICH}.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_hack") / WHICH
EVID = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves") / (
    "probe31_hackjump" if WHICH == "jump" else "probe32_hackse")


def hold(btn, n, wait=0):
    return UA.hold(btn, n, wait)


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(str(ROM), BH, work=str(WORK)) as s:
        def step(tag, macro=None, run=60):
            if macro:
                s.macro(macro)
            if run:
                s.run(run)
            s.shot(str(WORK / tag))
            shutil.copyfile(WORK / f"{tag}.png", EVID / f"{tag}.png")
            print(tag, "shot", flush=True)

        s.run(1200)
        step("b00_title", hold("Start", 10))
        step("b01_mode", hold("Start", 10))
        step("b02_down", hold("Down", 3, 20), run=20)
        step("b03_start", hold("Start", 10))
        step("b04_start", hold("Start", 10))
        step("b05_start", hold("Start", 10))
        step("b06_wait", run=250)
        field = None
        for k, key in enumerate(("Start", "A", "Start", "A")):
            tag = f"b07_kick{k}"
            step(tag, hold(key, 3, 10))
            rp = WORK / f"{tag}.bin"
            s.ramdump(str(rp))
            if UA.soccer2_oam_parse(rp.read_bytes()) is not None:
                field = s.save(str(WORK / "hack_field"))
                shutil.copyfile(field, EVID / "hack_field.state")
                print("FIELD_AT", key, k, flush=True)
                break
        if field is None:
            print("NO_FIELD", flush=True)
            return
        pb = s.use_state(str(field))
        chains = [
            ("kB", [hold("B", 3, 0), ("run", 30), hold("B", 3, 0)]),
            ("kA", [hold("A", 3, 0), ("run", 30), hold("A", 3, 0)]),
            ("kAB", [hold("A+B", 6, 0)]),
            ("kSel", [hold("Select", 3, 0)]),
        ]
        times = (3, 9, 15, 21, 27, 33, 39, 45, 51, 57)
        rows = []
        for tag, chain in chains:
            s.load(pb)
            for m in chain:
                if isinstance(m, tuple):
                    s.run(m[1])
                else:
                    s.macro(m)
            s.shot(str(WORK / f"{tag}_t00"))
            frames = [WORK / f"{tag}_t00.png"]
            prev = 0
            for t in times:
                s.run(t - prev)
                prev = t
                s.shot(str(WORK / f"{tag}_t{t:02d}"))
                frames.append(WORK / f"{tag}_t{t:02d}.png")
            rows.append(frames)
            print(tag, "done", flush=True)
        from PIL import Image
        ims = [[Image.open(p) for p in row] for row in rows]
        w, h = ims[0][0].size
        sheet = Image.new("RGB", (w * len(times + (0,)), h * len(ims)))
        for r, row in enumerate(ims):
            for c, im in enumerate(row):
                sheet.paste(im, (c * w, r * h))
        sheet.save(WORK / "buttons_sheet.png")
        shutil.copyfile(WORK / "buttons_sheet.png", EVID / "buttons_sheet.png")
    print("BUTTONS_OK", WHICH, flush=True)


if __name__ == "__main__":
    main()