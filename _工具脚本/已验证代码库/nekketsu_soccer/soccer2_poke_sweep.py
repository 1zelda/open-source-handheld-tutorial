# -*- coding: utf-8 -*-
"""逐字节因果扫描：从 KICK OFF 冻结态出发，改一个字节，看精灵表哪里变了。

为什么可行：冻结态 60 帧内精灵表一字不变（soccer2_practice_setup.py 实测），
所以"写入后精灵表发生变化"就是因果证据，不需要相关系数、不怕摄像机偏移。
为什么跳过 $200-$2FF：那正是精灵 DMA 目标、也就是本脚本的观测口径，写它只改画法。

用法：python soccer2_poke_sweep.py [lo] [hi]      # 十六进制，默认 0 800
产物：F:\\taspipe_scratch\\soccer2_practice\\sweep.tsv（addr / 原值 / 新值 / 变化精灵数）
"""
import subprocess
import sys
import time
from pathlib import Path

BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_practice")
ROM = WORK / "rom.nes"
LUA = WORK / "sweep.lua"
TSV = WORK / "sweep.tsv"
LOG = WORK / "sweep_run.log"

TMPL = r'''
local dir = "__DIR__"
client.speedmode(400)
local st = dir .. "/field.state"
local lo, hi = __LO__, __HI__
local log = io.open(dir .. "/sweep.tsv", "w")
local W, K = 6, 6
local function snap()
	local t = {}
	for i = 0, 63 do
		local b = 0x200 + 4 * i
		local y = memory.read_u8(b) or 0
		local tile = memory.read_u8(b + 1) or 0
		local x = memory.read_u8(b + 3) or 0
		t[i] = y * 65536 + tile * 256 + x
	end
	return t
end
local function diff(a, b)
	local n = 0
	for i = 0, 63 do
		if a[i] ~= b[i] then n = n + 1 end
	end
	return n
end
local function advance(n)
	for i = 1, n do emu.frameadvance() end
end
savestate.load(st)
advance(W + K)
local base = snap()
savestate.load(st)
advance(W + K)
log:write(string.format("#ctrl_diff\t%d\n", diff(base, snap())))
log:flush()
for a = lo, hi - 1 do
	if not (a >= 0x200 and a <= 0x2FF) then
		savestate.load(st)
		advance(W)
		local orig = memory.read_u8(a) or 0
		local nv = (orig + 0x40) % 256
		memory.write_u8(a, nv)
		advance(K)
		local d = diff(base, snap())
		if d > 0 then
			log:write(string.format("%d\t%d\t%d\t%d\n", a, orig, nv, d))
			log:flush()
		end
	end
end
log:write("#done\n")
log:flush()
log:close()
client.exit()
'''


def run(lo=0x00, hi=0x800, timeout=1800.0):
    proc = subprocess.Popen([str(BH / "EmuHawk.exe"), "--chromeless", f"--lua={LUA}", str(ROM)],
                            cwd=str(BH), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if TSV.exists():
            txt = TSV.read_text(encoding="utf-8", errors="replace")
            if "#done" in txt:
                break
        if proc.poll() is not None:
            break
        time.sleep(1.0)
    if proc.poll() is None:
        proc.kill()
    txt = TSV.read_text(encoding="utf-8", errors="replace") if TSV.exists() else ""
    rows = [l.split("\t") for l in txt.splitlines() if l and not l.startswith("#")]
    ctrl = [l for l in txt.splitlines() if l.startswith("#ctrl_diff")]
    print(f"对照自检（不写入时精灵表变化数）：{ctrl}")
    print(f"命中地址 {len(rows)} 个 / 扫描 {hi - lo} 个")
    rows.sort(key=lambda r: -int(r[3]))
    for r in rows[:40]:
        a, orig, nv, d = int(r[0]), int(r[1]), int(r[2]), int(r[3])
        print(f"  $0x{a:03X}  {orig:#04x}->{nv:#04x}  变化精灵 {d} 条")
    print(f"→ {TSV}")
    return rows


if __name__ == "__main__":
    lo = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x00
    hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x800
    LUA.write_text(TMPL.replace("__DIR__", str(WORK).replace("\\", "/"))
                   .replace("__LO__", str(lo)).replace("__HI__", str(hi)),
                   encoding="utf-8", newline="\n")
    sys.stdout.reconfigure(encoding="utf-8")
    run(lo, hi)
