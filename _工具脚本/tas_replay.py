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

run_replay / encode_video 是可复用函数，供 taspipe.backends 薄封装；
main() 保持原 CLI 行为作为回归基线。
"""
import argparse
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
	emu.frameadvance()
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

client.speedmode(__SPEED__)

local function log(s)
	logf:write(s .. "\\n")
	logf:flush()
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

local valid_buttons = joypad.get(1)

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

local function read8(addr, domain)
	if domain then return memory.read_u8(addr, domain) end
	return memory.read_u8(addr)
end

local function write8(addr, value, domain)
	if domain then memory.write_u8(addr, value, domain) else memory.write_u8(addr, value) end
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
	client.screenshot(path)
	flushing = { id = id, path = path, tries = 0 }
end

local function instant(id, op, p)
	if op == "ping" then
		return "ok", emu.framecount() .. " " .. tostring(movie.mode())
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
	elseif op == "ramtest" then
		local a = tonumber(p[3])
		local o = read8(a)
		write8(a, (o + 1) % 256)
		local v = read8(a)
		write8(a, o)
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
local function start_pending(id, inputs, extra, shot)
	if #inputs + extra == 0 then
		if shot then
			queue_shot(id, shot)
		else
			respond(id, "ok", tostring(emu.framecount()))
		end
		return nil
	end
	return { id = id, inputs = inputs, idx = 1, extra = extra, shot = shot }
end

local function poll()
	local f = io.open(cmd_path, "r")
	if not f then return end
	local line = f:read("*l")
	f:close()
	os.remove(cmd_path)
	if line then line = string.gsub(line, "\\r$", "") end
	if not line or line == "" then return end
	local p = split_keep(line, " ")
	local id = tonumber(p[1])
	if not id or id <= last_id then return end
	last_id = id
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
			pending = start_pending(id, inputs, extra, p[6])
			return nil
		elseif op == "ramdump" then
			local path = p[3]
			local len = tonumber(p[4]) or 2048
			if len < 1 then error("ramdump 长度须为正") end
			local f = io.open(path, "wb")
			if not f then error("ramdump 无法写: " .. path) end
			local chunk = {}
			for a = 0, len - 1 do
				chunk[#chunk + 1] = string.char(read8(a) or 0)
				if #chunk >= 256 then f:write(table.concat(chunk)); chunk = {} end
			end
			if #chunk > 0 then f:write(table.concat(chunk)) end
			f:close()
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
			dumping = { id = id, dir = fdir, inputs = inputs, total = total, idx = 1 }
			return nil
		end
		return instant(id, op, p)
	end)
	if not okc then
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

log("session start")
while true do
	hb:seek("set", 0)
	hb:write(string.format("%08d %-10s\\n", emu.framecount(), tostring(movie.mode())))
	hb:flush()
	if not pending and not flushing and not dumping then poll() end
	if pending then
		if pending.idx <= #pending.inputs then
			joypad.set(pending.inputs[pending.idx], 1)
		elseif movie.mode() == "INACTIVE" then
			joypad.set({}, 1)
		end
		emu.frameadvance()
		pending.idx = pending.idx + 1
		if pending.idx > #pending.inputs + pending.extra then
			if movie.mode() == "INACTIVE" then joypad.set({}, 1) end
			if pending.shot then
				queue_shot(pending.id, pending.shot)
			else
				respond(pending.id, "ok", tostring(emu.framecount()))
			end
			pending = nil
		end
	elseif dumping then
		if dumping.idx <= #dumping.inputs then
			joypad.set(dumping.inputs[dumping.idx], 1)
		elseif movie.mode() == "INACTIVE" then
			joypad.set({}, 1)
		end
		emu.frameadvance()
		client.screenshot(dumping.dir .. string.format("/f%04d.png", dumping.idx - 1))
		dumping.idx = dumping.idx + 1
		if dumping.idx > dumping.total then
			if movie.mode() == "INACTIVE" then joypad.set({}, 1) end
			local lastpath = dumping.dir .. string.format("/f%04d.png", dumping.total - 1)
			flushing = { id = dumping.id, path = lastpath, tries = 0 }
			dumping = nil
		end
	elseif flushing then
		emu.frameadvance()
		flushing.tries = flushing.tries + 1
		if png_complete(flushing.path) then
			respond(flushing.id, "ok", tostring(emu.framecount()))
			flushing = nil
		elseif flushing.tries >= 12 then
			respond(flushing.id, "err", "screenshot not flushed: " .. flushing.path)
			flushing = nil
		end
	else
		emu.frameadvance()
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
    os.makedirs(os.path.join(work, "frames"), exist_ok=True)
    m = os.path.join(work, "movie" + os.path.splitext(movie)[1])
    r = os.path.join(work, "rom" + os.path.splitext(rom)[1])
    unwrapped = materialize_movie(movie, m)
    shutil.copyfile(rom, r)
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
    # DEVNULL 而不是 capture_output：BizHawk 每帧往 stdout 打 "xxx.png saved."，
    # 管道没人读会写满并反过来把模拟器堵死（另一种「卡住」）。
    proc = subprocess.Popen(cmd, cwd=bizhawk, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    wd = watchdog.watch_process(proc, work, hard_timeout=to,
                                stall_timeout=stall_timeout,
                                dismiss_grace=dismiss_grace,
                                auto_dismiss=auto_dismiss)
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
            "movie_unwrapped": unwrapped}


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