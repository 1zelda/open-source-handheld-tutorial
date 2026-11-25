# -*- coding: utf-8 -*-
"""probe38: 杂志/攻略记载的正确触发族（此前未测）：平地步数B、跳最高点B、前B头球、后B倒钩。
从净持球 received.state 出发。用法：python soccer2_correct_triggers.py <jump|se>
"""
import sys
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import statejump as SJ
from taspipe import universal_authoring as UA

WHICH = sys.argv[1] if len(sys.argv) > 1 else "jump"
ROM = Path(r"F:\taspipe_scratch\netdisk_roms") / f"hack_{WHICH}.nes"
BH = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8"
WORK = Path(r"F:\taspipe_scratch\soccer2_triggers") / WHICH
BASE = Path(r"F:\taspipe_scratch\soccer2_userroute") / WHICH / "received.state"


def hold(b, n, w=0):
    return UA.hold(b, n, w)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    rows, labels = [], []
    times = [4, 8, 12, 18, 24]
    variants = []
    for F in (12, 20, 28, 40, 56):
        variants.append((f"ground{F}", [hold("Right", F, 0), hold("B", 3, 0)]))
    for J in (6, 10, 14):
        variants.append((f"apex{J}", [hold("A+B", 6, 0), (J, None), hold("B", 3, 0)]))
    for K in (3, 6):
        variants.append((f"fwdB{K}", [hold("Right+A+B", 6, 0), (K, None), hold("Right+B", 3, 0)]))
        variants.append((f"backB{K}", [hold("Right+A+B", 6, 0), (K, None), hold("Left+B", 3, 0)]))
    with SJ.StateSession(str(ROM), BH, work=str(WORK)) as s:
        pb = s.use_state(str(BASE))
        for tag, seq in variants:
            s.load(pb)
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
            rows.append(frames); labels.append(tag)
            print(tag, "done", flush=True)
    w, h = Image.open(rows[0][0]).size
    sheet = Image.new("RGB", (w * len(times), h * len(rows)))
    for r, row in enumerate(rows):
        for c, fp in enumerate(row):
            sheet.paste(Image.open(fp), (c * w, r * h))
    sheet.save(WORK / "trigger_sheet.png")
    (WORK / "labels.txt").write_text("\n".join(labels), encoding="utf-8")
    print("TRIGGERS_OK", WHICH, "rows", len(rows), flush=True)


if __name__ == "__main__":
    main()