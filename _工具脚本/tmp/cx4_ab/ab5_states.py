# -*- coding: utf-8 -*-
"""CX4 固件 A/B 追加臂：用 savestate 字节区分「没被调用」和「压根没读文件」。

前四臂（ab4）实测：无固件 / cx4.rom 1KB / cx4.rom 32KB×0xCD / SNES_cx4.rom 32KB×0xCD
四者 2000 帧 PNG 逐帧 sha1 全等，全程 0 弹框，日志各只有一句
    Served libsnes request for firmware "cx4.rom"
⇒ 前 2000 帧（版权页+开场）的像素与固件内容无关。原因可能是：
  (i)  这几帧没调用 CX4（芯片内容根本没参与运算）；或
  (ii) BizHawk 那句「Served」没读 Firmware/ 里的文件（放文件是空动作）。

区分办法不靠画面：只跑 60 帧就 savestate，比状态文件字节。bsnes 会把 CX4 芯片的
32KB 程序存储器序列化进状态，所以
  状态不同 / 状态里能搜到那串 0xCD  => (ii) 不成立，文件真被读进芯片
                                        ⇒ 芯片只是还没被调用，放真固件才有意义
  状态完全相同                       => (ii) 成立，BizHawk 回的是空包/内置内容
                                        ⇒ D1「放固件」这个动作对本代码路径无效
"""
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import registry as R       # noqa: E402
from taspipe import watchdog as WD      # noqa: E402
import tas_replay                       # noqa: E402

SCRATCH = r"F:\taspipe_scratch\cx4_ab"
BIZHAWK = os.path.join(SCRATCH, "bizhawk")
JSON_ID = r"F:\开源掌机教程\_工具脚本\tmp\cx4_ab\assess_5628.json"
FRAMES = 60
ARMS = [("st1_none", None),
        ("st2_cx4rom_32k_CD", ("cx4.rom", 32768)),
        ("st3_cx4rom_1k", ("cx4.rom", 1024))]
FILL = bytes([0xCD])


def sha(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest().upper()


def find_states(d):
    """工作目录里所有看起来是 bsnes 状态的文件（扩展名 m11/state/bsnes）。"""
    out = []
    for root, _dirs, files in os.walk(d):
        for f in files:
            if f.endswith((".m11", ".state", ".bsnes", ".srm")):
                out.append(os.path.join(root, f))
    return sorted(out)


def main():
    a = json.load(open(JSON_ID, encoding="utf-8"))["assess"]
    movie, rom, core, system = (a["movie"], a["rom_match"][0], a["core"], a["platform_code"])
    fw_dir = os.path.join(BIZHAWK, "Firmware")
    res = {"frames": FRAMES, "arms": {}}
    for key, spec in ARMS:
        for f in os.listdir(fw_dir):
            os.remove(os.path.join(fw_dir, f))
        placed = None
        if spec:
            fn, size = spec
            placed = {"name": fn, "size": size, "fill": "0xCD"}
            with open(os.path.join(fw_dir, fn), "wb") as fh:
                fh.write(FILL * size)
            placed["sha1"] = sha(os.path.join(fw_dir, fn))
        work = os.path.join(SCRATCH, key)
        if os.path.isdir(work):
            import shutil
            shutil.rmtree(work)
        os.makedirs(os.path.join(work, "frames"), exist_ok=True)
        t0 = time.time()
        m = os.path.join(work, "movie.bk2")
        rr = os.path.join(work, "rom.sfc")
        tas_replay.materialize_movie(movie, m)
        tas_replay.materialize_rom(rom, rr)
        lua = os.path.join(work, "ss.lua")
        with open(lua, "w", encoding="utf-8") as fh:
            fh.write(
                'local d = "%s/"\nfor i = 1, %d do emu.frameadvance() end\n'
                'savestate.save(d .. "snap.m11")\n'
                'local f = io.open(d .. "ss.txt", "w")\n'
                'f:write("saved n=" .. tostring(emu.framecount()))\nf:close()\n'
                'client.exit()\n' % (work.replace("\\", "/"), FRAMES))
        proc = subprocess.Popen(
            [os.path.join(BIZHAWK, "EmuHawk.exe"), "--chromeless",
             "--movie=" + m, "--lua=" + lua, rr],
            cwd=BIZHAWK, stdout=open(os.path.join(work, "emulator2.log"), "wb"),
            stderr=subprocess.STDOUT)
        wd2 = WD.watch_process(proc, work, hard_timeout=400, stall_timeout=90)
        states = find_states(work)
        info = {}
        for s in states:
            b = open(s, "rb").read()
            info[os.path.basename(s)] = {
                "bytes": len(b), "sha1": sha(s),
                "runs_of_CD": b.count(FILL * 64),
                "has_32k_CD_block": FILL * 32768 in b,
                "cd_total": b.count(FILL),
            }
        log2 = os.path.join(work, "emulator2.log")
        res["arms"][key] = {
            "firmware_placed": placed,
            "save_term": wd2["termination"],
            "save_note": open(os.path.join(work, "ss.txt")).read().strip()
                         if os.path.isfile(os.path.join(work, "ss.txt")) else "(no ss.txt)",
            "wall_s": round(time.time() - t0, 1),
            "states": info,
            "console_fw_lines": WD.firmware_console_lines(log2) or
                                WD.firmware_console_lines(os.path.join(work, "emulator.log")),
        }
        print("\n=== %s placed=%s  save=%s %s" % (
            key, placed and placed["name"], wd2["termination"],
            res["arms"][key]["save_note"]), flush=True)
        for n, v in info.items():
            print("   STATE %s bytes=%d sha1=%s CD64runs=%d has32KCD=%s cd_total=%d" % (
                n, v["bytes"], v["sha1"][:12], v["runs_of_CD"],
                v["has_32k_CD_block"], v["cd_total"]), flush=True)
        for ln in res["arms"][key]["console_fw_lines"]:
            print("   LOG:", ln[:170], flush=True)

    base = res["arms"]["st1_none"]["states"]
    for key, _s in ARMS[1:]:
        other = res["arms"][key]["states"]
        for n in other:
            b = base.get(n)
            print("\n%s/%s vs none: sha 相同=%s 字节数 %s→%s" % (
                key, n, b and b["sha1"] == other[n]["sha1"],
                b and b["bytes"], other[n]["bytes"]), flush=True)
    with open(os.path.join(SCRATCH, "ab5_states.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nwrote", os.path.join(SCRATCH, "ab5_states.json"), flush=True)


main()
