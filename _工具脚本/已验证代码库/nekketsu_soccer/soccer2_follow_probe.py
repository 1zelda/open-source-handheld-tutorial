# -*- coding: utf-8 -*-
"""找 1P 的坐标字节：带球向右跑，看哪些字节和球($314)一起走、且始终贴在一起。

黏球的正确做法是"字段→字段"（球的位置写成人物的位置），因为镜头跟着球跑，
往球的位置里写屏幕坐标只会把整个世界推走（11-15 GLUE 实测：球屏幕 x 一直卡在
80-95，间距 30-63px，完全没黏住）。所以先要拿到 1P 自己的坐标字节。

判据：跑动中 |byte - $314| <= 8 的帧占比 >= 80%，且该字节随 Right 单调增长。
用法：python soccer2_follow_probe.py
产物：follow.csv（逐帧 48 个字节）+ follow_report.txt
"""
import subprocess
import sys
import time
from pathlib import Path

BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_practice")
LUA = WORK / "follow.lua"
CSV = WORK / "follow.csv"
ROM = WORK / "rom.nes"
STATE = WORK / "field.state"

LO, HI = 0x314, 0x340
FRAMES = 140

TMPL = r'''
local dir = "__DIR__"
local LO, HI, FRAMES = __LO__, __HI__, __FRAMES__
client.speedmode(400)
local f = io.open(dir .. "/follow.csv", "w")
f:write("frame\tA\tB\tR\tD\tbytes\n")
savestate.load(dir .. "/field.state")
emu.frameadvance()
for fr = 1, FRAMES do
	local inp
	if fr <= 3 then inp = {A = true}
	elseif fr > 5 and fr <= 70 then inp = {Right = true}
	else inp = {} end
	joypad.set(inp, 1)
	emu.frameadvance()
	local chunk = {}
	for a = LO, HI do chunk[#chunk + 1] = tostring(memory.read_u8(a) or 0) end
	f:write(string.format("%d\t%d\t%d\t%d\t%d\t%s\n", fr,
		inp.A and 1 or 0, inp.B and 1 or 0, inp.Right and 1 or 0, inp.Down and 1 or 0,
		table.concat(chunk, ",")))
end
f:write("#done\n")
f:close()
client.exit()
'''


def main():
    LUA.write_text(TMPL.replace("__DIR__", str(WORK).replace("\\", "/"))
                   .replace("__LO__", str(LO)).replace("__HI__", str(HI))
                   .replace("__FRAMES__", str(FRAMES)), encoding="utf-8", newline="\n")
    CSV.unlink(missing_ok=True)
    proc = subprocess.Popen([str(BH / "EmuHawk.exe"), "--chromeless", f"--lua={LUA}", str(ROM)],
                            cwd=str(BH), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 420
    while time.time() < deadline:
        if CSV.exists() and "#done" in CSV.read_text(encoding="utf-8", errors="replace"):
            break
        if proc.poll() is not None:
            break
        time.sleep(2.0)
    if proc.poll() is None:
        proc.kill()
    rows = []
    for l in CSV.read_text(encoding="utf-8").splitlines()[1:]:
        if not l or l.startswith("#"):
            continue
        p = l.split("\t")
        rows.append((int(p[0]), int(p[3]), [int(v) for v in p[5].split(",")]))
    win = [r for r in rows if r[1] == 1]          # 只在"按住 Right"的帧上判
    print(f"共 {len(rows)} 帧，其中按住 Right {len(win)} 帧")
    ball = LO
    bi = ball - LO
    out = []
    for off in range(HI - LO):
        addr = LO + off
        ser = [r[2][bi] for r in win]            # 球的序列
        cand = [r[2][off] for r in win]
        near = sum(1 for s, c in zip(ser, cand) if abs(((c - s + 128) % 256) - 128) <= 8)
        frac = near / max(1, len(ser))
        moved = len(set(cand))
        out.append((frac, moved, addr))
    out.sort(reverse=True)
    print("贴合球(±8px)的帧占比 / 取值种数 / 地址：")
    lines = []
    for frac, moved, addr in out[:12]:
        s = f"  ${addr:03X}  贴合 {frac * 100:5.1f}%  取值 {moved:>3} 种"
        print(s)
        lines.append(s)
    rep = WORK / "follow_report.txt"
    rep.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ {rep}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
