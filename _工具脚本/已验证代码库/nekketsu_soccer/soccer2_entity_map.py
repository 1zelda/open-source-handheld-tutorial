# -*- coding: utf-8 -*-
"""给每个字节起名字：写入后，屏幕上"哪一团精灵"跳到了哪里。

输出每行 = 地址 / 原值 / 动了几条精灵 / 那团精灵原来的屏幕位置 / 它的位移。
按"原位置"聚类就能得到每个实体的 x、y 地址；按位移正负能定轴向。
用法：python soccer2_entity_map.py [lo] [hi]     # 默认 0300 0500
产物：F:\\taspipe_scratch\\soccer2_practice\\entity_map.tsv + entity_map.json
"""
import json
import subprocess
import sys
import time
from pathlib import Path

BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_practice")
LUA = WORK / "emap.lua"
TSV = WORK / "entity_map.tsv"
JSON = WORK / "entity_map.json"

TMPL = r'''
local dir = "__DIR__"
local lo, hi = __LO__, __HI__
client.speedmode(400)
local st = dir .. "/field.state"
local log = io.open(dir .. "/entity_map.tsv", "w")
local W, K = 6, 6
local function snap()
	local t = {}
	for i = 0, 63 do
		local b = 0x200 + 4 * i
		t[i] = {y = memory.read_u8(b) or 0, tile = memory.read_u8(b + 1) or 0,
		        attr = memory.read_u8(b + 2) or 0, x = memory.read_u8(b + 3) or 0}
	end
	return t
end
local function advance(n)
	for i = 1, n do emu.frameadvance() end
end
savestate.load(st)
advance(W + K)
local base = snap()
for a = lo, hi - 1 do
	if not (a >= 0x200 and a <= 0x2FF) then
		savestate.load(st)
		advance(W)
		local orig = memory.read_u8(a) or 0
		memory.write_u8(a, (orig + 0x40) % 256)
		advance(K)
		local now = snap()
		local moved = {}
		for i = 0, 63 do
			local p, q = base[i], now[i]
			if p.y ~= q.y or p.tile ~= q.tile or p.x ~= q.x then
				moved[#moved + 1] = {i = i, x = p.x, y = p.y, dx = q.x - p.x, dy = q.y - p.y}
			end
		end
		if #moved > 0 then
			-- 取"整团一起跳"的主簇：位移相同的条目归一组，选最大组
			local groups = {}
			for _, m in ipairs(moved) do
				local key = m.dx .. "/" .. m.dy
				groups[key] = groups[key] or {}
				table.insert(groups[key], m)
			end
			local best, bk = nil, nil
			for key, g in pairs(groups) do
				if not best or #g > #best then best, bk = g, key end
			end
			local x0, y0 = 999, 999
			for _, m in ipairs(best) do
				if m.x < x0 then x0 = m.x end
				if m.y < y0 then y0 = m.y end
			end
			local dxs, dys = bk:match("^(%-?%d+)/(%-?%d+)$")
			log:write(string.format("%d\t%d\t%d\t%d\t%d\t%s\t%s\t%d\n",
				a, orig, #moved, x0, y0, dxs, dys, #best))
			log:flush()
		end
	end
end
log:write("#done\n")
log:close()
client.exit()
'''


def main():
    lo = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x300
    hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x500
    LUA.write_text(TMPL.replace("__DIR__", str(WORK).replace("\\", "/"))
                   .replace("__LO__", str(lo)).replace("__HI__", str(hi)),
                   encoding="utf-8", newline="\n")
    TSV.unlink(missing_ok=True)
    proc = subprocess.Popen([str(BH / "EmuHawk.exe"), "--chromeless", f"--lua={LUA}",
                             str(WORK / "rom.nes")], cwd=str(BH),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 900
    while time.time() < deadline:
        if TSV.exists() and "#done" in TSV.read_text(encoding="utf-8", errors="replace"):
            break
        if proc.poll() is not None:
            break
        time.sleep(2.0)
    if proc.poll() is None:
        proc.kill()
    rows = []
    for l in TSV.read_text(encoding="utf-8").splitlines():
        if not l or l.startswith("#"):
            continue
        a, orig, n, x0, y0, dx, dy, cn = l.split("\t")
        rows.append({"addr": int(a), "hex": f"$0x{int(a):03X}", "orig": int(orig),
                     "moved": int(n), "at": [int(x0), int(y0)],
                     "d": [int(dx), int(dy)], "cluster": int(cn)})
    # 按"原来在哪"聚类：同一实体的 x 字节和 y 字节会指向同一团精灵
    by_pos = {}
    for r in rows:
        bx = (r["at"][0] // 24, r["at"][1] // 24)
        by_pos.setdefault(bx, []).append(r)
    print(f"{len(rows)} 个有效地址，聚成 {len(by_pos)} 团（按 24px 网格）")
    ents = []
    for cell, lst in sorted(by_pos.items(), key=lambda kv: -len(kv[1])):
        ax = [r["hex"] for r in lst if r["d"][0] != 0 and r["d"][1] == 0]
        ay = [r["hex"] for r in lst if r["d"][1] != 0 and r["d"][0] == 0]
        other = [r["hex"] for r in lst if r not in ([] if not ax else []) ]
        ents.append({"cell": list(cell), "at": lst[0]["at"], "n_rows": len(lst),
                     "x_bytes": ax, "y_bytes": ay,
                     "all": [(r["hex"], r["d"], r["moved"]) for r in lst]})
    for e in ents[:18]:
        print(f"  屏幕团≈{e['at']} 记录 {e['n_rows']} 行  x字节={e['x_bytes'][:6]}  y字节={e['y_bytes'][:6]}")
        for hexv, d, mv in e["all"][:6]:
            print(f"      {hexv} 位移={tuple(d)} 动{mv}条")
    JSON.write_text(json.dumps(ents, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {JSON}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
