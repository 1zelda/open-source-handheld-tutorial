# -*- coding: utf-8 -*-
"""CX4 固件：文件名归属（ab6）+ 内容是否参与运算（ab7），串行跑（EmuHawk 一次一个）。

已实测（ab5，本机 5628 真机）：
  st1 空目录        snap.m11 88,484 字节 sha1 7FD81185D20A…
  st2 cx4.rom=32K   snap.m11 88,493 字节 sha1 86F2D0D348A2…   => 文件被读、进了芯片状态
而 ab4 的四臂 2000 帧 PNG 逐帧 sha 全等 => 那 2000 帧里芯片内容没影响像素。
两个问题还没答：
  ab6 到底认哪个文件名：BizHawk 固件表写的是 SNES_cx4.rom，核心请求串是 cx4.rom。
      只放表名 / 只放裸名 / 两个都放，看状态字节跟哪个基线一致。
  ab7 内容有没有真参与运算：把 30,000 帧处的状态与 60 帧处的状态比。
      若两臂差异只在固件来源字段（差异字节数不随帧数增长）=> 芯片只是被装载、没执行；
      若差异变大 => CX4 确实执行过，本机现在跑的是「芯片里没有程序」的状态，
      出版级复刻必须放经独立印证的真实 CX4 dump（哈希目标 188D471F…，不是 Header 那个）。
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
FILL = bytes([0xCD])

LUA = '''
local dir = "%s/"
local marks = {%s}
local out = io.open(dir .. "marks.txt", "w")
for i = 1, %d do
    emu.frameadvance()
    local fc = emu.framecount()
    for _, m in ipairs(marks) do
        if fc == m then
            savestate.save(dir .. "s" .. m .. ".m11")
            out:write("saved " .. m .. "\\n"); out:flush()
        end
    end
end
out:write("end n=" .. tostring(emu.framecount()) .. " mode=" .. tostring(movie.mode()) .. "\\n")
out:close()
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
            "first_offs": offs[:12], "last_offs": offs[-3:]}


def run_arm(tag, files, frames, marks):
    """files: [(名字, 长度)]；marks: 在这些帧号存状态。返回结构化结果。"""
    fw = os.path.join(BIZ, "Firmware")
    for f in os.listdir(fw):
        os.remove(os.path.join(fw, f))
    placed = []
    for name, size in files:
        with open(os.path.join(fw, name), "wb") as fh:
            fh.write(FILL * size)
        placed.append({"name": name, "size": size,
                       "sha1": sha(os.path.join(fw, name))})
    w = os.path.join(SCR, tag)
    if os.path.isdir(w):
        shutil.rmtree(w)
    os.makedirs(w)
    m = os.path.join(w, "movie.bk2")
    r = os.path.join(w, "rom.sfc")
    tas_replay.materialize_movie(MOVIE, m)
    tas_replay.materialize_rom(ROM, r)
    lua = os.path.join(w, "p.lua")
    with open(lua, "w", encoding="utf-8") as fh:
        fh.write(LUA % (w.replace("\\", "/"),
                        ",".join(str(x) for x in marks), frames))
    log = os.path.join(w, "emulator.log")
    t0 = time.time()
    with open(log, "wb") as lf:
        proc = subprocess.Popen(
            [os.path.join(BIZ, "EmuHawk.exe"), "--chromeless",
             "--movie=" + m, "--lua=" + lua, r],
            cwd=BIZ, stdout=lf, stderr=subprocess.STDOUT)
        wd = WD.watch_process(proc, w, hard_timeout=None if frames < 2000 else 5400,
                              stall_timeout=180, dismiss_grace=8, auto_dismiss=True)
    states = {f[:-4]: os.path.join(w, f) for f in sorted(os.listdir(w))
              if f.endswith(".m11")}
    rec = {"placed": placed, "frames": frames, "wall_s": round(time.time() - t0, 1),
           "termination": wd["termination"],
           "marks": open(os.path.join(w, "marks.txt")).read().strip().splitlines()
                    if os.path.isfile(os.path.join(w, "marks.txt")) else [],
           "states": {k: {"bytes": os.path.getsize(v), "sha1": sha(v)}
                      for k, v in states.items()},
           "fw_lines": WD.firmware_console_lines(log),
           "gate": WD.firmware_verdict(dict(wd, console_texts=WD.firmware_console_lines(log)))}
    print("\n=== %s placed=%s term=%s %.1fs states=%s" % (
        tag, [p["name"] for p in placed], wd["termination"], rec["wall_s"],
        {k: v["bytes"] for k, v in rec["states"].items()}), flush=True)
    for ln in rec["fw_lines"]:
        print("    LOG:", ln[:170], flush=True)
    print("    GATE:", rec["gate"][0], str(rec["gate"][2]), flush=True)
    rec["_paths"] = states
    return rec


def main():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EmuHawk.exe"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    if "EmuHawk.exe" in out:
        print("!! EmuHawk 正在跑，本脚本不启动"); return 3
    tas_replay.force_core(BIZ, "SNES", "BSNES")
    res = {}

    # ---------- ab6：哪个文件名算数（60 帧，秒级） ----------
    ab6 = {}
    for tag, files in [("n0_none", []),
                       ("n1_bare_cx4rom", [("cx4.rom", 32768)]),
                       ("n2_db_name", [("SNES_cx4.rom", 32768)]),
                       ("n3_both", [("cx4.rom", 32768), ("SNES_cx4.rom", 32768)]),
                       ("n4_wrong_len", [("cx4.rom", 1024)])]:
        ab6[tag] = run_arm(tag, files, 60, [60])
    base = ab6["n0_none"]["_paths"].get("s60")
    res["ab6"] = {}
    for tag, rec in ab6.items():
        p = rec["_paths"].get("s60")
        d = difftable(base, p) if p and base and tag != "n0_none" else None
        res["ab6"][tag] = {k: v for k, v in rec.items() if k != "_paths"}
        res["ab6"][tag]["diff_vs_none"] = d
        print("  %-16s s60 sha=%s diff=%s" % (
            tag, rec["states"].get("s60", {}).get("sha1", "")[:12],
            d and d["n_diff"]), flush=True)

    # ---------- ab7：内容有没有参与运算（30,000 帧 vs 60 帧） ----------
    marks = [60, 10000, 20000, 30000]
    a = run_arm("L1_none", [], 30000, marks)
    b = run_arm("L2_dummy32k", [("cx4.rom", 32768)], 30000, marks)
    res["ab7"] = {"none": {k: v for k, v in a.items() if k != "_paths"},
                  "dummy": {k: v for k, v in b.items() if k != "_paths"},
                  "diff_by_mark": {}}
    for mk in marks:
        pa, pb = a["_paths"].get("s%d" % mk), b["_paths"].get("s%d" % mk)
        d = difftable(pa, pb) if pa and pb else None
        res["ab7"]["diff_by_mark"]["s%d" % mk] = d
        print("  mark %-7s none=%s dummy=%s 差异字节=%s" % (
            mk, a["states"].get("s%d" % mk, {}).get("sha1", "")[:10],
            b["states"].get("s%d" % mk, {}).get("sha1", "")[:10],
            d and d["n_diff"]), flush=True)

    with open(os.path.join(SCR, "names_and_growth.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print("\nwrote", os.path.join(SCR, "names_and_growth.json"), flush=True)
    return 0


sys.exit(main())
