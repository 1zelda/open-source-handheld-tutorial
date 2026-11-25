# -*- coding: utf-8 -*-
"""行为判据找 1P 坐标：把候选字节写进球的位置($314)，看球落到谁身上。

前一版拿"数值接近"当证据是错的——$07xx 那几个字节只是数值凑巧落在球的区间里。
这版只看结果：写入后球与最近人物的屏幕距离。
  阴性对照 = 把球自己的另一份副本($316)写回 $314，距离应基本不变；
  阳性 = 某个候选写进去之后球贴到人物脚下（距离 <= 8px）。

用法：python soccer2_glue_find.py
产物：glue_find.tsv + shots_find_*.png
"""
import subprocess
import sys
import time
from pathlib import Path

BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_practice")
LUA = WORK / "glue_find.lua"
TSV = WORK / "glue_find.tsv"

CAND = [0x02C, 0x034, 0x1F6, 0x1F3, 0x045, 0x046, 0x025, 0x725,
        0x021, 0x02D, 0x030, 0x01F, 0x1E3, 0x1F2, 0x1FA, 0x301, 0x303,
        0x316, 0x318, 0x323]      # 后三个是球自己的副本 = 阴性对照

TMPL = r'''
local dir = "__DIR__"
local CAND = {__CAND__}
client.speedmode(400)
local BALLT = {[195]=1,[196]=1,[197]=1,[211]=1,[212]=1,[213]=1}
local LEGT  = {[16]=1,[17]=1,[32]=1,[33]=1,[48]=1,[49]=1}
local function rd(a) return memory.read_u8(a) or 0 end
local function snap()
	local t = {}
	for i = 0, 63 do
		local b = 0x200 + 4 * i
		t[#t + 1] = {y = rd(b), tile = rd(b + 1), attr = rd(b + 2), x = rd(b + 3)}
	end
	return t
end
local function ball_of(s)
	local x0, y0, x1, y1, n = 255, 255, 0, 0, 0
	for _, v in ipairs(s) do
		if BALLT[v.tile] and (v.attr % 4) == 0 then
			n = n + 1
			if v.x < x0 then x0 = v.x end
			if v.y < y0 then y0 = v.y end
			if v.x > x1 then x1 = v.x end
			if v.y > y1 then y1 = v.y end
		end
	end
	if n < 4 then return nil end
	return {x = (x0 + x1) / 2 + 4, y = (y0 + y1) / 2 + 4}
end
local function people(s)
	local pts = {}
	for _, v in ipairs(s) do
		if LEGT[v.tile] then pts[#pts + 1] = {v.x, v.y} end
	end
	local out = {}
	for _, p in ipairs(pts) do
		local hit
		for _, g in ipairs(out) do
			if math.abs(g.cx - p[1]) <= 20 and math.abs(g.cy - p[2]) <= 20 then
				g.n = g.n + 1
				g.cx = (g.cx * (g.n - 1) + p[1]) / g.n
				g.cy = (g.cy * (g.n - 1) + p[2]) / g.n
				hit = true
				break
			end
		end
		if not hit then out[#out + 1] = {cx = p[1], cy = p[2], n = 1} end
	end
	return out
end
local function mind(b, ppl)
	local best = 9999
	for _, g in ipairs(ppl) do
		local d = math.floor(math.abs(g.cx - b.x) + math.abs(g.cy - b.y))
		if d < best then best = d end
	end
	return best
end

savestate.load(dir .. "/field.state")
-- 释放开球 + 向右带球 60 帧，存成"比赛中"基线
for fr = 1, 66 do
	local inp
	if fr <= 3 then inp = {A = true} elseif fr > 5 then inp = {Right = true} else inp = {} end
	joypad.set(inp, 1)
	emu.frameadvance()
end
savestate.save(dir .. "/dribble.state")

local log = io.open(dir .. "/glue_find.tsv", "w")
log:write("case\taddr\tval\tdist0\tdist6\tball\tppl\n")
for _, c in ipairs(CAND) do
	savestate.load(dir .. "/dribble.state")
	emu.frameadvance()
	emu.frameadvance()
	local s0 = snap()
	local b0 = ball_of(s0)
	local d0 = b0 and mind(b0, people(s0)) or -1
	local v = rd(c)
	memory.write_u8(0x314, v)
	for i = 1, 6 do emu.frameadvance() end
	local s1 = snap()
	local b1 = ball_of(s1)
	local ppl = people(s1)
	local d1 = b1 and mind(b1, ppl) or -1
	local bs = b1 and string.format("%d,%d", math.floor(b1.x), math.floor(b1.y)) or "none"
	log:write(string.format("%s\t%d\t%d\t%d\t%d\t%s\t%d\n",
		c >= 0x314 and "CTRL" or "CAND", c, v, d0, d1, bs, #ppl))
	log:flush()
	if c < 0x314 then
		client.screenshot(dir .. "/shot_find_" .. string.format("%03X", c) .. ".png")
		for i = 1, 6 do emu.frameadvance() end
	end
end
log:write("#done\n")
log:close()
client.exit()
'''


def main():
    src = TMPL.replace("__DIR__", str(WORK).replace("\\", "/"))
    src = src.replace("__CAND__", ",".join(str(c) for c in CAND))
    LUA.write_text(src, encoding="utf-8", newline="\n")
    TSV.unlink(missing_ok=True)
    proc = subprocess.Popen([str(BH / "EmuHawk.exe"), "--chromeless", f"--lua={LUA}",
                             str(WORK / "rom.nes")], cwd=str(BH),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 600
    while time.time() < deadline:
        if TSV.exists() and "#done" in TSV.read_text(encoding="utf-8", errors="replace"):
            break
        if proc.poll() is not None:
            break
        time.sleep(2.0)
    if proc.poll() is None:
        proc.kill()
    rows = [l.split("\t") for l in TSV.read_text(encoding="utf-8").splitlines()
            if l and not l.startswith("#") and not l.startswith("case")]
    print(f"{'类':>5} {'地址':>6} {'写入值':>6} {'写前距离':>8} {'写后距离':>8}  球屏幕位")
    good = []
    for kind, addr, val, d0, d1, bs, np_ in rows:
        a = int(addr)
        print(f"{kind:>5} ${a:03X} {val:>6} {d0:>8} {d1:>8}  ({bs}) 人数{np_}")
        if kind == "CAND" and int(d1) <= 8:
            good.append(a)
    print(f"\n阴性对照(球副本写回球)写后距离 = "
          f"{[r[4] for r in rows if r[0] == 'CTRL']}")
    print(f"把球贴到人物脚下的候选：{[hex(g) for g in good] or '无'}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
