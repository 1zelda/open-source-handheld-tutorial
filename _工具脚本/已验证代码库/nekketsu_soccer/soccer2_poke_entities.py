# -*- coding: utf-8 -*-
"""把命中地址按"动了哪几条精灵"聚类 ⇒ 每个簇 = 一个实体（球员/球/镜头）。

写入量用 +0x40（64 像素）而不是 +1：位移够大，簇不会被动画抖动混在一起。
用法：python soccer2_poke_entities.py
产物：F:\\taspipe_scratch\\soccer2_practice\\entities.json（簇 → 地址表 + 该实体屏幕坐标）
"""
import json
import subprocess
import sys
import time
from pathlib import Path

BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_practice")
LUA = WORK / "ent.lua"
OUT = WORK / "entities.tsv"
JSON = WORK / "entities.json"

TMPL = r'''
local dir = "__DIR__"
local addrs = {__ADDRS__}
client.speedmode(400)
local st = dir .. "/field.state"
local log = io.open(dir .. "/entities.tsv", "w")
local W, K = 6, 6
local function snap()
	local t = {}
	for i = 0, 63 do
		local b = 0x200 + 4 * i
		t[i] = {memory.read_u8(b) or 0, memory.read_u8(b + 1) or 0,
		        memory.read_u8(b + 2) or 0, memory.read_u8(b + 3) or 0}
	end
	return t
end
local function moved_ids(a, b)
	local out = {}
	for i = 0, 63 do
		if a[i][1] ~= b[i][1] or a[i][2] ~= b[i][2] or a[i][4] ~= b[i][4] then
			out[#out + 1] = i
		end
	end
	return out
end
local function bbox(a, ids)
	local x0, x1, y0, y1 = 999, -1, 999, -1
	for _, i in ipairs(ids) do
		if a[i][4] < x0 then x0 = a[i][4] end
		if a[i][4] > x1 then x1 = a[i][4] end
		if a[i][1] < y0 then y0 = a[i][1] end
		if a[i][1] > y1 then y1 = a[i][1] end
	end
	return x0, y0, x1, y1
end
local function advance(n)
	for i = 1, n do emu.frameadvance() end
end
savestate.load(st)
advance(W + K)
local base = snap()
for _, a in ipairs(addrs) do
	savestate.load(st)
	advance(W)
	local orig = memory.read_u8(a) or 0
	memory.write_u8(a, (orig + 0x40) % 256)
	advance(K)
	local ids = moved_ids(base, snap())
	local x0, y0, x1, y1 = bbox(base, ids)
	local parts = {}
	for _, i in ipairs(ids) do parts[#parts + 1] = tostring(i) end
	log:write(string.format("%d\t%d\t%s\t%d\t%d\t%d\t%d\n", a, orig,
		table.concat(parts, ","), x0, y0, x1, y1))
	log:flush()
end
log:write("#done\n")
log:close()
client.exit()
'''


def main():
    rows = [l.split("\t") for l in (WORK / "sweep.tsv").read_text(encoding="utf-8")
            .splitlines() if l and not l.startswith("#")]
    addrs = sorted({int(r[0]) for r in rows})
    LUA.write_text(TMPL.replace("__DIR__", str(WORK).replace("\\", "/"))
                   .replace("__ADDRS__", ",".join(str(a) for a in addrs)),
                   encoding="utf-8", newline="\n")
    OUT.unlink(missing_ok=True)
    proc = subprocess.Popen([str(BH / "EmuHawk.exe"), "--chromeless", f"--lua={LUA}",
                             str(WORK / "rom.nes")], cwd=str(BH),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 900
    while time.time() < deadline:
        if OUT.exists() and "#done" in OUT.read_text(encoding="utf-8", errors="replace"):
            break
        if proc.poll() is not None:
            break
        time.sleep(1.0)
    if proc.poll() is None:
        proc.kill()
    lines = [l.split("\t") for l in OUT.read_text(encoding="utf-8").splitlines()
             if l and not l.startswith("#")]
    print(f"跑完 {len(lines)}/{len(addrs)} 个地址")
    groups = {}
    for a, orig, ids, x0, y0, x1, y1 in lines:
        box = (int(x0), int(y0)) if ids else None
        groups.setdefault((ids, box), []).append((int(a), int(orig)))
    table = []
    for (ids, box), lst in sorted(groups.items(), key=lambda kv: -len(kv[0][0])):
        n = len(ids.split(",")) if ids else 0
        table.append({"sprite_ids": ids, "n_sprites": n, "screen_xy": list(box) if box else None,
                      "addrs": [a for a, _ in lst],
                      "hexes": [f"$0x{a:03X}" for a, _ in lst]})
    table.sort(key=lambda r: -r["n_sprites"])
    print(f"聚成 {len(table)} 类（按动多少条精灵）：")
    for r in table[:24]:
        loc = f"屏幕({r['screen_xy'][0]},{r['screen_xy'][1]})" if r["screen_xy"] else "全体/无"
        print(f"  动 {r['n_sprites']:2} 条 × {len(r['addrs']):2} 址  {loc:16} "
              f"{' '.join(r['hexes'][:10])}")
    JSON.write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {JSON}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
