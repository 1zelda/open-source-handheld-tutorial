import sys, json, shutil
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe.statejump import StateSession
from taspipe import universal_authoring as UA

ROM = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\nekketsu_soccer_league_cn_jf.nes")
BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_scan_work")
OUT = Path(r"F:\taspipe_scratch\soccer2_possess_scan")
KICK = Path(r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\验证\t3_soccer2_moves\probe9_cn\kickoff.state")
OUT.mkdir(parents=True, exist_ok=True)

BALL_TILES = {0xC3, 0xC4, 0xC5, 0xD3, 0xD4, 0xD5}
LEG_TILES = {0x10, 0x11, 0x20, 0x21, 0x30, 0x31}


def parse(ram):
    spr = []
    for i in range(64):
        y, t, a, x = ram[0x200 + 4 * i : 0x204 + 4 * i]
        if y > 239:
            continue
        spr.append((i, y, t, a, x))
    marker = [s for s in spr if s[2] == 0xC0]
    ball = [s for s in spr if s[2] in BALL_TILES and (s[3] & 3) == 0]
    if not marker or len(ball) < 4:
        return None
    mx = marker[0][4] + 4
    legs = [s for s in spr if s[2] in LEG_TILES and abs(s[4] + 4 - mx) <= 10 and s[1] > marker[0][1]]
    if not legs:
        return None
    cy = max(s[1] for s in legs) + 8
    bx = min(s[4] for s in ball) + 8
    by = min(s[1] for s in ball) + 8
    # cluster remaining sprites into player groups by x proximity
    body = [s for s in spr if (s[3] & 3) in (1, 2, 3) and s[2] not in (0xC0,)]
    groups = []
    for s in sorted(body, key=lambda s: s[4]):
        for g in groups:
            if abs(g["x"] - (s[4] + 4)) <= 12 and abs(g["y"] - s[1]) <= 44:
                g["xs"].append(s[4] + 4)
                g["ys"].append(s[1])
                g["pal"].append(s[3] & 3)
                g["x"] = sum(g["xs"]) / len(g["xs"])
                g["y"] = sum(g["ys"]) / len(g["ys"])
                break
        else:
            groups.append({"x": s[4] + 4.0, "y": float(s[1]), "xs": [s[4] + 4], "ys": [s[1]], "pal": [s[3] & 3]})
    holder, hd = None, 1e9
    for g in groups:
        fy = max(g["ys"]) + 8
        d = ((g["x"] - bx) ** 2 + (fy - by) ** 2) ** 0.5
        if d < hd:
            hd, holder = d, g
    team = max(set(holder["pal"]), key=holder["pal"].count) if holder else -1
    return {"cap": (mx, cy), "ball": (bx, by), "dist": round(((mx - bx) ** 2 + (cy - by) ** 2) ** 0.5, 1),
            "holder_dist": round(hd, 1), "holder_team": team}


with StateSession(ROM, BH, work=WORK) as s:
    base = s.use_state(str(KICK))
    s.load(str(base))
    rows = []
    for i in range(40):
        s.run(30)
        rp = OUT / f"r{i:02d}.bin"
        s.ramdump(str(rp))
        p = parse(rp.read_bytes())
        rows.append({"i": i, "frame": (i + 1) * 30, **(p or {})})
        print(i, p, flush=True)
        if p and p["dist"] < 14:
            st = s.save(str(OUT / "possess_true"))
            s.shot(str(OUT / "possess_true.png"))
            print("POSSESSION_AT", i, st, flush=True)
            break
    (OUT / "scan.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("SCAN_OK", flush=True)