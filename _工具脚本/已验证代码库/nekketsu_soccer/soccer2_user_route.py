# -*- coding: utf-8 -*-
"""用户路线验证：开球传球→要回传→接球瞬间立即触发，逐帧记录球权防"被抢"假说。
用法：python soccer2_user_route.py <jump|se>
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
WORK = Path(r"F:\taspipe_scratch\soccer2_userroute") / WHICH


def hold(btn, n, wait=0):
    return UA.hold(btn, n, wait)


def parse(s, tag):
    rp = WORK / f"{tag}.bin"
    s.ramdump(str(rp))
    return UA.soccer2_oam_parse(rp.read_bytes())


def cap_has(p):
    return (p is not None and p["dist"] < UA.SOCCER2_POSSESS_DIST
            and p["holder_team"] == 1 and abs(p["holder_dist"] - p["dist"]) < 0.6)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    with SJ.StateSession(str(ROM), BH, work=str(WORK)) as s:
        s.run(1200)
        s.macro(hold("Start", 10)); s.run(60)
        s.macro(hold("Start", 10)); s.run(60)
        s.macro(hold("Down", 3, 20)); s.run(20)
        for _ in range(3):
            s.macro(hold("Left", 3, 20)); s.run(20)
        for _ in range(3):
            s.macro(hold("Start", 10)); s.run(60)
        s.run(180)
        onfield = False
        for key in ("Start", "A", "Start", "A"):
            s.macro(hold(key, 3, 10))
            if parse(s, "kick") is not None:
                onfield = True
                print("KICKOFF_KEY", key, flush=True)
                break
        if not onfield:
            print("NO_FIELD", flush=True)
            return
        # 解除 KICK OFF 锁定：A 开球传球，直到坐标真的变化（活 play）
        s.run(120)
        live = False
        for _ in range(6):
            s.macro(hold("A", 3, 10))
            a = parse(s, "lv_a"); s.run(6); b = parse(s, "lv_b")
            if a != b:
                live = True
                break
        print("LIVE", live, flush=True)
        if not live:
            print("STILL_FROZEN", flush=True)
            return
        received = None
        timeline = []
        for i in range(90):
            p = parse(s, f"r{i:02d}")
            timeline.append({"i": i, **(p or {})})
            if cap_has(p):
                received = s.save(str(WORK / "received"))
                s.shot(str(WORK / "received"))
                print("RECEIVED_AT", i, "opp", p["opp_dist"], flush=True)
                break
            # 队友持球→要回传（先 A 后 B 两种都试）
            if p is not None and p["holder_team"] == 1 and p["holder_dist"] < 14:
                s.macro(hold("A" if i % 2 == 0 else "B", 3, 6))
            else:
                s.run(4)
        (WORK / "route_timeline.json").write_text(
            __import__("json").dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
        if received is None:
            print("NO_RECEIVE", flush=True)
            return
        pb = s.use_state(str(received))
        # 从接球瞬间同一干净状态，立即触发各变体；触发帧记录球权
        variants = [
            ("immB", [hold("B", 3, 0)]),
            ("immAB_B", [hold("A+B", 4, 0), hold("B", 3, 0)]),
            ("immRunB", [hold("Right", 6, 0), hold("B", 3, 0)]),
            ("teamB", [hold("B", 20, 0)]),
        ]
        for tag, chain in variants:
            s.load(pb)
            q0 = parse(s, f"{tag}_at")
            for m in chain:
                s.macro(m)
            q1 = parse(s, f"{tag}_post")
            print(tag, "AT_TRIGGER", None if q0 is None else (round(q0["dist"], 1), q0["holder_team"], q0["opp_dist"]),
                  "POST", None if q1 is None else (round(q1["dist"], 1), q1["holder_team"]), flush=True)
            prev = 0
            for t in (2, 6, 12, 20, 30, 42):
                s.run(t - prev); prev = t
                s.shot(str(WORK / f"{tag}_p{t:02d}"))
        print("USERROUTE_OK", WHICH, flush=True)


if __name__ == "__main__":
    main()