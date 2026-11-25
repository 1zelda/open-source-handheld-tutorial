# -*- coding: utf-8 -*-
"""CX4 固件·存档级 A/B（免截图，比 ab4 的逐帧 PNG 便宜一个量级）。

ab4 已经量到：空目录 / cx4.rom=1K / cx4.rom=32K(0xCD) 三种条件下，5628 前 2000 帧
PNG 逐帧 sha 全等。这只说明「这 2000 帧的像素不受 CX4 程序存储器影响」，没说明
BizHawk 那句 Served libsnes request 到底给了核心什么。

本探针回答后者：回放同一部电影到同一帧，把 savestate 落盘后逐字节比。
  状态相同  => 那份文件根本没进 CX4 的程序存储器（"Served" 只是个空回包），
              放文件这条路对结果无影响，D1 的「放固件」动作可以撤。
  状态不同  => 文件真被读进芯片，本机现在跑的是「CX4 程序存储器为空」的机器状态，
              与作者当时的机器状态不等价 => 出版前必须放真固件（哈希 188D... 且验签）。

EmuHawk 严格串行，本脚本一次只起一个进程，跑前自己确认没有别的 EmuHawk 在跑。
"""
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import registry as R          # noqa: E402
from taspipe import watchdog as WD         # noqa: E402
import tas_replay                          # noqa: E402

SCR = r"F:\taspipe_scratch\cx4_state"
BIZ = r"F:\taspipe_scratch\cx4_ab\bizhawk"      # ASCII 副本（ab4 用的那份）
MOVIE = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\movies\SNES\5628.bk2"
ROM = r"F:\BaiduNetdiskDownload\rom\snes\洛克人 X2.zip!洛克人 X2.sfc"
FRAMES = 1500

LUA = """
local dir = "%s/"
local N = %d
for i = 1, N do emu.frameadvance() end
savestate.save(dir .. "state.m11")
local f = io.open(dir .. "done.txt", "w")
f:write("n=" .. tostring(emu.framecount()) .. " mode=" .. tostring(movie.mode()) .. "\\n")
f:close()
client.exit()
"""


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def diffbytes(a, b):
    """两条状态串的第一个差异偏移与差异字节数（全等返回 None/0）。"""
    if not (os.path.isfile(a) and os.path.isfile(b)):
        return "missing", None, None
    x, y = open(a, "rb").read(), open(b, "rb").read()
    if len(x) != len(y):
        return ("size %d vs %d" % (len(x), len(y))), None, None
    d = [i for i in range(0, len(x)) if x[i] != y[i]]
    return None, len(x), len(d)


def first_diff(a, b):
    x, y = open(a, "rb").read(), open(b, "rb").read()
    for i in range(min(len(x), len(y))):
        if x[i] != y[i]:
            return i, x[i - 16:i + 48], y[i - 16:i + 48]
    return None, b"", b""


def main():
    # 串行闸门：有别的 EmuHawk 在跑就直接退出，不排队也不抢锁。
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EmuHawk.exe"],
                         capture_output=True, text=True).stdout
    if "EmuHawk.exe" in out:
        print("!! 已有 EmuHawk 在跑，本探针不启动（EmuHawk 严格串行）")
        return 3
    os.makedirs(SCR, exist_ok=True)
    fw = os.path.join(BIZ, "Firmware")
    for f in os.listdir(fw):
        os.remove(os.path.join(fw, f))
    rom_local = os.path.join(SCR, "rom.sfc")
    tas_replay.materialize_rom(ROM, rom_local)
    movie_local = os.path.join(SCR, "movie.bk2")
    tas_replay.materialize_movie(MOVIE, movie_local)
    tas_replay.force_core(BIZ, "SNES", "BSNES")

    conds = [("none", None), ("cx4rom_32k_CD", ("cx4.rom", 32768, 0xCD)),
             ("cx4rom_32k_00", ("cx4.rom", 32768, 0x00)),
             ("SNES_cx4rom_32k_CD", ("SNES_cx4.rom", 32768, 0xCD))]
    res = {"frames": FRAMES, "conds": {}}
    states = {}
    for name, spec in conds:
        for f in os.listdir(fw):
            os.remove(os.path.join(fw, f))
        placed = None
        if spec:
            fn, size, fill = spec
            with open(os.path.join(fw, fn), "wb") as fh:
                fh.write(bytes([fill]) * size)
            placed = {"name": fn, "size": size, "fill": hex(fill),
                      "sha1": __import__("hashlib").sha1(
                          open(os.path.join(fw, fn), "rb").read()).hexdigest().upper()}
        w = os.path.join(SCR, "w_" + name)
        os.makedirs(w, exist_ok=True)
        for junk in ("state.m11", "done.txt"):
            if os.path.exists(os.path.join(w, junk)):
                os.remove(os.path.join(w, junk))
        lua = os.path.join(w, "p.lua")
        with open(lua, "w", encoding="ascii") as fh:
            fh.write(LUA % (w.replace("\\", "/"), FRAMES))
        log = os.path.join(w, "emulator.log")
        t0 = time.time()
        with open(log, "wb") as lf:
            proc = subprocess.Popen(
                [os.path.join(BIZ, "EmuHawk.exe"), "--chromeless",
                 "--movie=" + movie_local, "--lua=" + lua, rom_local],
                cwd=BIZ, stdout=lf, stderr=subprocess.STDOUT)
            wd = WD.watch_process(proc, w, hard_timeout=900, stall_timeout=60,
                                  dismiss_grace=8, auto_dismiss=True)
        sp = os.path.join(w, "state.m11")
        st = {"placed": placed, "wall_s": round(time.time() - t0, 1),
              "termination": wd["termination"],
              "done": open(os.path.join(w, "done.txt")).read().strip()
                     if os.path.isfile(os.path.join(w, "done.txt")) else None,
              "state_bytes": os.path.getsize(sp) if os.path.isfile(sp) else None,
              "state_sha256": sha256(sp) if os.path.isfile(sp) else None,
              "console_fw_lines": WD.firmware_console_lines(log),
              "gate": WD.firmware_verdict(
                  dict(wd, console_texts=WD.firmware_console_lines(log)))}
        res["conds"][name] = st
        if os.path.isfile(sp):
            states[name] = sp
        print("%-20s term=%-16s %s bytes=%s sha=%s %.1fs" % (
            name, st["termination"], st["done"], st["state_bytes"],
            str(st["state_sha256"])[:16], st["wall_s"]), flush=True)
        for ln in st["console_fw_lines"]:
            print("      LOG:", ln[:170], flush=True)
        print("      GATE:", st["gate"][0], "|", st["gate"][1][:120], flush=True)

    base = states.get("none")
    res["diff_vs_none"] = {}
    for name, sp in states.items():
        if name == "none":
            continue
        size, total, nd = diffbytes(base, sp)
        off, xa, xb = first_diff(base, sp) if size is None else (None, b"", b"")
        res["diff_vs_none"][name] = {"note": size, "bytes": total, "n_diff": nd,
                                     "first_off": off,
                                     "none_ctx": xa.hex(), "other_ctx": xb.hex()}
        print("\nnone vs %s: %s 总字节=%s 差异字节数=%s 首个差异偏移=%s" % (
            name, size, total, nd, off), flush=True)
        if off is not None:
            print("   none  :", xa.hex(), flush=True)
            print("   other :", xb.hex(), flush=True)
    with open(os.path.join(SCR, "state_ab.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print("\nwrote", os.path.join(SCR, "state_ab.json"))
    return 0


sys.exit(main())
