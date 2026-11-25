# -*- coding: utf-8 -*-
"""练习态验证：把球钉在被控人脚下（只用已证实的字节）。

已证实（11-15 因果扫描 + 逐字节归因，冻结基线零漂移）：
  $0314 = 球 X，写 +1 → 屏幕球 +1px（1:1）
  $0386 = 球 Y，写 +1 → 屏幕球 -1px（反向）
  $0F0/$0F2 = 镜头 X/Y
  $03F6/$042E 那块是速度/位移数组（冻结态原值全 0，+0x40 会把人甩出 ~64px），不是坐标
所以"黏球"只能在屏幕系做：每帧读精灵影子拿球与人的屏幕坐标，把差值补进 $0314/$0386。

用法：python soccer2_glue_test.py [GLUE|OFF]
产物：glue_<mode>.tsv（逐帧球/人屏幕坐标与间距）+ shots_glue_<mode>_*.png
"""
import subprocess
import sys
import time
from pathlib import Path

BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_practice")
ROM = WORK / "rom.nes"
STATE = WORK / "field.state"
LUA = WORK / "glue.lua"

TMPL = r'''
local dir   = "__DIR__"
local mode  = "__MODE__"
local FRAMES = 150
client.speedmode(400)

local BALLT = {[195]=1,[196]=1,[197]=1,[211]=1,[212]=1,[213]=1}
local LEGT  = {[16]=1,[17]=1,[32]=1,[33]=1,[48]=1,[49]=1}

local function rd(a) return memory.read_u8(a) or 0 end
local function wr(a,v) memory.write_u8(a, v % 256) end

local function snap()
	local t = {}
	for i = 0, 63 do
		local b = 0x200 + 4 * i
		t[#t + 1] = {y = rd(b), tile = rd(b + 1), attr = rd(b + 2), x = rd(b + 3)}
	end
	return t
end

-- 球：4 块以上球贴图才认（和生产侧 soccer2_oam_parse 同一判据）
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
	return {x = (x0 + x1) / 2 + 4, y = (y0 + y1) / 2 + 4, n = n}
end

-- 人：腿/身贴图按 20px 邻接聚类
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

local function shot(name)
	local p = dir .. "/shot_" .. mode .. "_" .. name .. ".png"
	client.screenshot(p)
	local tries = 0
	while tries < 40 do
		emu.frameadvance()
		tries = tries + 1
		local f = io.open(p, "rb")
		if f then
			local ok = f:read("*a") or ""
			f:close()
			if string.find(ok, "IEND", 1, true) then break end
		end
	end
	return p
end

local log = io.open(dir .. "/glue_" .. mode .. ".tsv", "w")
savestate.load(STATE_PATH)
emu.frameadvance()

local prev_ball, still, cool = nil, 0, 0
for f = 1, FRAMES do
	local inp = {}
	if f <= 3 then
		inp = {A = true}                 -- 释放 KICK OFF
	elseif f > 6 and f <= 60 then
		inp = {Right = true}             -- 带球跑：黏球期
	elseif f > 60 and f <= 66 then
		inp = {B = true}                 -- 射门：黏球必须松手，否则球永远飞不出去
	elseif f > 66 and f <= 120 then
		inp = {}
	else
		inp = {Right = true}
	end
	if f == 61 then cool = 90 end        -- 射门后 90 帧不干预

	local s = snap()
	local b = ball_of(s)
	local ppl = people(s)
	local tgt, bestd = nil, 9999
	for _, g in ipairs(ppl) do
		if b then
			local d = math.abs(g.cx - b.x) + math.abs(g.cy - b.y)
			if d < bestd then tgt, bestd = g, d end
		end
	end
	-- 绝对写入：屏幕球位 = (字段 - 镜头) + 12（11-15 实测 f=60 精确命中）
	-- 上一版每帧补"全部误差"，一帧 15px 连补 60 帧把球甩出场外 → 死锁，已否。
	if mode == "GLUE" and b and tgt and cool <= 0 then
		local want = math.floor(tgt.cx) - 12 + rd(0x0F0)
		wr(0x314, want % 256)
	end
	if cool > 0 then cool = cool - 1 end
	local raw = 0
	for _, v in ipairs(s) do
		if BALLT[v.tile] then raw = raw + 1 end
	end
	local mk = 0
	for _, v in ipairs(s) do
		if v.tile == 0xC0 then mk = mk + 1 end
	end
	-- 静止探测：球连续 45 帧不动 = 回开球/进球死锁
	if b and prev_ball then
		if math.abs(b.x - prev_ball.x) < 1 and math.abs(b.y - prev_ball.y) < 1 and f > 10 then
			still = still + 1
		else
			still = 0
		end
	end
	if b then prev_ball = b end
	if still >= 45 then inp = {A = true}; still = 0 end

	joypad.set(inp, 1)
	emu.frameadvance()

	if f % 10 == 0 then
		local bs = b and string.format("%d,%d", math.floor(b.x), math.floor(b.y)) or "none"
		local ts = tgt and string.format("%d,%d", math.floor(tgt.cx), math.floor(tgt.cy)) or "none"
		log:write(string.format("%d\t%s\t%s\t%s\t%d\t%d\t%d\t%d\t%d\n",
			f, bs, ts, mode, #ppl, rd(0x314), rd(0x0F0), mk, raw))
		log:flush()
	end
	if f == 30 or f == 55 or f == 75 or f == 95 or f == 130 then shot(string.format("f%03d", f)) end
end
log:write("#done\n")
log:close()
client.exit()
'''


def main():
    mode = sys.argv[1].upper() if len(sys.argv) > 1 else "GLUE"
    assert mode in ("GLUE", "OFF"), mode
    src = (TMPL.replace("__DIR__", str(WORK).replace("\\", "/"))
                .replace("__MODE__", mode))
    src = 'local STATE_PATH = "%s"\n' % str(STATE).replace("\\", "/") + src
    LUA.write_text(src, encoding="utf-8", newline="\n")
    tsv = WORK / f"glue_{mode}.tsv"
    tsv.unlink(missing_ok=True)
    for p in WORK.glob(f"shot_{mode}_*.png"):
        p.unlink()
    proc = subprocess.Popen([str(BH / "EmuHawk.exe"), "--chromeless", f"--lua={LUA}", str(ROM)],
                            cwd=str(BH), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 420
    while time.time() < deadline:
        if tsv.exists() and "#done" in tsv.read_text(encoding="utf-8", errors="replace"):
            break
        if proc.poll() is not None:
            break
        time.sleep(2.0)
    if proc.poll() is None:
        proc.kill()
    lines = [l for l in tsv.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    print(f"mode={mode} 采样 {len(lines)} 帧")
    worst = 0
    for l in lines:
        parts = l.split("\t")
        f, bs, ts, m, np_, x314, cam, mk, raw = parts[:9]
        if bs == "none" or ts == "none":
            print(f"  f={f:>3} 球={bs} 人={ts} 人数={np_} 球贴图={raw} 标记={mk}  ← 解析不到")
            continue
        bxi, byi = (int(v) for v in bs.split(","))
        txi, tyi = (int(v) for v in ts.split(","))
        d = max(abs(bxi - txi), abs(byi - tyi))
        worst = max(worst, d)
        print(f"  f={f:>3} 球=({bxi:>3},{byi:>3}) 最近人=({txi:>3},{tyi:>3}) 间距={d:>3}px "
              f"$314={x314} 镜头={cam} 标记={mk} 球贴图={raw}")
    print(f"最大间距 = {worst}px（{mode}）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
