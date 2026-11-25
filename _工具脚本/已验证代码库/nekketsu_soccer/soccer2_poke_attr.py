# -*- coding: utf-8 -*-
"""命中地址的归因：每次只 +1，量"球动了几个像素""哪些人动了""是不是全体平移（镜头）"。

sweep.tsv 只回答"有没有因果"，这轮回答"是谁的坐标"：
  ball_dx/dy     = 球精灵（tile 195/196/197/211/212/213 且调色板 0）的位移
  n_moved        = 位移非零的精灵条目数
  modal_dx/dy    = 所有位移精灵的众数位移（全体同向 = 镜头滚动，不是实体坐标）
用法：python soccer2_poke_attr.py [tsv]
产物：F:\\taspipe_scratch\\soccer2_practice\\attr.tsv + attr_table.json
"""
import json
import subprocess
import sys
import time
from pathlib import Path

BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_practice")
LUA = WORK / "attr.lua"
OUT = WORK / "attr.tsv"
JSON = WORK / "attr_table.json"

TMPL = r'''
local dir = "__DIR__"
local addrs = {__ADDRS__}
client.speedmode(400)
local st = dir .. "/field.state"
local log = io.open(dir .. "/attr.tsv", "w")
local W, K = 6, 6
local BALL = {[195]=1,[196]=1,[197]=1,[211]=1,[212]=1,[213]=1}
local function snap()
	local xs, ys, tiles, pal = {}, {}, {}, {}
	local bx, by = nil, nil
	for i = 0, 63 do
		local b = 0x200 + 4 * i
		local y = memory.read_u8(b) or 0
		local tile = memory.read_u8(b + 1) or 0
		local a = memory.read_u8(b + 2) or 0
		local x = memory.read_u8(b + 3) or 0
		xs[i], ys[i], tiles[i], pal[i] = x, y, tile, a % 4
		if BALL[tile] and a % 4 == 0 then
			if bx == nil or x < bx then bx = x end
			if by == nil or y < by then by = y end
		end
	end
	return {xs = xs, ys = ys, tiles = tiles, bx = bx, by = by}
end
local function advance(n)
	for i = 1, n do emu.frameadvance() end
end
savestate.load(st)
advance(W + K)
local base = snap()
log:write(string.format("#base_ball\t%s\t%s\n", tostring(base.bx), tostring(base.by)))
for _, a in ipairs(addrs) do
	savestate.load(st)
	advance(W)
	local orig = memory.read_u8(a) or 0
	memory.write_u8(a, (orig + 1) % 256)
	advance(K)
	local s = snap()
	local moved, dxs, dys = 0, {}, {}
	for i = 0, 63 do
		local dx = s.xs[i] - base.xs[i]
		local dy = s.ys[i] - base.ys[i]
		if dx ~= 0 or dy ~= 0 then
			moved = moved + 1
			dxs[dx] = (dxs[dx] or 0) + 1
			dys[dy] = (dys[dy] or 0) + 1
		end
	end
	local function modal(t)
		local best, n = 0, -1
		for k, v in pairs(t) do
			if v > n then n, best = v, k end
		end
		return best, n
	end
	local mdx, cnx = modal(dxs)
	local mdy, cny = modal(dys)
	local bdx = (s.bx and base.bx) and (s.bx - base.bx) or -99
	local bdy = (s.by and base.by) and (s.by - base.by) or -99
	log:write(string.format("%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\n",
		a, orig, bdx, bdy, moved, mdx, mdy, cnx))
	log:flush()
end
log:write("#done\n")
log:close()
client.exit()
'''


def main(tsv=None):
    tsv = Path(tsv or (WORK / "sweep.tsv"))
    rows = [l.split("\t") for l in tsv.read_text(encoding="utf-8").splitlines()
            if l and not l.startswith("#")]
    addrs = sorted({int(r[0]) for r in rows})
    print(f"归因 {len(addrs)} 个命中地址（每个 +1 像素级写入）")
    LUA.write_text(TMPL.replace("__DIR__", str(WORK).replace("\\", "/"))
                   .replace("__ADDRS__", ",".join(str(a) for a in addrs)),
                   encoding="utf-8", newline="\n")
    OUT.unlink(missing_ok=True)
    proc = subprocess.Popen([str(BH / "EmuHawk.exe"), "--chromeless", f"--lua={LUA}",
                             str(WORK / "rom.nes")], cwd=str(BH),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 600
    while time.time() < deadline:
        if OUT.exists() and "#done" in OUT.read_text(encoding="utf-8", errors="replace"):
            break
        if proc.poll() is not None:
            break
        time.sleep(1.0)
    if proc.poll() is None:
        proc.kill()
    lines = [l for l in OUT.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    table = []
    for l in lines:
        a, orig, bdx, bdy, moved, mdx, mdy, cnx = [int(x) for x in l.split("\t")]
        if bdx == 0 and bdy == 0 and moved == 0:
            kind = "无可见效应（+1 太小）"
        elif abs(mdx) <= 1 and abs(mdy) <= 1 and moved >= 40:
            kind = "镜头/全局（全体平移）"
        elif bdx != 0 or bdy != 0:
            kind = "球坐标"
        else:
            kind = f"实体坐标（{moved} 条精灵）"
        table.append({"addr": a, "hex": f"$0x{a:03X}", "orig": orig, "ball_dx": bdx,
                      "ball_dy": bdy, "moved": moved, "modal_dx": mdx, "modal_dy": mdy,
                      "modal_count": cnx, "kind": kind})
    table.sort(key=lambda r: (r["kind"], -r["moved"]))
    for r in table:
        print(f"  {r['hex']} 球Δ=({r['ball_dx']:+d},{r['ball_dy']:+d}) 动精灵={r['moved']:2} "
              f"众数Δ=({r['modal_dx']:+d},{r['modal_dy']:+d})×{r['modal_count']}  {r['kind']}")
    JSON.write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {JSON}")
    return table


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1] if len(sys.argv) > 1 else None)
