# -*- coding: utf-8 -*-
"""wl 系 hack（无限跳跃 / 按Se群殴）判别探针。
导航：mode 对战行 Left 梯截图（人数列默认判别，Left3 回默认）→ Start×3 → VS 自动进休息室 → Start 开球；
冻结判别（360 帧无输入坐标是否不变）→ 追球持球 → 触发链（地面B/长B/跳后B偏移梯/Select）。
用法：python soccer2_hack_probe.py <jump|se>
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


def parse(s, tag):
    rp = WORK / f"{tag}.bin"
    s.ramdump(str(rp))
    return UA.soccer2_oam_parse(rp.read_bytes())


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(str(ROM), BH, work=str(WORK)) as s:
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
        step("h00_title", hold("Start", 10))
        step("h01_mode", hold("Start", 10))
        step("h02_down", hold("Down", 3, 20), run=20)
        step("h03_left1", hold("Left", 3, 20), run=20)
        step("h04_left2", hold("Left", 3, 20), run=20)
        step("h05_left3", hold("Left", 3, 20), run=20)
        step("h06_start", hold("Start", 10))
        step("h07_start", hold("Start", 10))
        step("h08_start", hold("Start", 10))
        step("h09_wait", run=180)
        onfield = False
        for k, key in enumerate(("Start", "A", "Start", "A")):
            tag = f"h10_kick{k}"
            step(tag, hold(key, 3, 10), do_parse=True)
            if parse(s, tag) is not None:
                onfield = True
                print("KICKOFF_KEY", key, k, flush=True)
                break
        if not onfield:
            step("h10_wait", run=120, do_parse=True)
            onfield = parse(s, "h10_wait") is not None
        if not onfield:
            print("NO_FIELD", flush=True)
            return
        p0 = parse(s, "h10_kick3")
        s.run(360)
        p1 = parse(s, "h11_frozen")
        print("FROZEN", p0 == p1, p0, p1, flush=True)
        s.macro(hold("A", 3, 30))
        possess = None
        p = None
        for i in range(60):
            p = parse(s, f"hp{i:02d}")
            if i % 4 == 0:
                s.shot(str(WORK / f"hp{i:02d}"))
                shutil.copyfile(WORK / f"hp{i:02d}.png", EVID / f"hp{i:02d}.png")
            if p is None:
                s.run(12)
                continue
            if (p["dist"] < UA.SOCCER2_POSSESS_DIST and p["holder_team"] == 1
                    and abs(p["holder_dist"] - p["dist"]) < 0.6):
                if p["opp_dist"] is None or p["opp_dist"] > 40:
                    possess = s.save(str(WORK / "hack_possess"))
                    s.shot(str(WORK / "hack_possess"))
                    shutil.copyfile(possess, EVID / "hack_possess.state")
                    shutil.copyfile(WORK / "hack_possess.png", EVID / "hack_possess.png")
                    print("POSSESS_AT", i, p, flush=True)
                    break
                away = UA.soccer2_dir_toward(*p["cap"], *p["opp"])
                rev = {"Left": "Right", "Right": "Left", "Up": "Down", "Down": "Up"}
                back = "+".join(rev[t] for t in away.split("+") if t in rev) or "Left"
                s.macro(hold(back, 16, 4))
                continue
            d = UA.soccer2_dir_toward(*p["cap"], *p["ball"])
            if p["holder_team"] == 1 and p["holder_dist"] < 14:
                s.macro(UA.chain_macros(hold("A", 6, 6), hold("", 12)))
            elif d:
                s.macro(hold(d, 14, 4))
            else:
                s.run(12)
        if possess is None:
            print("NO_POSSESS", p, flush=True)
            s.shot(str(WORK / "hp_end"))
            shutil.copyfile(WORK / "hp_end.png", EVID / "hp_end.png")
            return
        pb = s.use_state(str(possess))
        s.load(pb)
        s.macro(hold("Right+A+B", 6, 0))
        for k in range(12):
            s.run(1)
            q = parse(s, f"cal{k:02d}")
            print("CAL", k + 1, q, flush=True)
        chains = [
            ("b0", [hold("B", 3, 18)]),
            ("u04", [hold("Right+A+B", 4, 0), hold("B", 3, 18)]),
            ("u06", [hold("Right+A+B", 6, 0), hold("B", 3, 18)]),
            ("u08", [hold("Right+A+B", 6, 0), ("run", 2), hold("B", 3, 18)]),
            ("v08", [hold("Right+A+B", 4, 0), hold("A+B", 2, 0), ("run", 2), hold("B", 3, 18)]),
            ("v12", [hold("Right+A+B", 4, 0), hold("A+B", 2, 0), ("run", 6), hold("B", 3, 18)]),
            ("ra16", [hold("Right", 12, 0), hold("Right+A+B", 6, 0), ("run", 10), hold("B", 3, 18)]),
            ("s1", [hold("Select", 3, 20)]),
        ]
        cols = ["kick", "p03", "p09", "p15", "p21", "p27", "p33", "p39", "p45"]
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
            prev = 0
            for t in (3, 9, 15, 21, 27, 33, 39, 45):
                s.run(t - prev)
                prev = t
                s.shot(str(WORK / f"{tag}_p{t:02d}"))
                frames.append(WORK / f"{tag}_p{t:02d}.png")
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
    print("HACK_OK", WHICH, flush=True)


if __name__ == "__main__":
    main()