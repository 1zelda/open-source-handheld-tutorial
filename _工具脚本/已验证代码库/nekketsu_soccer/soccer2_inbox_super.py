# -*- coding: utf-8 -*-
"""probe39: 进禁区+高空球/燕返触发（sohu:高空球在禁区必出必杀；燕返=方向+A+B仅小辫子）。
先 Right 带球推进 ~50f 入禁区，再挑高球/燕返后射门。用法：python soccer2_inbox_super.py <jump|se>
"""
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

WHICH = sys.argv[1] if len(sys.argv) > 1 else "jump"
ROM = Path(r"F:\taspipe_scratch\netdisk_roms") / f"hack_{WHICH}.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_inbox") / WHICH
BASE = Path(r"F:\taspipe_scratch\soccer2_userroute") / WHICH / "received.state"


def hold(b, n, w=0):
    return UA.hold(b, n, w)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    rows, labels = [], []
    times = [4, 8, 12, 18]
    variants = []
    for K in (2, 4, 6):
        variants.append((f"box_tossB{K}", [hold("A+B", 6, 0), (K, None), hold("B", 3, 0)]))
        variants.append((f"box_tossFwdB{K}", [hold("A+B", 6, 0), (K, None), hold("Right+B", 3, 0)]))
    for K in (2, 4):
        variants.append((f"box_yanfanB{K}", [hold("Right+A+B", 6, 0), (K, None), hold("B", 3, 0)]))
    variants.append(("box_apexB", [hold("A+B", 6, 0), (8, None), hold("B", 3, 0)]))
    with SJ.StateSession(str(ROM), BH, work=str(WORK)) as s:
        pb = s.use_state(str(BASE))
        for tag, seq in variants:
            s.load(pb)
            s.macro(hold("Right", 50, 0))   # dribble into box
            at = WORK / f"{tag}_at.bin"
            s.ramdump(str(at))
            p = UA.soccer2_oam_parse(at.read_bytes())
            ok = UA.soccer2_possess_ok(p)
            for item in seq:
                if isinstance(item, tuple):
                    s.run(item[0])
                else:
                    s.macro(item)
            frames, prev = [], 0
            for t in times:
                s.run(t - prev); prev = t
                stem = WORK / f"{tag}_t{t:02d}"
                s.shot(str(stem))
                frames.append(Path(str(stem) + ".png"))
            rows.append(frames); labels.append(f"{tag} possess={ok}")
            print(tag, "possess", ok, flush=True)
    w, h = Image.open(rows[0][0]).size
    sheet = Image.new("RGB", (w * len(times), h * len(rows)))
    for r, row in enumerate(rows):
        for c, fp in enumerate(row):
            sheet.paste(Image.open(fp), (c * w, r * h))
    sheet.save(WORK / "inbox_sheet.png")
    (WORK / "labels.txt").write_text("\n".join(labels), encoding="utf-8")
    print("INBOX_OK", WHICH, "rows", len(rows), flush=True)


if __name__ == "__main__":
    main()