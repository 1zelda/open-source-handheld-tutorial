# -*- coding: utf-8 -*-
"""A/B 实验：每帧把 $03F6-$0465（逐实体速度数组）清零，能不能把对手钉成雕像。

为什么要换路子（11-15 实测）：
  1) 比赛中球本来就贴在带球人脚下（写前 21px / 写后 8px，所有候选都一样），
     "黏球"这个需求本身不成立；
  2) $0314 在比赛里是只读输出量——写 20 个不同字节，6 帧后球全落回 (94,88)，
     说明球的位置由权威状态每帧重算，改它改不动。
所以真正的抓手是速度数组：$3F6=球，$3F8..$3FB 是 4 个不同的人（+0x40 各甩 +64px），
Y 在 X 之后 0x38 处（$42E=球Y，$431/$432/$433 与 $3F9/$3FA/$3FB 一一对应）。

判据：同样按住 Right 60 帧，对照段 vs 清零段，各人物团的位移。
      对手被钉住 = 那些团的位移 <= 8px，而 1P 的团仍然要走。
用法：python soccer2_statue_test.py
产物：statue.tsv（逐段逐团位移）+ shot_statue_{ctrl,patch}_f*.png
"""
import subprocess
import sys
import time
from pathlib import Path

BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_practice")
LUA = WORK / "statue.lua"
TSV = WORK / "statue.tsv"

TMPL = r'''
local dir = "__DIR__"
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
-- 人物团：腿/身贴图按 24px 邻接聚类，返回按 (x,y) 排序的团心列表
local function people(s)
	local pts = {}
	for _, v in ipairs(s) do
		if LEGT[v.tile] then pts[#pts + 1] = {v.x, v.y} end
	end
	local out = {}
	for _, p in ipairs(pts) do
		local hit
		for _, g in ipairs(out) do
			if math.abs(g.cx - p[1]) <= 24 and math.abs(g.cy - p[2]) <= 24 then
				g.n = g.n + 1
				g.cx = (g.cx * (g.n - 1) + p[1]) / g.n
				g.cy = (g.cy * (g.n - 1) + p[2]) / g.n
				hit = true
				break
			end
		end
		if not hit then out[#out + 1] = {cx = p[1], cy = p[2], n = 1} end
	end
	table.sort(out, function(a, b)
		if a.cy ~= b.cy then return a.cy < b.cy end
		return a.cx < b.cx
	end)
	return out
end
local function zero_vel()
	for a = 0x3F6, 0x465 do memory.write_u8(a, 0) end
end

local log = io.open(dir .. "/statue.tsv", "w")
log:write("phase\tframe\tidx\tcx\tcy\tball\n")
local function record(phase, f)
	local s = snap()
	local b = ball_of(s)
	local ppl = people(s)
	local bs = b and string.format("%d,%d", math.floor(b.x), math.floor(b.y)) or "none"
	for i, g in ipairs(ppl) do
		log:write(string.format("%s\t%d\t%d\t%d\t%d\t%s\n", phase, f, i,
			math.floor(g.cx), math.floor(g.cy), bs))
	end
end

-- 段1：对照。释放开球 + 向右带球 60 帧，全程不打补丁
savestate.load(dir .. "/field.state")
for fr = 1, 66 do
	local inp
	if fr <= 3 then inp = {A = true} elseif fr > 5 then inp = {Right = true} else inp = {} end
	joypad.set(inp, 1)
	emu.frameadvance()
	if fr % 10 == 0 then record("ctrl", fr) end
end
client.screenshot(dir .. "/shot_statue_ctrl_f060.png")
for i = 1, 8 do emu.frameadvance() end
savestate.save(dir .. "/live.state")

-- 段2：从同一个 live.state 出发，同样按 Right 60 帧，但每帧清零速度数组
savestate.load(dir .. "/live.state")
for fr = 1, 66 do
	local inp = {Right = true}
	zero_vel()
	joypad.set(inp, 1)
	emu.frameadvance()
	if fr % 10 == 0 then record("patch", fr) end
end
client.screenshot(dir .. "/shot_statue_patch_f060.png")
for i = 1, 8 do emu.frameadvance() end
log:write("#done\n")
log:close()
client.exit()
'''


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "analyze":
        if not (TSV.exists() and "#done" in TSV.read_text(encoding="utf-8", errors="replace")):
            raise SystemExit(f"{TSV} 没有 #done，先不带 analyze 跑一遍")
        report()
        return
    LUA.write_text(TMPL.replace("__DIR__", str(WORK).replace("\\", "/")),
                   encoding="utf-8", newline="\n")
    TSV.unlink(missing_ok=True)
    proc = subprocess.Popen([str(BH / "EmuHawk.exe"), "--chromeless", f"--lua={LUA}",
                             str(WORK / "rom.nes")], cwd=str(BH),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 420
    while time.time() < deadline:
        if TSV.exists() and "#done" in TSV.read_text(encoding="utf-8", errors="replace"):
            break
        if proc.poll() is not None:
            break
        time.sleep(2.0)
    if proc.poll() is None:
        proc.kill()
    report()


def report():
    txt = TSV.read_text(encoding="utf-8")
    if "#done" not in txt:
        raise SystemExit(f"没跑完：{TSV} 尾部 = {txt[-120:]!r}")
    per = {}
    for l in txt.splitlines():
        if not l or l.startswith("#") or l.startswith("phase"):
            continue
        ph, f, idx, cx, cy, ball = l.split("\t")
        per.setdefault(ph, {}).setdefault(int(f), []).append(
            (int(idx), int(cx), int(cy), ball))
    for ph in ("ctrl", "patch"):
        frames = sorted(per.get(ph, {}))
        if len(frames) < 2:
            print(f"{ph}: 采样不足 {frames}")
            continue
        f0, f1 = frames[0], frames[-1]
        g0 = {i: (x, y) for i, x, y, _ in per[ph][f0]}
        print(f"\n[{ph}] f{f0} -> f{f1} 各人物团位移：")
        moved = 0
        for i, x, y, _ in per[ph][f1]:
            if i in g0:
                dx, dy = x - g0[i][0], y - g0[i][1]
            else:
                dx, dy = 0, 0
            d = max(abs(dx), abs(dy))
            if d > 8:
                moved += 1
            print(f"   团{i:>2} ({x:>3},{y:>3})  位移=({dx:>4},{dy:>4})  {'走' if d > 8 else '钉住'}")
        print(f"   → 会动的团 {moved} 个 / 共 {len(per[ph][f1])} 个"
              f"   球 f{f0}={per[ph][f0][0][3]} f{f1}={per[ph][f1][0][3]}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
