# -*- coding: utf-8 -*-
"""CX4 A/B 的恒量反证格：状态字节当尺子之前，先量这把尺子本身有多抖。

为什么要这一格（11-23 自己抓自己）：
  ab5 st1_none（空固件、60 帧）snap.m11 = 88,484 字节
  ab6 n0_none （空固件、60 帧）s60.m11  = 88,496 字节
同 ROM、同电影、同核心、同帧号、同样没固件，两个数不一样 ⇒ 跨进程本身就有抖动。
ab6/ab7 全靠「两臂状态字节差异数」下结论，不先量出抖动底数，任何差异都可能只是噪声。

三档对照，一次跑完（都在同一个进程里存两次，再和新进程比）：
  d1 同进程同帧存两次 s60a / s60b      => 相等 ⇒ 状态格式内不含时间戳/指针之类噪声
  d2 换新进程、配置完全相同，存 s60     => 与 d1 比 = 跨进程抖动底数
  d3 再换一次进程                     => 底数是否稳定（1 次观测不算数）
判读：
  跨进程差异 == 0            ⇒ ab6/ab7 的 n_diff 可以按字面归因给固件
  0 < 跨进程差异 << 固件臂差异 ⇒ 能归因，但要用差值而不是「有无」
  跨进程差异 ≈ 固件臂差异       ⇒ 这把尺子废了，只能回退到像素/行为口径
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import watchdog as WD      # noqa: E402
import tas_replay                        # noqa: E402

SCR = r"F:\taspipe_scratch\cx4_ab"
BIZ = os.path.join(SCR, "bizhawk")
MOVIE = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\movies\SNES\5628.bk2"
ROM = r"F:\BaiduNetdiskDownload\rom\snes\洛克人 X2.zip!洛克人 X2.sfc"

# 心跳按生产 cap.lua 的格式写（8 位帧号 + mode）：看门狗据此判"还在动"。
# ab6 没写心跳，把 stall_timeout 撑到 180s，光点一张固件框就白等 3 分钟。
LUA = '''
local dir = "%s/"
local hb = io.open(dir .. "heartbeat.txt", "w")
local out = io.open(dir .. "marks.txt", "w")
assert(hb, "heartbeat.txt 打不开：工作目录必须全 ASCII")
for i = 1, %d do
    emu.frameadvance()
    local fc = emu.framecount()
    hb:seek("set", 0)
    hb:write(string.format("%%08d %%-10s\\n", fc, tostring(movie.mode())))
    hb:flush()
    if fc == 60 then
        for _, nm in ipairs{%s} do
            savestate.save(dir .. nm .. ".m11")
            out:write("saved " .. nm .. " at " .. tostring(fc) .. "\\n"); out:flush()
        end
    end
end
out:close(); hb:close()
client.exit()
'''


def sha(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest().upper()


def difftable(a, b):
    x, y = open(a, "rb").read(), open(b, "rb").read()
    n = min(len(x), len(y))
    offs = [i for i in range(n) if x[i] != y[i]]
    return {"size_a": len(x), "size_b": len(y), "n_diff": len(offs),
            "first_offs": offs[:16], "last_offs": offs[-3:]}


def run_arm(tag, names):
    fw = os.path.join(BIZ, "Firmware")
    for f in os.listdir(fw):
        os.remove(os.path.join(fw, f))          # 三臂都空固件：配置完全相同
    w = os.path.join(SCR, tag)
    if os.path.isdir(w):
        shutil.rmtree(w)
    os.makedirs(w)
    m, r = os.path.join(w, "movie.bk2"), os.path.join(w, "rom.sfc")
    tas_replay.materialize_movie(MOVIE, m)
    tas_replay.materialize_rom(ROM, r)
    lua = os.path.join(w, "p.lua")
    with open(lua, "w", encoding="utf-8") as fh:
        fh.write(LUA % (w.replace("\\", "/"), 60,
                        ",".join('"%s"' % n for n in names)))
    log = os.path.join(w, "emulator.log")
    t0 = time.time()
    with open(log, "wb") as lf:
        proc = subprocess.Popen(
            [os.path.join(BIZ, "EmuHawk.exe"), "--chromeless",
             "--movie=" + m, "--lua=" + lua, r],
            cwd=BIZ, stdout=lf, stderr=subprocess.STDOUT)
        wd = WD.watch_process(proc, w)          # 全用生产默认（stall 30s / grace 8s）
    rec = {"termination": wd["termination"], "dismissed": wd["dismissed"],
           "stalls": wd["stalls"], "wall_s": round(time.time() - t0, 1),
           "heartbeat": open(os.path.join(w, "heartbeat.txt")).read().strip()
                        if os.path.isfile(os.path.join(w, "heartbeat.txt")) else "(none)",
           "marks": open(os.path.join(w, "marks.txt")).read().strip().splitlines()
                    if os.path.isfile(os.path.join(w, "marks.txt")) else [],
           "states": {f[:-4]: {"bytes": os.path.getsize(os.path.join(w, f)),
                               "sha1": sha(os.path.join(w, f))}
                      for f in sorted(os.listdir(w)) if f.endswith(".m11")},
           "fw_lines": WD.firmware_console_lines(log),
           "dialogs": [d.get("texts") for d in wd["dismissed_dialogs"]]}
    print("\n=== %s term=%s dismissed=%s stalls=%s %.1fs hb=%s states=%s" % (
        tag, wd["termination"], wd["dismissed"], wd["stalls"], rec["wall_s"],
        rec["heartbeat"], {k: v["bytes"] for k, v in rec["states"].items()}), flush=True)
    for d in rec["dialogs"]:
        print("    DLG:", str(d)[:200], flush=True)
    for ln in rec["fw_lines"]:
        print("    LOG:", ln[:170], flush=True)
    rec["_dir"] = w
    return rec


def main():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EmuHawk.exe"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace").stdout
    if "EmuHawk.exe" in out:
        print("!! EmuHawk 正在跑，本脚本不启动（严格串行）"); return 3
    tas_replay.force_core(BIZ, "SNES", "BSNES")
    a = run_arm("d1_same_proc", ["s60a", "s60b"])
    b = run_arm("d2_new_proc", ["s60"])
    c = run_arm("d3_new_proc2", ["s60"])

    def cmp(x, y, lbl):
        d = difftable(x, y)
        print("  %-28s n_diff=%-6s size %s->%s" % (lbl, d["n_diff"],
              d["size_a"], d["size_b"]), flush=True)
        return d

    same_proc = cmp(os.path.join(a["_dir"], "s60a.m11"),
                    os.path.join(a["_dir"], "s60b.m11"), "同进程同帧 s60a vs s60b")
    xp1 = cmp(os.path.join(a["_dir"], "s60a.m11"),
              os.path.join(b["_dir"], "s60.m11"), "跨进程 d1 vs d2")
    xp2 = cmp(os.path.join(b["_dir"], "s60.m11"),
              os.path.join(c["_dir"], "s60.m11"), "跨进程 d2 vs d3")
    xp3 = cmp(os.path.join(a["_dir"], "s60a.m11"),
              os.path.join(c["_dir"], "s60.m11"), "跨进程 d1 vs d3")
    res = {"arms": {k: {x: v[x] for x in v if x != "_dir"}
                    for k, v in (("d1", a), ("d2", b), ("d3", c))}}
    res["noise"] = {"same_proc": same_proc, "d1_d2": xp1, "d2_d3": xp2, "d1_d3": xp3}
    floor = max(x["n_diff"] for x in (xp1, xp2, xp3))
    res["cross_process_noise_floor"] = floor
    print("\n跨进程抖动底数 = %d 字节（同进程同帧 = %d）" % (floor, same_proc["n_diff"]),
          flush=True)
    with open(os.path.join(SCR, "ab8_control.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print("wrote", os.path.join(SCR, "ab8_control.json"), flush=True)
    return 0


sys.exit(main())
