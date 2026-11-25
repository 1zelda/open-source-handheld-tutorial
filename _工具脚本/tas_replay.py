# -*- coding: utf-8 -*-
"""TAS 输入录像回放 → 视频（已验证管线，见 04-游戏资源库/TAS输入录像库/验证/replay_verification.json）。

用法:
  python tas_replay.py --movie <.bk2/.fm2/...> --rom <rom> --core NesHawk \
      --bizhawk <BizHawk目录> --frames 180 --out <输出.mp4> [--fps 60]

要点（都是踩过的坑）:
  * BizHawk 版本必须与录像 Header 的 emuVersion 一致（2.8 录像用 2.8）。
  * 2.8 CLI 用 --flag=value 等号语法；2.10+ 才支持空格分隔。
  * 核心必须与录像 Header 的 Core 一致，用 config.ini PreferredCores 强制。
  * 发行版无内置 AVI writer，故用 Lua 逐帧截图 + 外部 ffmpeg 编码。
  * 路径一律转成纯 ASCII 临时目录，避免中文转码损坏。
  * 已知缺口：逐帧截图没有声音；音频采集是 M5 的独立准入项。
  * 2026-11-07：最后一帧截图后不再 frameadvance（那一下会把 movie 推到末尾，
    BizHawk 弹 "end of the movie ... missing a cycle count" 模态框堵死 Lua，
    client.exit() 永远到不了，白等 27 分钟超时）。每帧写 heartbeat.txt，
    外层看门狗发现停滞会先自动点框、再树杀；cap.txt 空文件不再算「无 desync」。
  * 2026-11-24：启动前 assert_rom_matches_movie 逐字节核对 ROM md5（整文件与
    去 iNES 头两种口径都认）；换镜像回放跑出来的不是原 TAS，直接拦死。

run_replay / encode_video 是可复用函数，供 taspipe.backends 薄封装；
main() 保持原 CLI 行为作为回归基线。
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from taspipe import watchdog

LUA_TMPL = """
local dir = "{dir}/frames/"
local f = io.open("{dir}/cap.txt", "w")
local hb = io.open("{dir}/heartbeat.txt", "w")
local N = {n}
local status = "complete"
local captured = 0
for i = 0, N - 1 do
	client.screenshot(dir .. string.format("f%04d.png", i))
	captured = i + 1
	local mode = tostring(movie.mode())
	hb:seek("set", 0)
	hb:write(string.format("%08d %-10s\\n", captured, mode))
	hb:flush()
	if i == N - 1 then
		break
	end
	advance_frame()
	if movie.mode() ~= "PLAY" and movie.mode() ~= "RECORD" then
		f:write("desync at " .. i .. " mode=" .. tostring(movie.mode()) .. "\\n")
		status = "desync"
		break
	end
end
f:write(string.format("status=%s n=%d mode=%s\\n", status, captured, tostring(movie.mode())))
f:flush()
f:close()
hb:close()
client.exit()
"""

# 状态会话模板（T3 前置件，2026-11-10）：持久 EmuHawk + 文件指令通道。
# 与 LUA_TMPL 不同：不退出，逐帧轮询 cmd.txt（"id op args..." 单行），响应写
# resp.txt（"id ok|err data"）。id 单调递增，Lua 拒绝 id<=last_id 防重复执行。
# 用 __DIR__/__SPEED__ 占位符而非 str.format：Lua 表字面量 {} 会与 format 冲突。
# 关键原子性：load/run/macro/attempt 可带截图路径，截图在指令末帧同帧执行，
# Python 往返延迟不会混进帧号（否则「同状态+同输入=同画面」会被空闲漂移污染）。
STATE_LUA_TMPL = """
local dir = "__DIR__"
local cmd_path = dir .. "/cmd.txt"
local resp_path = dir .. "/resp.txt"
local hb = io.open(dir .. "/heartbeat.txt", "w")
local logf = io.open(dir .. "/session.log", "w")
local last_id = 0
local pending = nil
local flushing = nil
local dumping = nil
local bus_probe = nil

client.speedmode(__SPEED__)
client.pause()

local function log(s)
	logf:write(s .. "\\n")
	logf:flush()
end

local function advance_frame()
	client.unpause()
	emu.frameadvance()
	client.pause()
end

local function split_keep(s, sep)
	local t, init = {}, 1
	while true do
		local a, b = string.find(s, sep, init, true)
		if not a then t[#t + 1] = string.sub(s, init); break end
		t[#t + 1] = string.sub(s, init, a - 1)
		init = b + 1
	end
	return t
end

local valid_buttons = {__BUTTONS__}

local use_joypad_port = false
for name in pairs(joypad.get() or {}) do
	if string.find(name, "^P%d+ ") then
		use_joypad_port = true
		break
	end
end

local function set_controls(inputs)
	if use_joypad_port then
		joypad.set(inputs, __PORT__)
	else
		joypad.set(inputs)
	end
end

local function get_controls()
	if use_joypad_port then return joypad.get(__PORT__) end
	return joypad.get()
end

local function apply_frame_controls()
	if pending then
		if pending.idx <= #pending.inputs then
			set_controls(pending.inputs[pending.idx])
		else
			set_controls({})
		end
	elseif dumping then
		if dumping.idx <= #dumping.inputs then
			set_controls(dumping.inputs[dumping.idx])
		else
			set_controls({})
		end
	elseif movie.mode() == "INACTIVE" then
		set_controls({})
	end
end

local function buttons(tok)
	local b = {}
	if tok == "" then return b end
	for _, name in ipairs(split_keep(tok, "+")) do
		if valid_buttons[name] == nil then error("unknown button: " .. name) end
		b[name] = true
	end
	return b
end

local function respond(id, status, data)
	local f = io.open(resp_path, "w")
	if not f then log("RESP_OPEN_ERR " .. resp_path) return end
	f:write(string.format("%d %s %s\\n", id, status, data or ""))
	f:flush()
	f:close()
	local chk = io.open(resp_path, "r")
	if chk then chk:close() end
	log(string.format("resp %d %s %s visible=%s", id, status, data or "", tostring(chk ~= nil)))
end

local function need_inactive(op)
	if movie.mode() == "PLAY" or movie.mode() == "RECORD" then
		error(op .. " 需先 stop_movie（电影回放中接管手柄会 desync）")
	end
end

-- 指令行按空格切参，域名里的空格在 Python 侧编码成 %20，这里还原后交给 BizHawk。
local function decode_domain(domain)
	if not domain then return nil end
	return (domain:gsub("%%20", " "))
end

local function read8(addr, domain)
	if domain then return memory.read_u8(addr, decode_domain(domain)) end
	return memory.read_u8(addr)
end

local function write8(addr, value, domain)
	if domain then memory.write_u8(addr, value, decode_domain(domain)) else memory.write_u8(addr, value) end
end

local function apply_patches(patches)
	if patches then
		for _, patch in ipairs(patches) do
			write8(patch.addr, patch.value, patch.domain)
		end
	end
end

-- PNG 完整性：以 IEND 块结尾才算落盘完成。无 yield，可在任何地方调。
local function png_complete(path)
	local f = io.open(path, "rb")
	if not f then return false end
	local size = f:seek("end")
	f:seek("set", math.max(0, size - 12))
	local tail = f:read(12) or ""
	f:close()
	return size > 0 and string.find(tail, "IEND", 1, true) ~= nil
end

-- client.screenshot 只是「排队」，真正落盘在下一次 frameadvance 之后。
-- 若截完就 respond，Python 立刻拷文件会拿到上一张旧图/半截图（11-10 实测：
-- macro_effective 因此假阳性）。故截图后进入 flushing 态：主循环每轮推一帧
-- （触发落盘）并查 IEND，完整了才 respond。emu.frameadvance 会 yield Lua 协程，
-- 绝不能放进 pcall（Lua 5.1 禁止跨 C-call 边界 yield），所以 flushing 的推进
-- 放在主循环本体里。多推的帧在截图之后、中立输入，不影响所截画面。
local function queue_shot(id, path)
	local oks, errs = pcall(client.screenshot, path)
	if not oks then log("SHOT_ERR " .. tostring(errs)) end
	flushing = { id = id, path = path, tries = 0 }
end

-- 默认域 0..len-1 原始字节落盘；ramdump 指令与 pending 收尾共用这一份实现。
local function dump_ram(path, len, domain, start)
	start = start or 0
	local f = io.open(path, "wb")
	if not f then error("ramdump 无法写: " .. path) end
	local chunk = {}
	for a = start, start + len - 1 do
		chunk[#chunk + 1] = string.char(read8(a, domain) or 0)
		if #chunk >= 256 then f:write(table.concat(chunk)); chunk = {} end
	end
	if #chunk > 0 then f:write(table.concat(chunk)) end
	f:close()
end

local function state_fingerprint()
	local parts = {tostring(emu.framecount())}
	for _, name in ipairs(memory.getmemorydomainlist()) do
		local size = memory.getmemorydomainsize(name)
		if name ~= "ROM" and name ~= "BIOS" and name ~= "System Bus"
			and name ~= "CPU registers" and size <= 1048576 then
			parts[#parts + 1] = name .. ":" .. tostring(size) .. ":"
				.. tostring(memory.hash_region(0, size, name))
		end
	end
	return table.concat(parts, "|")
end

local function instant(id, op, p)
	if op == "ping" then
		return "ok", emu.framecount() .. " " .. tostring(movie.mode())
	elseif op == "domains" then
		local names = memory.getmemorydomainlist()
		local current_name = memory.getcurrentmemorydomain()
		local rows, listed = {}, {}
		for _, name in ipairs(names) do
			listed[name] = true
			local ok, size = pcall(function() return memory.getmemorydomainsize(name) end)
			rows[#rows + 1] = name .. ":" .. tostring(ok and size or -1) .. (name == current_name and "*" or "")
		end
		-- Snes9x Waterbox 的 Save RAM 可直读，却不在 Lua 域列表里。
		if emu.getsystemid() == "SNES" and not listed["Save RAM"] then
			local ok, size = pcall(function() return memory.getmemorydomainsize("Save RAM") end)
			if ok and size and size > 0 then
				rows[#rows + 1] = "Save RAM:" .. tostring(size)
			end
		end
		return "ok", table.concat(rows, "|")
	elseif op == "businfo" then
		return "ok", emu.getsystemid() .. "~" .. client.getversion() .. "~"
			.. table.concat(event.availableScopes(), "|")
	elseif op == "gameinfo" then
		return "ok", gameinfo.getromname()
	elseif op == "profile" then
		need_inactive(op)
		savestate.load(p[3])
		local before = state_fingerprint()
		savestate.save(p[4])
		savestate.load(p[4])
		local after = state_fingerprint()
		return "ok", before .. "~" .. after
	elseif op == "save" then
		savestate.save(p[3])
		return "ok", tostring(emu.framecount())
	elseif op == "load" then
		need_inactive(op)
		savestate.load(p[3])
		if p[4] then client.screenshot(p[4]) end
		return "ok", tostring(emu.framecount()), p[4]
	elseif op == "read" then
		return "ok", tostring(read8(tonumber(p[3]), p[4]))
	elseif op == "write" then
		write8(tonumber(p[3]), tonumber(p[4]), p[5])
		return "ok", ""
	elseif op == "seed_ram" then
		need_inactive(op)
		local f = io.open(p[3], "rb")
		if not f then error("seed_ram 无法读: " .. p[3]) end
		local blob = f:read("*a") or ""
		f:close()
		local domain = decode_domain(p[4])
		local size = domain and memory.getmemorydomainsize(domain) or nil
		if not size or #blob < 1 or #blob > size then
			error("seed_ram 内存域或长度非法: " .. tostring(domain) .. " bytes=" .. #blob .. " size=" .. tostring(size))
		end
		client.reboot_core()
		local start = tonumber(p[6]) or 0
		for i = 1, #blob do write8(start + i - 1, string.byte(blob, i), domain) end
		for i = 1, #blob do
			if read8(start + i - 1, domain) ~= string.byte(blob, i) then
				error("seed_ram 回读不符: " .. tostring(domain) .. " offset=" .. (start + i - 1))
			end
		end
		savestate.save(p[5])
		return "ok", emu.framecount() .. " " .. #blob
	elseif op == "ramtest" then
		local a = tonumber(p[3])
		local o = read8(a, p[4])
		write8(a, (o + 1) % 256, p[4])
		local v = read8(a, p[4])
		write8(a, o, p[4])
		return "ok", o .. " " .. v
	elseif op == "shot" then
		client.screenshot(p[3])
		return "ok", "", p[3]
	elseif op == "stop_movie" then
		movie.stop()
		return "ok", tostring(movie.mode())
	end
	error("unknown op: " .. tostring(op))
end

-- run/macro/attempt 统一成 pending：{inputs, idx, extra, shot}。
-- 每帧：宏段按表 joypad.set，空档段 joypad.set({})；run 在电影 PLAY 中不碰手柄。
-- ram 与 save/shot 排在同一帧上：命令之间空闲循环每轮都在推帧，
-- 分开的 ramdump 读到的是不定帧，只有挂在 pending 收尾才是帧对齐的取样。
local function pending_result(frame, probe, domain, bus_probe)
	local data = tostring(frame)
	if probe then data = data .. "~" .. tostring(read8(probe, domain)) end
	if bus_probe then
		data = data .. "~" .. tostring(bus_probe.read_value() or "none")
			.. "~" .. tostring(bus_probe.read_count())
			.. "~" .. tostring(bus_probe.write_value() or "none")
			.. "~" .. tostring(bus_probe.write_count())
	end
	return data
end

local function start_bus_probe(addr, scope)
	if not event.can_use_callback_params() then
		error("当前核心/版本不向总线回调传参，不能采样输入寄存器")
	end
	local function capture(val, state)
		state.count = state.count + 1
		if state.first == nil then
			state.first = val
		elseif val ~= state.first then
			state.changed = true
		end
		state.values[val] = true
	end
	local read_state = {count = 0, values = {}}
	local write_state = {count = 0, values = {}}
	local function capture_read(at, val)
		capture(val, read_state)
	end
	local function capture_write(at, val)
		capture(val, write_state)
	end
	local function summary(state)
		if next(state.values) == nil then return nil end
		if state.changed then return "mixed" end
		return state.first
	end
	local read_id = event.on_bus_read(capture_read, addr, "statejump keyinput read", scope)
	local write_id = event.on_bus_write(capture_write, addr, "statejump keyinput write", scope)
	return {
		addr = addr,
		scope = scope,
		read_value = function() return summary(read_state) end,
		write_value = function() return summary(write_state) end,
		read_count = function() return read_state.count end,
		write_count = function() return write_state.count end,
		close = function()
			event.unregisterbyid(read_id)
			event.unregisterbyid(write_id)
		end
	}
end

local function close_bus_probe()
	local active = bus_probe
	bus_probe = nil
	if type(active) ~= "table" then return end
	log("bus probe " .. tostring(active.addr) .. " scope=" .. tostring(active.scope)
		.. " reads=" .. tostring(active.read_count()) .. " read="
		.. tostring(active.read_value()) .. " writes=" .. tostring(active.write_count())
		.. " write=" .. tostring(active.write_value()))
	active.close()
end

local function start_pending(id, inputs, extra, shot, save, ram, probe, domain, bus_probe,
	                        ram_start, ram_length)
	if #inputs + extra == 0 then
		if save then savestate.save(save) end
		if ram then dump_ram(ram, ram_length or 2048, domain, ram_start or 0) end
		local data = pending_result(emu.framecount(), probe, domain, bus_probe)
		if bus_probe then close_bus_probe() end
		if shot then
			queue_shot(id, shot)
		else
			respond(id, "ok", data)
		end
		return nil
	end
	return { id = id, inputs = inputs, idx = 1, extra = extra, shot = shot,
	         save = save, ram = ram, probe = probe, domain = domain, bus_probe = bus_probe,
	         ram_start = ram_start, ram_length = ram_length }
end

local function poll()
	local f = io.open(cmd_path, "r")
	if not f then return end
	local line = f:read("*a")
	f:close()
	os.remove(cmd_path)
	if line then line = string.gsub(line, "[\\r\\n]+$", "") end
	if not line or line == "" then return end
	local p = split_keep(line, " ")
	local id = tonumber(p[1])
	if not id or id <= last_id then return end
	last_id = id
	log("cmd " .. id .. " op " .. tostring(p[2]) .. " len " .. #line)
	local op = p[2]
	if op == "quit" then
		respond(id, "ok", "")
		hb:flush()
		hb:close()
		logf:close()
		client.exit()
		return
	end
	local okc, a, b, c = pcall(function()
		if op == "run" then
			local n = tonumber(p[3])
			if not n or n < 1 then error("run 需正整数帧数") end
			pending = start_pending(id, {}, n, p[4])
			return nil
		elseif op == "macro" then
			need_inactive(op)
			local inputs = {}
			for i, tok in ipairs(split_keep(p[3], ",")) do inputs[i] = buttons(tok) end
			if #inputs == 0 then error("macro 至少一帧") end
			pending = start_pending(id, inputs, 0, p[4])
			return nil
		elseif op == "attempt" then
			need_inactive(op)
			savestate.load(p[3])
			local inputs = {}
			if p[4] ~= "-" then
				for i, tok in ipairs(split_keep(p[4], ",")) do inputs[i] = buttons(tok) end
			end
			local extra = tonumber(p[5]) or 0
			if extra < 0 then error("attempt extra 不能为负") end
			local probe_domain = p[10] and p[10] ~= "-" and decode_domain(p[10]) or nil
			local bus_scope = p[12] and p[12] ~= "-" and decode_domain(p[12]) or nil
			local ram_start = tonumber(p[13])
			local ram_length = tonumber(p[14])
			if ram_length and (ram_length < 1 or ram_length > 65536) then
				error("attempt ram_length 须为 1..65536")
			end
			if ram_start and ram_start < 0 then error("attempt ram_start 不能为负") end
			if p[15] and p[15] ~= "-" then
				for _, tok in ipairs(split_keep(p[15], ";")) do
					local a, v, domain = tok:match("^(%d+):(%d+)@(.+)$")
					if not a then a, v = tok:match("^(%d+):(%d+)$") end
					if not a then error("attempt patch 格式非法: " .. tok) end
					a, v = tonumber(a), tonumber(v)
					if a < 0 or v < 0 or v > 255 then error("attempt patch 地址/值非法: " .. tok) end
					write8(a, v, domain)
				end
			end
			__BUSPROBE_START__
			pending = start_pending(id, inputs, extra,
			                        p[6] ~= "-" and p[6] or nil,
			                        p[7] ~= "-" and p[7] or nil,
			                        p[8] ~= "-" and p[8] or nil,
			                        p[9] and p[9] ~= "-" and tonumber(p[9]) or nil,
			                        probe_domain, bus_probe, ram_start, ram_length)
			return nil
		elseif op == "ramdump" then
			local len = tonumber(p[4]) or 2048
			local start = tonumber(p[5]) or 0
			local domain = p[6] and decode_domain(p[6]) or nil
			if len < 1 or start < 0 then error("ramdump 长度/起点非法") end
			dump_ram(p[3], len, domain, start)
			return "ok", tostring(len)
		elseif op == "dump" then
			need_inactive(op)
			local fdir = p[3]
			local inputs = {}
			if p[4] ~= "-" then
				for i, tok in ipairs(split_keep(p[4], ",")) do inputs[i] = buttons(tok) end
			end
			local extra = tonumber(p[5]) or 0
			if extra < 0 then error("dump extra 不能为负") end
			local total = #inputs + extra
			if total < 1 then error("dump 至少一帧") end
			if p[6] and p[6] ~= "-" then savestate.load(p[6]) end
			local patch_mode = p[8] or "one_shot"
			if patch_mode ~= "one_shot" and patch_mode ~= "per_frame" then
				error("dump patch mode 非法: " .. patch_mode)
			end
			local dump_patches = {}
			if p[7] and p[7] ~= "-" then
				for _, tok in ipairs(split_keep(p[7], ";")) do
					local a, v, domain = tok:match("^(%d+):(%d+)@(.+)$")
					if not a then a, v = tok:match("^(%d+):(%d+)$") end
					if not a then error("dump patch 格式非法: " .. tok) end
					local patch = { addr = tonumber(a), value = tonumber(v), domain = domain }
					write8(patch.addr, patch.value, patch.domain)
					if patch_mode == "per_frame" then
						dump_patches[#dump_patches + 1] = patch
					end
				end
			end
			dumping = { id = id, dir = fdir, inputs = inputs, total = total, idx = 1,
			            patches = dump_patches }
			return nil
		end
		return instant(id, op, p)
	end)
	if not okc then
		close_bus_probe()
		pending = nil
		dumping = nil
		respond(id, "err", tostring(a))
	elseif a then
		if c then
			flushing = { id = id, path = c, tries = 0 }
		else
			respond(id, a, b)
		end
	end
end

event.onframestart(apply_frame_controls, "statejump frame controls")
log("session start")
while true do
	local okh, errh = pcall(function()
		hb:seek("set", 0)
		hb:write(string.format("%08d %-10s\\n", emu.framecount(), tostring(movie.mode())))
		hb:flush()
	end)
	if not okh then log("HB_ERR " .. tostring(errh)) end
	if not pending and not flushing and not dumping then
		local okp, errp = xpcall(poll, function(e)
			return tostring(e) .. " || " .. debug.traceback("", 2)
		end)
		if not okp then log("POLL_ERR " .. tostring(errp)) end
	end
	if pending then
		advance_frame()
		pending.idx = pending.idx + 1
		if pending.idx > #pending.inputs + pending.extra then
			local data = pending_result(emu.framecount(), pending.probe, pending.domain,
			                            pending.bus_probe)
			if pending.bus_probe then close_bus_probe() end
			if pending.probe then
				local pressed = {}
				for name, value in pairs(get_controls() or {}) do
					pressed[#pressed + 1] = name .. "=" .. tostring(value)
				end
				table.sort(pressed)
				log("probe controls " .. table.concat(pressed, ","))
			end
			if movie.mode() == "INACTIVE" then set_controls({}) end
			if pending.save then savestate.save(pending.save) end
			if pending.ram then
				dump_ram(pending.ram, pending.ram_length or 2048, pending.domain,
				         pending.ram_start or 0)
			end
			if pending.shot then
				queue_shot(pending.id, pending.shot)
			else
				respond(pending.id, "ok", data)
			end
			pending = nil
		end
	elseif dumping then
		advance_frame()
		apply_patches(dumping.patches)
		local oks, errs = pcall(client.screenshot, dumping.dir .. string.format("/f%04d.png", dumping.idx - 1))
		if not oks then log("SHOT_ERR " .. tostring(errs)) end
		dumping.idx = dumping.idx + 1
		if dumping.idx > dumping.total then
			if movie.mode() == "INACTIVE" then set_controls({}) end
			local lastpath = dumping.dir .. string.format("/f%04d.png", dumping.total - 1)
			flushing = { id = dumping.id, path = lastpath, tries = 0,
			             data = tostring(dumping.total), patches = dumping.patches }
			dumping = nil
		end
	elseif flushing then
		advance_frame()
		apply_patches(flushing.patches)
		flushing.tries = flushing.tries + 1
		if png_complete(flushing.path) then
			respond(flushing.id, "ok", flushing.data or tostring(emu.framecount()))
			flushing = nil
		elseif flushing.tries >= 12 then
			respond(flushing.id, "err", "screenshot not flushed: " .. flushing.path)
			flushing = nil
		end
	else
		advance_frame()
	end
end
"""


def parse_report(report):
    """cap.txt -> (status, desync)。三态，证据不足返回 None，绝不默认「没失败=通过」。

    11-07 那次 run.json 把 0 字节 cap.txt 判成了 replay_no_desync=pass，
    实际是 TIMEOUT 1635s 被杀；空文件不能当证据。
    """
    if not report or report.strip() in ("", "(no cap.txt)"):
        return None, None
    m = re.search(r"status=(\w+)", report)
    status = m.group(1) if m else None
    if "desync at" in report or status == "desync":
        return status or "desync", True
    if status == "complete":
        return status, False
    if "TIMEOUT" in report or "WATCHDOG" in report:
        return "timeout", None
    return status, None


def force_core(bizhawk, system, core):
    """读改写 config.ini（JSON），强制 PreferredCores[system]=core。

    BizHawk 2.9+ 启动校验 config 版本：极简 config 缺 LastWrittenFrom 标记就弹
    "Mismatched version in config file" 模态框堵死 Lua（2.8 不校验，故旧管线只
    在 ≤2.8 能跑）。按目录名 BizHawk-<ver> 补写版本标记，让该框根本不出现。
    """
    cfg = os.path.join(bizhawk, "config.ini")
    conf = {}
    if os.path.isfile(cfg):
        with open(cfg, encoding="utf-8-sig") as f:
            conf = json.load(f)
    conf.setdefault("PreferredCores", {})[system] = core
    conf["DontTryOtherCores"] = True
    conf["FirstBoot"] = False
    m = re.fullmatch(r"BizHawk-(.+)", os.path.basename(os.path.normpath(bizhawk)))
    if m:
        ver = m.group(1)
        conf["LastWrittenFrom"] = ver
        conf["LastWrittenFromDetailed"] = "Version " + ver
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump(conf, f)


def materialize_movie(src, dst):
    """把 movie 落到 dst。TASVideos 下载常是「外壳 zip 里套一个真 .bk2」，
    文件名却仍叫 *.bk2；BizHawk 只认顶层带 Header.txt 的真 .bk2，喂外壳会抛
    "Essential zip section not found: Header" 并在启动时弹 Exception 模态框堵死 Lua。
    故：顶层无 Header.txt 但内含 .bk2 时解出内部那个；否则原样拷贝。
    返回 True 表示做了解包（供证据/日志）。"""
    try:
        with zipfile.ZipFile(src) as z:
            names = z.namelist()
            if "Header.txt" not in names:
                inner = [n for n in names if n.lower().endswith(".bk2")]
                if inner:
                    data = z.read(inner[0])
                    with open(dst, "wb") as fh:
                        fh.write(data)
                    return True
    except zipfile.BadZipFile:
        pass
    shutil.copyfile(src, dst)
    return False


def materialize_rom(src, dst):
    """把 ROM 普通文件或 zip!条目落到回放工作目录，不改写原包。"""
    from taspipe.schema import split_rom_spec
    archive, entry = split_rom_spec(src)
    if entry is None:
        shutil.copyfile(archive, dst)
        return False
    with zipfile.ZipFile(archive) as z, z.open(entry) as fh, open(dst, "wb") as out:
        shutil.copyfileobj(fh, out)
    return True


def expected_rom_md5(movie_path):
    """录像件声明的期望 ROM md5（BizHawk/FCEUX 口径 = iNES 去 16 字节头后的 md5）。

    真 .bk2 从 zip 内 Header.txt 的 MD5 行取；.fcm/.fmv/.fm2 走 taspipe.fceux
    的解析（romChecksum=GameInfo->MD5，同去头口径）。读不到返回空串（不设闸）。
    """
    try:
        with zipfile.ZipFile(movie_path) as z:
            if "Header.txt" in z.namelist():
                for line in z.read("Header.txt").decode("utf-8-sig", "replace").splitlines():
                    if line.strip().lower().startswith("md5"):
                        return line.split(" ", 1)[1].strip().upper()
                return ""
    except (OSError, zipfile.BadZipFile):
        pass
    try:
        from taspipe.fceux import parse_movie
        m = parse_movie(movie_path)
        return (getattr(m, "md5", "") or "").upper()
    except Exception:
        return ""


def rom_md5_candidates(rom_path):
    """实 ROM 的 md5 两种口径：整文件 / 去 iNES 头。"""
    with open(rom_path, "rb") as fh:
        data = fh.read()
    cands = {hashlib.md5(data).hexdigest().upper()}
    if data[:4] == b"NES\x1a" and len(data) > 16:
        cands.add(hashlib.md5(data[16:]).hexdigest().upper())
    return cands


def assert_rom_matches_movie(movie_path, rom_path):
    """启动前闸门：换镜像回放 = TAS 输入对不上内存布局, 跑出来的不是原 TAS。

    11-24 实锤：515M 用 mega_man_usa.nes(md5 不符) 回放, 16 分钟困一关/零换
    武器/零击杀, 画面看着像正常游玩, 实际整段脱轨; 换 megaman1_ntsc_hd.nes
    (去头 md5 逐字节吻合) 才是原片。md5 读不到时放行（不拦未知格式）。
    """
    exp = expected_rom_md5(movie_path)
    if not exp:
        return None
    actual = rom_md5_candidates(rom_path)
    if exp not in actual:
        raise RuntimeError(
            "ROM 与录像不匹配: 录像期望 md5=%s, 实件 md5=%s (%s)。换镜像回放跑"
            "出来的不是原 TAS, 禁止用作素材/证据。" % (
                exp, ", ".join(sorted(actual)), os.path.basename(rom_path)))
    return exp


def run_replay(movie, rom, core, system, bizhawk, frames, work=None, realtime=False,
               timeout=None, stall_timeout=30.0, dismiss_grace=8.0,
               auto_dismiss=True):
    """回放 frames 帧并逐帧截图。返回结构化结果（不编码）。

    返回 dict 增加 termination / status / watchdog；desync 变成三态
    (True=确认 desync / False=确认无 desync / None=证据不足)。
    realtime=True 强制 client.speedmode(100) 实时运行，供 loopback 音频对齐。
    timeout 仍是按帧数放宽的总兜底 max(600, frames/30 + 120)，但看门狗会在
    心跳停滞 30s 时先点框、再树杀，不会再空等到 27 分钟。
    无论哪种终止，已采到的帧都原样返回，由调用方接着编码（「继续下一步」）。
    """
    work = work or tempfile.mkdtemp(prefix="tas_replay_")
    # cap.lua 里的 io.open 在含非 ASCII 字符的目录下直接返回 nil（11-23 连踩两次：
    # 表现是 LuaScriptException "index a nil value (local 'hb')" + 只出 1 帧，
    # 外层看着像模拟器死了）。拦在启动前，别让人拿 1 帧的产物去判仿真。
    if not work.isascii():
        raise ValueError(
            "work 目录必须全 ASCII，当前含非 ASCII 字符: %r —— 否则 cap.lua 的 "
            "io.open 返回 nil，整跑只出 1 帧。默认 tempfile.mkdtemp() 就是 ASCII。" % work)
    os.makedirs(os.path.join(work, "frames"), exist_ok=True)
    m = os.path.join(work, "movie" + os.path.splitext(movie)[1])
    r = os.path.join(work, "rom" + os.path.splitext(rom)[1])
    unwrapped = materialize_movie(movie, m)
    rom_materialized = materialize_rom(rom, r)
    verified_md5 = assert_rom_matches_movie(m, r)
    force_core(bizhawk, system, core)
    lua = os.path.join(work, "cap.lua")
    body = LUA_TMPL.format(dir=work.replace("\\", "/"), n=frames)
    if realtime:
        body = "client.speedmode(100)\n" + body
    with open(lua, "w", encoding="utf-8") as f:
        f.write(body)
    exe = os.path.join(bizhawk, "EmuHawk.exe")
    cmd = [exe, "--chromeless", f"--movie={m}", f"--lua={lua}", r]
    to = timeout if timeout is not None else max(600, int(frames / 30) + 120)
    # BizHawk 每帧往 stdout 打 "xxx.png saved."，用管道又没人读会写满并反过来
    # 把模拟器堵死（另一种「卡住」），所以当初直接 DEVNULL。落盘到文件句柄同样
    # 不堵（文件不是管道），却保住了只走 Console 的固件/降级证据 —— 11-23 从
    # dll 字面量核实 Couldn't find firmware … 这条不保证弹框，只盯框就会把
    # 「压根没弹框」当成「没降级」。
    emulog = os.path.join(work, "emulator.log")
    with open(emulog, "wb") as log_fh:
        proc = subprocess.Popen(cmd, cwd=bizhawk, stdout=log_fh,
                                stderr=subprocess.STDOUT)
        wd = watchdog.watch_process(proc, work, hard_timeout=to,
                                    stall_timeout=stall_timeout,
                                    dismiss_grace=dismiss_grace,
                                    auto_dismiss=auto_dismiss)
    wd["console_texts"] = watchdog.firmware_console_lines(emulog)
    cap = os.path.join(work, "cap.txt")
    if os.path.isfile(cap):
        with open(cap, encoding="utf-8", errors="replace") as fh:
            report = fh.read()
    else:
        report = "(no cap.txt)"
    if wd["termination"] in ("timeout", "stalled_killed"):
        report = (report + f"\nWATCHDOG {wd['termination']} after {wd['elapsed']}s "
                  f"(target {frames} frames, last heartbeat {wd['last_frame']})").strip()
    frames_dir = os.path.join(work, "frames")
    n = len([x for x in os.listdir(frames_dir) if x.endswith(".png")])
    status, desync = parse_report(report)
    termination = wd["termination"]
    if status in ("complete", "desync"):
        termination = "complete" if status == "complete" else "desync"
    elif termination == "exited":
        termination = "movie_end" if n >= frames else "incomplete"
    return {"work": work, "frames_dir": frames_dir, "n_frames": n,
            "desync": desync, "status": status, "report": report.strip(),
            "cmd": cmd, "timeout": wd["termination"] == "timeout",
            "termination": termination, "watchdog": wd,
            "movie_unwrapped": unwrapped, "rom_materialized": rom_materialized,
            "rom_md5": verified_md5}


def encode_video(frames_dir, fps, out, ffmpeg="ffmpeg"):
    """frames/f%04d.png -> mp4（libx264/yuv420p/crf18）。仅图像，无音频。"""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    enc = [ffmpeg, "-y", "-framerate", str(fps), "-i",
           os.path.join(frames_dir, "f%04d.png"), "-c:v", "libx264",
           "-pix_fmt", "yuv420p", "-crf", "18", out]
    subprocess.run(enc, check=True, capture_output=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--movie", required=True)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--core", default="NesHawk")
    ap.add_argument("--system", default="NES")
    ap.add_argument("--bizhawk", required=True, help="BizHawk 解压目录(含 EmuHawk.exe)")
    ap.add_argument("--frames", type=int, default=180)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    args = ap.parse_args()

    res = run_replay(args.movie, args.rom, args.core, args.system,
                     args.bizhawk, args.frames)
    print("run:", " ".join(res["cmd"]), flush=True)
    print("replay:", res["report"])
    print(f"termination={res['termination']} watchdog={res['watchdog']}")
    if res["desync"] is True:
        print("!! desync，检查 ROM hash / 模拟器版本 / 核心", file=sys.stderr)
        sys.exit(2)
    if res["n_frames"] == 0:
        print("!! 没有截到帧", file=sys.stderr)
        sys.exit(2)
    # 卡死/超时也用已采到的帧继续出片，终止原因留在 report 里给上层判证据等级。
    if res["desync"] is None or res["termination"] in ("stalled_killed", "timeout"):
        print(f"! 非干净退出（{res['termination']}），仍用已采的 "
              f"{res['n_frames']} 帧继续编码；证据不足，别当验收通过",
              file=sys.stderr)
    encode_video(res["frames_dir"], args.fps, args.out, args.ffmpeg)
    print(f"OK: {res['n_frames']} frames -> {args.out}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()