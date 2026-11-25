# -*- coding: utf-8 -*-
"""热血足球：真人实时操作捕获 → 帧级宏 + .bk2 → 确定性回放复现。

分工：真人负责把必杀打出来（机制他熟），本工具负责把真人操作变成可复算、可回放的输入资产。

通道说明（11-15 实测）：BizHawk 2.8 的 Lua 没有 movie.record，所以录制用
joypad.get(1) 逐帧读当前生效手柄（真人键盘经键位映射后就是它），停录时用本仓库
taspipe.fceux 的 bk2 写盘器生成录像，再交给 BizHawk 自己回放。

用法（在 F:\\taspipe_scratch 下）：
  py -3 -u soccer2_live_capture.py keys                # 查看/重刷键位（上下左右=W/S/A/D，A=J B=K Select=L Start=;）
  py -3 -u soccer2_live_capture.py start [--rom X]     # 开窗口并从开机第一帧开始记录
  py -3 -u soccer2_live_capture.py status              # 录制是否活着、到第几帧
  py -3 -u soccer2_live_capture.py stop                # 停录：落 inputs.tsv + live.bk2 + live_end.state
  py -3 -u soccer2_live_capture.py ingest              # 解析：宏/事件/按键统计
  py -3 -u soccer2_live_capture.py replay [--every N]  # 用 live.bk2 确定性回放，出抽样拼图
  py -3 -u soccer2_live_capture.py selftest            # 合成真实按键走完整链路并逐条断言
"""
import argparse
import ctypes
import ctypes.wintypes as WT
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

BH = Path(r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.8")
WORK = Path(r"F:\taspipe_scratch\soccer2_live")
CFG = BH / "config.ini"
DEFAULT_ROM = Path(r"F:\taspipe_scratch\soccer2_cn_base\rom.nes")
TOOLS = Path(r"F:\开源掌机教程\_工具脚本")
SELFTEST = WORK.parent / "soccer2_live_selftest"

# FC 只有 A/B 两键；Select 是换人（展示不同角色必杀的关键），Start 是暂停，
# 所以把 abcd 四个键位落成 J=射击口 A、K=射门 B、L=换人 Select、;=Start。
KEYMAP = {
    "P1 Up": "W", "P1 Down": "S", "P1 Left": "A", "P1 Right": "D",
    "P1 A": "J", "P1 B": "K", "P1 Select": "L", "P1 Start": "Semicolon",
}
SCANCODE = {"W": 0x11, "A": 0x1E, "S": 0x1F, "D": 0x20, "J": 0x24,
            "K": 0x25, "L": 0x26, "SEMI": 0x27}

LUA_TMPL = r'''
local dir = "__DIR__"
local cmd_path = dir .. "/cmd.txt"
client.speedmode(100)
local logf = io.open(dir .. "/capture.log", "w")
local inp = io.open(dir .. "/inputs.tsv", "w")
local function note(s) logf:write(s .. "\n"); logf:flush() end

local proto = {}
for k in pairs(joypad.get(1)) do proto[#proto + 1] = k end
table.sort(proto)
note("buttons=" .. table.concat(proto, ","))
note("start frame=" .. emu.framecount())

local last_beat, stopping, quitnext = 0, false, false
while not stopping do
	local j = joypad.get(1)
	local pressed = {}
	for _, n in ipairs(proto) do
		if j[n] then pressed[#pressed + 1] = n end
	end
	local f = emu.framecount()
	inp:write(string.format("%d\t%s\n", f, #pressed > 0 and table.concat(pressed, "+") or "-"))
	if f - last_beat >= 60 then
		inp:flush()
		last_beat = f
		note("beat frame=" .. f)
	end
	emu.frameadvance()
	local cf = io.open(cmd_path, "r")
	if cf then
		local line = cf:read("*l")
		cf:close()
		os.remove(cmd_path)
		if line then
			if string.find(line, "quit", 1, true) then stopping, quitnext = true, true
			elseif string.find(line, "stop", 1, true) then stopping = true end
		end
	end
end
inp:flush()
inp:close()
local oks, erre = pcall(function() savestate.save(dir .. "/live_end.state") end)
note("endstate ok=" .. tostring(oks) .. " err=" .. tostring(erre))
note("stopped frame=" .. emu.framecount())
logf:flush()
logf:close()
if quitnext then client.exit() end
'''


def _fceux():
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    from taspipe import fceux as F
    return F


def apply_keys(write=True):
    """把新键位并进 config.ini 的 NES 绑定（保留原方向键/X/Z），幂等。"""
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    nes = cfg["AllTrollers"]["NES Controller"]
    out = {}
    for act, newk in KEYMAP.items():
        parts = [x.strip() for x in str(nes.get(act, "")).split(",") if x.strip()]
        if newk not in parts:
            parts.append(newk)
        nes[act] = ", ".join(parts)
        out[act] = nes[act]
    cfg["DisplayInput"] = True
    cfg["PauseWhenMenuActivated"] = False
    if write:
        bak = BH / "config.ini.bak_before_live_keys"
        if not bak.exists():
            bak.write_text(CFG.read_text(encoding="utf-8"), encoding="utf-8")
        CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=True), encoding="utf-8")
    return out


def running_pid():
    p = WORK / "pid.txt"
    if not p.exists():
        return None
    try:
        pid = int(p.read_text().strip())
    except ValueError:
        return None
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                       capture_output=True, text=True, errors="replace")
    return pid if "EmuHawk" in (r.stdout or "") else None


def start(rom, force=False):
    WORK.mkdir(parents=True, exist_ok=True)
    prev = WORK / "inputs.tsv"
    if prev.exists():
        n = sum(1 for _ in prev.open(encoding="utf-8", errors="replace"))
        if n > 2 and not force:
            raise SystemExit(
                f"{prev} 已有 {n} 帧录制：开新录会清空它。"
                f"先 bk2/ingest 归档，或复制整个目录另存，再加 --force（11-15 曾把 451 秒真人录制覆盖掉）")
    apply_keys()
    pid = running_pid()
    if pid:
        raise SystemExit(f"已有一个 EmuHawk(pid={pid}) 在跑，先执行 stop")
    for stale in ("cmd.txt", "inputs.tsv", "capture.log", "live.bk2", "live_end.state"):
        f = WORK / stale
        if f.exists():
            f.unlink()
    rom = Path(rom)
    if not rom.is_file():
        raise SystemExit(f"ROM 不存在：{rom}")
    r = WORK / "rom.nes"
    r.write_bytes(rom.read_bytes())
    lua = WORK / "live.lua"
    lua.write_text(LUA_TMPL.replace("__DIR__", str(WORK).replace("\\", "/")),
                   encoding="utf-8", newline="\n")
    proc = subprocess.Popen([str(BH / "EmuHawk.exe"), f"--lua={lua}", str(r)],
                            cwd=str(BH), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (WORK / "pid.txt").write_text(str(proc.pid))
    (WORK / "source_rom.txt").write_text(str(rom.resolve()), encoding="utf-8")
    log = WORK / "capture.log"
    deadline = time.time() + 60
    while time.time() < deadline:
        if log.exists():
            txt = log.read_text(encoding="utf-8", errors="replace")
            if "stopped" in txt:
                raise SystemExit("Lua 提前退出：\n" + txt)
            if "start frame=" in txt:
                return proc
        time.sleep(0.3)
    tail = log.read_text(encoding="utf-8", errors="replace") if log.exists() else "(无 capture.log)"
    raise SystemExit(f"60s 内没开始记录\n{tail}")


def status():
    log = WORK / "capture.log"
    pid = running_pid()
    if not log.exists():
        print("没有 capture.log，先 start")
        return
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"EmuHawk: {('活着 pid=' + str(pid)) if pid else '已退出'}")
    for l in lines[-5:]:
        print("  " + l)
    inp = WORK / "inputs.tsv"
    if inp.exists():
        rows = inp.read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"  已记录 {len(rows)} 帧 ≈ {len(rows) / 60:.1f} 秒")


def _send_cmd(text):
    tmp = WORK / "cmd.txt.tmp"
    tmp.write_text(text + "\n", encoding="utf-8", newline="\n")
    for _ in range(50):
        try:
            os.replace(tmp, WORK / "cmd.txt")
            return
        except PermissionError:
            time.sleep(0.02)
    raise SystemExit("cmd.txt 写入失败（Lua 侧文件锁）")


def stop(quit=True, timeout=40.0):
    pid = running_pid()
    if pid:
        _send_cmd("quit" if quit else "stop")
    else:
        print("EmuHawk 已不在跑，只收尾产物")
    log = WORK / "capture.log"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if log.exists() and "stopped" in log.read_text(encoding="utf-8", errors="replace"):
            break
        time.sleep(0.2)
    inp = WORK / "inputs.tsv"
    if not inp.exists():
        raise SystemExit("inputs.tsv 缺失，看 capture.log")
    n = len(inp.read_text(encoding="utf-8", errors="replace").splitlines())
    print(f"记录 {n} 帧 ≈ {n / 60:.1f} 秒 → {inp}")
    st = WORK / "live_end.state"
    if st.exists():
        print(f"停录瞬间的状态（可从这个点继续跑）→ {st} ({st.stat().st_size} bytes)")
    build_bk2()
    return inp


def build_bk2():
    """inputs.tsv → BizHawk .bk2（用仓库里已验证的 bk2 写盘器，MD5 按去头口径）。"""
    F = _fceux()
    rom = Path((WORK / "source_rom.txt").read_text(encoding="utf-8").strip()
               if (WORK / "source_rom.txt").exists() else DEFAULT_ROM)
    rows = []
    for line in (WORK / "inputs.tsv").read_text(encoding="utf-8", errors="replace").splitlines():
        f, bs = line.split("\t")
        rows.append({"cmd": None, "p1": set(bs.split("+")) - {"-"}, "p2": set()})
    m = SimpleNamespace(source_format="live", errors=[], warnings=[], fourscore=False,
                        fds=False, pal=False, port0=1, port1=0, rerecord=0,
                        author="user-live-capture", game_name=rom.name,
                        md5=F._rom_md5(rom), header={}, frames=rows)
    out = WORK / "live.bk2"
    F.to_bk2(m, out, sha1=None, game_name=rom.name, author=m.author)
    print(f"录像容器 → {out} ({out.stat().st_size} bytes)，MD5(去头)={m.md5}，帧数={len(rows)}")
    return out


def ingest():
    inp = WORK / "inputs.tsv"
    if not inp.exists():
        raise SystemExit("先 stop 拿到 inputs.tsv")
    rows = []
    for line in inp.read_text(encoding="utf-8", errors="replace").splitlines():
        f, bs = line.split("\t")
        rows.append((int(f), [] if bs == "-" else bs.split("+")))
    f0 = rows[0][0]
    runs, tally = [], {}
    cur, start_i = None, 0
    for i, (_, bs) in enumerate(rows):
        for b in bs:
            tally[b] = tally.get(b, 0) + 1
        tok = "+".join(bs) if bs else "-"
        if tok != cur:
            if cur is not None:
                runs.append({"buttons": cur, "frames": i - start_i,
                             "frame": rows[start_i][0], "t": round((rows[start_i][0] - f0) / 60.0, 2)})
            cur, start_i = tok, i
    runs.append({"buttons": cur, "frames": len(rows) - start_i,
                 "frame": rows[start_i][0], "t": round((rows[start_i][0] - f0) / 60.0, 2)})
    ab = sum(1 for _, bs in rows if "A" in bs and "B" in bs)
    presses = [r for r in runs if r["buttons"] != "-"]
    out = {"frames": len(rows), "frame0": f0, "seconds": round(len(rows) / 60.0, 2),
           "tally_frames_pressed": tally, "ab_same_frame": ab,
           "select_press_events": sum(1 for p in presses if "Select" in p["buttons"].split("+")),
           "runs": runs}
    (WORK / "live_frames.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (WORK / "live_macro.txt").write_text(
        ", ".join(f"{r['buttons']}*{r['frames']}" for r in runs) + "\n", encoding="utf-8")
    print(f"共 {len(rows)} 帧（{len(rows) / 60:.1f}s），行程段数 {len(runs)}，非空操作段 {len(presses)}")
    print(f"按下帧数：{tally}")
    print(f"A+B 同帧（起跳）：{ab} 帧；换人(Select)事件：{out['select_press_events']} 次")
    print("操作时间轴（前 40 段）：")
    for r in presses[:40]:
        print(f"  f{r['frame']:>6}  t={r['t']:>6.2f}s  {r['buttons']:<18} 持续 {r['frames']:>4} 帧")
    print("→ live_frames.json / live_macro.txt")
    return out


def replay(every=30, max_shots=24):
    sys.path.insert(0, str(TOOLS))
    from PIL import Image
    from taspipe.statejump import StateSession
    bk2 = WORK / "live.bk2"
    if not bk2.exists():
        raise SystemExit("先 stop/build_bk2")
    rom = Path((WORK / "source_rom.txt").read_text(encoding="utf-8").strip())
    out = WORK / "replay"
    out.mkdir(parents=True, exist_ok=True)
    n = len((WORK / "inputs.tsv").read_text(encoding="utf-8", errors="replace").splitlines())
    print(f"回放 {bk2}：{n} 帧，ROM={rom}")
    shots = []
    with StateSession(rom=rom, bizhawk=BH, movie=bk2, work=str(out / "sess"), speed=100) as s:
        pos, i = 0, 0
        while pos < n and i < max_shots:
            step = min(every, n - pos)
            p = os.path.join(s.work, f"r{i:02d}.png").replace("\\", "/")
            s.run(step, shot=p)
            shots.append(Path(p))
            pos += step
            i += 1
    shots = [p for p in shots if p.exists()]
    if not shots:
        print("没有产物")
        return
    distinct = len({hashlib.sha1(p.read_bytes()).hexdigest() for p in shots})
    print(f"回放落盘 {len(shots)} 张，其中互不相同 {distinct} 张（全相同=电影没真放）")
    ims = [Image.open(p).convert("RGB") for p in shots]
    w, h = ims[0].size
    cols = 4
    sheet = Image.new("RGB", (w * cols, h * ((len(ims) + cols - 1) // cols)), (0, 0, 0))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    sheet.save(out / "replay_sheet.png")
    print(f"抽样拼图 → {out / 'replay_sheet.png'}（{len(ims)} 格，每 {every} 帧一格）")


# ------------------------------------------------------------------ 审计回放（放电影 + 采样内存）
AUDIT_TMPL = r'''
local dir = "__DIR__"
local step = __STEP__
local maxf = __MAXF__
client.speedmode(400)
local logf = io.open(dir .. "/audit.log", "w")
local bin = io.open(dir .. "/dumps.bin", "wb")
local function note(s) logf:write(s .. "\n"); logf:flush() end
note("mode=" .. tostring(movie.mode()))
local n = 0
while true do
	local f = emu.framecount()
	if f >= maxf then break end
	if n % step == 0 then
		local chunk = {}
		for a = 0, 2047 do chunk[#chunk + 1] = string.char(memory.read_u8(a) or 0) end
		bin:write(table.concat(chunk))
		local j = joypad.get(1)
		local pressed = {}
		for k, v in pairs(j) do if v then pressed[#pressed + 1] = k end end
		table.sort(pressed)
		note(string.format("D %d %d %s", n, f, #pressed > 0 and table.concat(pressed, "+") or "-"))
	end
	n = n + 1
	emu.frameadvance()
end
bin:close()
note("done records=" .. n)
logf:flush()
logf:close()
client.exit()
'''


def audit(step=90, max_frames=0, timeout=900.0):
    WORK.mkdir(parents=True, exist_ok=True)
    bk2 = WORK / "live.bk2"
    if not bk2.exists():
        raise SystemExit("先 stop/build_bk2")
    if not max_frames:
        max_frames = sum(1 for _ in (WORK / "inputs.tsv").open(encoding="utf-8", errors="replace")) + 200
    for f in ("dumps.bin", "audit.log"):
        if (WORK / f).exists():
            (WORK / f).unlink()
    (WORK / "audit").mkdir(exist_ok=True)
    # BizHawk 的 --movie 会自己接管录像，Lua 侧只读不写手柄
    shutil.copyfile(bk2, WORK / "movie.bk2")
    lua = WORK / "audit.lua"
    lua.write_text(AUDIT_TMPL.replace("__DIR__", str(WORK).replace("\\", "/"))
                   .replace("__STEP__", str(int(step))).replace("__MAXF__", str(int(max_frames))),
                   encoding="utf-8", newline="\n")
    rom = Path((WORK / "source_rom.txt").read_text(encoding="utf-8").strip())
    proc = subprocess.Popen([str(BH / "EmuHawk.exe"), f"--movie={WORK / 'movie.bk2'}",
                             f"--lua={lua}", str(rom)], cwd=str(BH),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = WORK / "audit.log"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if log.exists():
            txt = log.read_text(encoding="utf-8", errors="replace")
            if "done records=" in txt:
                recs = int(txt.split("done records=")[1].split()[0])
                size = (WORK / "dumps.bin").stat().st_size
                print(f"审计回放完成：{recs} 帧推进，采样 {size // 2048} 份 WRAM（{size} 字节）")
                proc.wait(timeout=20)
                return size // 2048
        if proc.poll() is not None and not log.exists():
            raise SystemExit("EmuHawk 提前退出且没写 audit.log")
        time.sleep(1.0)
    raise SystemExit(f"{timeout}s 未完成审计回放")


def _load_dumps():
    man = []
    for line in (WORK / "audit.log").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("D "):
            _, i, f, b = line.split(" ", 3)
            man.append((int(i), int(f), [] if b == "-" else b.split("+")))
    raw = (WORK / "dumps.bin").read_bytes()
    n = len(raw) // 2048
    if n != len(man):
        raise SystemExit(f"dumps.bin {n} 条 vs manifest {len(man)} 条，对不上")
    return man, [raw[i * 2048:(i + 1) * 2048] for i in range(n)]


def _pearson(xs, ys):
    n = len(xs)
    if n < 4:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(sum((b - my) ** 2 for b in ys))
    return 0.0 if dx == 0 or dy == 0 else num / (dx * dy)


def _deltas(xs):
    """8 位回绕安全的逐样本差分（屏幕坐标会从 255 绕回 0）。"""
    return [((b - a + 128) % 256) - 128 for a, b in zip(xs, xs[1:])]


def hunt(win=1000):
    """地址反查：以 OAM 解析出的屏幕坐标为探针，在 2KB WRAM 里找同步变化的字节。

    场上坐标（WRAM）= 屏幕坐标（精灵）+ 摄像机偏移，所以不能直接比绝对值；
    用逐帧差分的相关系数找"跟着一起动"的字节，再用等值命中率区分屏幕/场上口径。
    """
    man, dumps = _load_dumps()
    sys.path.insert(0, str(TOOLS))
    from taspipe import universal_authoring as UA
    parsed = {}
    for (i, f, bs), ram in zip(man, dumps):
        p = UA.soccer2_oam_parse(ram)
        if p:
            parsed[i] = (f, p)
    idx = sorted(parsed)
    if len(idx) < 20:
        raise SystemExit(f"可解析样本太少（{len(idx)}），先加长录制或减小 step")
    targets = {}
    for key, getter in (
        ("ball_x", lambda p: p["ball"][0]), ("ball_y", lambda p: p["ball"][1]),
        ("cap_x", lambda p: p["cap"][0]), ("cap_y", lambda p: p["cap"][1]),
        ("opp_x", lambda p: p["opp"][0] if p["opp"] else None),
        ("opp_y", lambda p: p["opp"][1] if p["opp"] else None),
    ):
        s = [getter(parsed[i][1]) for i in idx]
        if any(v is None for v in s):
            keep = [k for k, v in enumerate(s) if v is not None]
            if len(keep) < 20:
                continue
        else:
            keep = list(range(len(s)))
        targets[key] = (keep, [s[k] for k in keep])
    print(f"样本 {len(dumps)} 份（{len(idx)} 份可解析）；探针：" + ", ".join(targets))
    out = {}
    for key, (keep, vals) in targets.items():
        if len(set(vals)) < 6:
            print(f"  {key}: 几乎不动，跳过")
            continue
        d = _deltas(vals)
        rows = []
        for a in range(2048):
            series = [dumps[idx[k]][a] for k in keep]
            ds = _deltas(series)
            if len(set(ds)) < 4:
                continue
            r = _pearson(ds, d)
            if abs(r) < 0.35:
                continue
            # 场上口径（同缩放）/ 取反口径（Y 轴向下 vs 场上向上）
            scale = 1.0
            if abs(r) < 0.9:
                r_neg = _pearson(ds, [-x for x in d])
                if abs(r_neg) > abs(r):
                    r, scale = r_neg, -1.0
            exact = sum(1 for v, t in zip(series, vals) if abs(v - t) <= 2) / len(vals)
            rows.append({"addr": a, "hex": f"$0x{a:03X}", "r_delta": round(r, 3),
                         "exact_pct": round(exact * 100, 1), "scale": scale})
        rows.sort(key=lambda x: -abs(x["r_delta"]))
        out[key] = rows[:12]
        print(f"\n== {key} 同步字节 top（|r_delta|≥0.35）==")
        if not rows:
            print("  无候选")
        for row in rows[:8]:
            print(f"  {row['hex']:>7} r={row['r_delta']:+.3f} 等值命中={row['exact_pct']:5.1f}% "
                  f"scale={row['scale']:+.0f}")
    # 计时器/比分：在可解析窗口内单调不增、且只以小步长下降的字节
    clock = []
    for a in range(2048):
        series = [dumps[i][a] for i in idx]
        ds = [b - c for c, b in zip(series, series[1:])]
        if any(d > 0 for d in ds):
            continue
        drops = [d for d in ds if d < 0]
        if not (2 <= len(drops) <= len(ds) // 4):
            continue
        if max(abs(d) for d in drops) > 4:
            continue
        clock.append({"addr": a, "hex": f"$0x{a:03X}", "drops": len(drops),
                      "total": sum(drops)})
    clock.sort(key=lambda x: x["drops"])
    out["monotone_down"] = clock[:25]
    print(f"\n== 疑似计时/倒计时字节（只小步下降）：{len(clock)} 个，前 12 ==")
    for c in clock[:12]:
        print(f"  {c['hex']:>7} 下降 {c['drops']} 次 累计 {c['total']}")
    (WORK / "ram_hunt.json").write_text(json.dumps(
        {"samples": len(dumps), "parsed": len(idx),
         "frames": [parsed[i][0] for i in idx], "hunt": out},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {WORK / 'ram_hunt.json'}")
    return out


def practice_toggle():
    p = WORK / "practice.txt"
    new = not (p.exists() and p.read_text().strip() == "on")
    p.write_text("on" if new else "off", encoding="utf-8")
    print("练习态金手指：" + ("已开（下次 start --practice 生效）" if new else "已关"))
    return new


# ------------------------------------------------------------------ 合成真实按键
class _KEYINPUT(ctypes.Structure):
    _fields_ = [("wVk", WT.WORD), ("wScan", WT.WORD), ("dwFlags", WT.DWORD),
                ("time", WT.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", WT.DWORD), ("u", _U)]


_u32 = ctypes.windll.user32
_WNFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, WT.HWND, WT.LPARAM)


def find_window(pid):
    hits = []

    def cb(hwnd, _):
        p = WT.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and _u32.IsWindowVisible(hwnd) and _u32.GetWindowTextLengthW(hwnd) > 0:
            hits.append(hwnd)
        return True

    _u32.EnumWindows(_WNFUNC(cb), 0)
    return hits[0] if hits else None


def _key(scan, down):
    inp = _INPUT(type=1)
    inp.ki = _KEYINPUT(0, scan, 0x0008 if down else 0x000A, 0, None)
    return _u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def focus(hwnd):
    """把 EmuHawk 真正抢成前台窗，返回是否成功。

    11-15 实测坑：跨进程 SetForegroundWindow 受 Windows 前台锁限制会**静默失败**，
    SendInput 照样返回"已投递"但 BizHawk（WinForms KeyDown 轮询）一帧都收不到，
    录出来 331 帧全空 ⇒ 自测 6/9 FAIL。修法是把本线程输入队列临时接到前台线程上。
    """
    _u32.GetForegroundWindow.restype = ctypes.c_void_p
    _u32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
    cur = _u32.GetForegroundWindow()
    if cur == hwnd:
        return True
    ftid = _u32.GetWindowThreadProcessId(ctypes.c_void_p(cur), None)
    atid = _u32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), None)
    att = bool(ftid) and bool(atid) and ftid != atid
    if att:
        _u32.AttachThreadInput(ftid, atid, True)
    try:
        _u32.ShowWindow(ctypes.c_void_p(hwnd), 9)      # SW_RESTORE
        _u32.BringWindowToTop(ctypes.c_void_p(hwnd))
        _u32.SetActiveWindow(ctypes.c_void_p(hwnd))
        _u32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    finally:
        if att:
            _u32.AttachThreadInput(ftid, atid, False)
    for _ in range(20):
        time.sleep(0.1)
        if _u32.GetForegroundWindow() == hwnd:
            return True
    return False


def hold(scans, seconds):
    for sc in scans:
        _key(sc, True)
    time.sleep(seconds)
    for sc in reversed(scans):
        _key(sc, False)


def selftest():
    # 自测会开新录并清空 inputs.tsv —— 必须落在隔离目录，绝不碰真人录制
    global WORK
    WORK = SELFTEST
    print(f"== 0) 自测隔离目录 {WORK}（真人录制目录不受影响）==")
    print("== 1) 键位 ==")
    for k, v in apply_keys().items():
        print(f"  {k:10} = {v}")
    proc = start(DEFAULT_ROM, force=True)
    print(f"== 2) EmuHawk pid={proc.pid}，等画面 2 秒 ==")
    time.sleep(2.0)
    hwnd = find_window(proc.pid)
    print(f"== 3) 主窗口 hwnd={hwnd}")
    if not hwnd:
        raise SystemExit("找不到窗口，无法合成按键（真人键盘仍可录，但本轮没法自测）")
    old = _u32.GetForegroundWindow()
    got = focus(hwnd)
    print(f"== 3b) 抢前台 {'OK' if got else 'FAIL'}（hwnd={hwnd} 现前台={_u32.GetForegroundWindow()}）")
    time.sleep(0.5)
    try:
        print("== 4) 合成操作：D 右 0.6s → J+K 0.4s → L 换人 → ; 暂停 ==")
        hold([SCANCODE["D"]], 0.6)
        time.sleep(0.2)
        hold([SCANCODE["J"], SCANCODE["K"]], 0.4)
        time.sleep(0.2)
        hold([SCANCODE["L"]], 0.15)
        time.sleep(0.2)
        hold([SCANCODE["SEMI"]], 0.15)
        time.sleep(0.5)
    finally:
        _u32.SetForegroundWindow(old)
    stop(quit=True)
    data = ingest()
    t = data["tally_frames_pressed"]
    checks = [("方向 D→Right", t.get("Right", 0) > 0),
              ("J→A", t.get("A", 0) > 0),
              ("K→B", t.get("B", 0) > 0),
              ("A+B 同帧（起跳）", data["ab_same_frame"] > 0),
              ("L→Select（换人）", t.get("Select", 0) > 0),
              (";→Start（暂停）", t.get("Start", 0) > 0),
              ("录到 >120 帧（≈2 秒）", data["frames"] > 120),
              ("live.bk2 已生成", (WORK / "live.bk2").exists()),
              ("live_end.state 已生成", (WORK / "live_end.state").exists())]
    print("== 5) 闸门 ==")
    bad = 0
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        bad += 0 if ok else 1
    print(f"{'SELFTEST PASS' if not bad else 'SELFTEST FAIL'}（{len(checks) - bad}/{len(checks)}）")
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keys")
    p_start = sub.add_parser("start")
    p_start.add_argument("--rom", default=str(DEFAULT_ROM))
    p_start.add_argument("--force", action="store_true",
                         help="明知会清空现有 inputs.tsv 仍要开新录")
    sub.add_parser("status")
    p_stop = sub.add_parser("stop")
    p_stop.add_argument("--keep-window", action="store_true")
    sub.add_parser("bk2")
    sub.add_parser("ingest")
    p_rep = sub.add_parser("replay")
    p_rep.add_argument("--every", type=int, default=30)
    p_rep.add_argument("--max-shots", type=int, default=24)
    p_aud = sub.add_parser("audit")
    p_aud.add_argument("--step", type=int, default=90)
    p_aud.add_argument("--max-frames", type=int, default=0)
    sub.add_parser("hunt")
    sub.add_parser("practice")
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "keys":
        for k, v in apply_keys().items():
            print(f"{k:10} = {v}")
        print("（方向键/Z/X/Enter/Space 原绑定仍保留；画面左上角输入 OSD 已开）")
    elif a.cmd == "start":
        p = start(a.rom, force=a.force)
        print(f"开始记录 pid={p.pid}  ROM={a.rom}")
        print(f"产物在 {WORK}；打完跑 stop")
    elif a.cmd == "status":
        status()
    elif a.cmd == "stop":
        stop(quit=not a.keep_window)
    elif a.cmd == "bk2":
        build_bk2()
    elif a.cmd == "ingest":
        ingest()
    elif a.cmd == "replay":
        replay(a.every, a.max_shots)
    elif a.cmd == "audit":
        audit(step=a.step, max_frames=a.max_frames)
        hunt()
    elif a.cmd == "hunt":
        hunt()
    elif a.cmd == "practice":
        practice_toggle()
    elif a.cmd == "selftest":
        sys.exit(selftest())
    else:
        # 历史上这里写成 else=selftest()，打错子命令就把真人录制清了——绝不再兜底
        raise SystemExit(f"未知子命令 {a.cmd!r}")


if __name__ == "__main__":
    main()
