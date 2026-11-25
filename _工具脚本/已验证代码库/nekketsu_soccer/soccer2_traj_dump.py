# -*- coding: utf-8 -*-
"""整页 2KB 逐帧轨迹：按住 Right 带球跑，把每一帧的 2048 字节全存下来，离线找"会走的字节"。

11-15 结论：$314-$340 里只有 $314/$316/$318/$323 跟着球走，而且它们彼此贴合——
那是球自己的多份副本，人物坐标不在这段。所以要靠全页轨迹把人物坐标挖出来。

用法：python soccer2_traj_dump.py            # 跑一次，产物 traj.bin
      python soccer2_traj_analyze.py         # 只分析
产物：traj.bin（帧数 x 2048）+ traj_report.txt
"""
import subprocess
import sys
import time
from pathlib import Path

BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_practice")
LUA = WORK / "traj.lua"
BIN = WORK / "traj.bin"
META = WORK / "traj.meta"
ROM = WORK / "rom.nes"
STATE = WORK / "field.state"
FRAMES = 150

TMPL = r'''
local dir = "__DIR__"
local FRAMES = __FRAMES__
client.speedmode(400)
local out = io.open(dir .. "/traj.bin", "wb")
local meta = io.open(dir .. "/traj.meta", "w")
savestate.load(dir .. "/field.state")
emu.frameadvance()
for fr = 1, FRAMES do
	local inp
	if fr <= 3 then inp = {A = true}
	elseif fr > 5 and fr <= 75 then inp = {Right = true}
	elseif fr > 75 and fr <= 110 then inp = {Down = true}
	else inp = {} end
	joypad.set(inp, 1)
	emu.frameadvance()
	local chunk = {}
	for a = 0, 2047 do chunk[#chunk + 1] = string.char(memory.read_u8(a) or 0) end
	out:write(table.concat(chunk))
	meta:write(string.format("%d\t%d\t%d\t%d\t%d\n", fr,
		inp.Right and 1 or 0, inp.Down and 1 or 0, inp.A and 1 or 0, inp.B and 1 or 0))
end
out:close()
meta:write("#done\n")
meta:close()
client.exit()
'''


def run():
    LUA.write_text(TMPL.replace("__DIR__", str(WORK).replace("\\", "/"))
                   .replace("__FRAMES__", str(FRAMES)), encoding="utf-8", newline="\n")
    BIN.unlink(missing_ok=True)
    META.unlink(missing_ok=True)
    proc = subprocess.Popen([str(BH / "EmuHawk.exe"), "--chromeless", f"--lua={LUA}", str(ROM)],
                            cwd=str(BH), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 600
    while time.time() < deadline:
        if META.exists() and "#done" in META.read_text(encoding="utf-8", errors="replace"):
            break
        if proc.poll() is not None:
            break
        time.sleep(2.0)
    if proc.poll() is None:
        proc.kill()
    print(f"traj.bin = {BIN.stat().st_size if BIN.exists() else 0} 字节（应为 {FRAMES * 2048}）")


def signed_delta(a, b):
    d = (b - a) % 256
    return d - 256 if d > 128 else d


def analyze():
    raw = BIN.read_bytes()
    n = len(raw) // 2048
    frames = [raw[i * 2048:(i + 1) * 2048] for i in range(n)]
    meta = []
    for l in META.read_text(encoding="utf-8").splitlines():
        if not l or l.startswith("#"):
            continue
        p = l.split("\t")
        meta.append((int(p[1]), int(p[2])))          # Right, Down
    right = [i for i, (r, d) in enumerate(meta) if r == 1 and i + 1 < n]
    down = [i for i, (r, d) in enumerate(meta) if d == 1 and i + 1 < n]
    print(f"{n} 帧，Right {len(right)} 帧，Down {len(down)} 帧")
    res = []
    for a in range(2048):
        ser = [frames[i][a] for i in right]
        if len(set(ser)) < 4:
            continue
        dx = sum(signed_delta(ser[k], ser[k + 1]) for k in range(len(ser) - 1))
        ser_d = [frames[i][a] for i in down]
        dy = sum(signed_delta(ser_d[k], ser_d[k + 1]) for k in range(len(ser_d) - 1))
        steps = sum(1 for k in range(len(ser) - 1) if ser[k] != ser[k + 1])
        res.append({"addr": a, "dx": dx, "dy": dy, "steps": steps,
                    "distinct": len(set(ser)), "v0": ser[0]})
    movers = [r for r in res if abs(r["dx"]) >= 8 or abs(r["dy"]) >= 8]
    movers.sort(key=lambda r: -(abs(r["dx"]) + abs(r["dy"])))
    lines = [f"会走的字节：{len(movers)} 个（|Δ|>=8）"]
    for r in movers[:28]:
        ax = "X" if abs(r["dx"]) >= abs(r["dy"]) else "Y"
        lines.append(f"  ${r['addr']:03X} 起值{r['v0']:>3}  Right位移{r['dx']:>5}  Down位移{r['dy']:>5}"
                     f"  变化{r['steps']:>3}帧  轴{ax}")
    txt = "\n".join(lines)
    print(txt)
    (WORK / "traj_report.txt").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "analyze":
        analyze()
    else:
        run()
        analyze()
