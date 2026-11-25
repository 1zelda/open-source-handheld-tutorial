# -*- coding: utf-8 -*-
"""ab18：同一批次里交叉跑 ab11 与 ab16 两条代码路径，把「谁弹框」和「用的哪个核心」一起量出来。

前情（全部实测，没有一条靠推）：
  * ab11（11-23 早）：注册键 bisect 8 臂，只有 `CX4` / `SNES+CX4` 两个键那次固件警告框**没出现**
    （k0_none disc=3/91.6s，k1_spec_all disc=1/33.1s，solo key_CX4 fw_dlg=0）。
  * ab17（本轮）：直接调 ab11 自己的 `run_arm`，r0_none fw=1/93.1s、r1_key_CX4 **fw=0/disc=0/9.0s**
    ⇒ ab11 的抑制在当下、用 ab11 自己的代码**复现了**。
  * ab16（本轮，紧接在前）：b1_spec_CX4rom_inFW 注册 `CX4`→`Firmware/cx4.rom`(32KB 0xCD)，
    disc=3、fw=1、91.7s ⇒ 同一套**没抑制**。
  * 本轮静态核对（不烧模拟器）：`A11.set_spec` 与 `A16.spec_blob` 对同一 base 产出的
    `FirmwareUserSpecifications` 块与整本 config **逐字节相同**（sha 7bffef5749a7）；
    SCR/BIZ/CFG/MOVIE/ROM 五个常量 ab11==ab12==ab16 全部相同；
    注册目标路径 ab11.DUMMY == ab16 的 FW_DIR/cx4.rom。
  ⇒ 所以「参数不同」被排除了。剩下的可能只有两类：
    （甲）两条路径在**启动那一刻的机器状态**上不同（批次内前面的臂留下的东西、核心选择、
         config 被 EmuHawk 退出时回写……），而批次顺序恰好把差异带到了 b1；
    （乙）ab11/ab17 的「没弹框」根本不是固件找到了，而是**那次压根没走到固件请求**
         （例如换了核心：Snes9x 不发 libsnes 固件请求 ⇒ 无框，且用时更短）。
    乙 这条现在有具体形状：ab17 r1 连 `Administrator privileges` 那张框都没有（disc=0），
    而每一臂「正常启动」的批都稳定有那张框；用时 9.0s 也远低于其他臂的 ~90s。

四臂（串行，一次一个 EmuHawk）：
  x1_ab11_none   走 ab11.run_arm，不注册            —— 同批基线（预期 fw=1）
  x2_ab11_CX4    走 ab11.run_arm，注册 CX4          —— 复现 ab17（预期 fw=0）
  x3_ab16_CX4    走 ab16.run，注册 CX4（=b1 等价）  —— 复现 ab16（预期 fw=1）
  x4_ab11_CX4    再走一次 ab11.run_arm，注册 CX4    —— 稳定性（不是单发巧合）

两条路径的 Lua 我都换成同一份增强版（只往 ab11 的模块常量上打补丁，不改文件本身）：
  心跳里多写一行 `core=<client.get_core_name()>`，并在退出前存一个 60 帧状态 `s60.m11`。
  ⇒ 核心名直接判 乙；状态字节 x2 vs x1 的底层差异判「抑制到底有没有把字节喂进核心」
     （底数参考 §45.4：帧 60 的跨进程噪声 234–297 字节，画面 sha1 帧 60 恒等）。
"""
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ab11_spec as A11        # noqa: E402
import ab16_name as A16        # noqa: E402
import state_decode as SD      # noqa: E402
from taspipe import watchdog as WD   # noqa: E402

OUT = os.path.join(A16.SCR, "ab18_xbatch.json")

LUA_X = '''
local dir = "%s/"
local hb = io.open(dir .. "heartbeat.txt", "w")
local okc, cn = pcall(function() return client.get_core_name() end)
hb:write("core=" .. (okc and tostring(cn) or "取不到") .. "\\n"); hb:flush()
for i = 1, 60 do emu.frameadvance() end
hb:write(string.format("%%08d %%-10s\\n", emu.framecount(), tostring(movie.mode()))); hb:flush()
savestate.save(dir .. "s60.m11")
hb:write("saved\\n"); hb:close()
client.exit()
'''


def state_metrics(tag):
    sp = os.path.join(A16.SCR, tag, "s60.m11")
    if not os.path.exists(sp):
        return {"state": "无"}
    parts = SD.parts(sp)
    core, fb = parts["Core.bin"], parts["Framebuffer.bmp"]
    return {"state": os.path.getsize(sp), "core_len": len(core),
            "core_sha1": hashlib.sha1(core).hexdigest(),
            "fb_len": len(fb), "fb_sha1": hashlib.sha1(fb).hexdigest()}


def core_from_hb(tag):
    p = os.path.join(A16.SCR, tag, "heartbeat.txt")
    return open(p, encoding="utf-8", errors="replace").read().strip() if os.path.exists(p) else "无"


def cfg_spec_now():
    blob = A11.read_cfg()
    m = A16.SPEC_PAT.search(blob)
    return m.group() if m else "(无该字段)"


def run_ab11(tag, spec):
    """按 ab11.run_arm 的调用序列重跑一遍，但用增强版 Lua（存状态 + 报核心名）。

    说清楚：这里**不是**直接调 `A11.run_arm`——原版的 Lua 不存状态也不报核心，量不到要问的两件事。
    用的是 ab11 模块里的同一批常量与函数（BIZ/CFG/SCR/MOVIE/ROM/DUMMY/FILL/read_cfg/set_spec），
    删文件→写假字节→写注册块→启动→还原，顺序照 ab11 的源码逐行对齐（含「假字节先于 config」）。
    ab17 已经证明直接调 `A11.run_arm` 能复现 fw=0，所以这里换 Lua 只补观测、不改臂的成立性。
    """
    def patched(t, dummy_file, sp):
        fw = os.path.join(A11.BIZ, "Firmware")
        for f in os.listdir(fw):
            os.remove(os.path.join(fw, f))
        if dummy_file:
            with open(A11.DUMMY, "wb") as fh:
                fh.write(A11.FILL * 32768)
        base = A11.read_cfg()
        with open(A11.CFG, "w", encoding="utf-8") as fh:
            fh.write(A11.set_spec(base, sp) if sp else base)
        launched = cfg_spec_now()
        w = os.path.join(A11.SCR, t)
        import shutil
        if os.path.isdir(w):
            shutil.rmtree(w)
        os.makedirs(w)
        m, r = os.path.join(w, "movie.bk2"), os.path.join(w, "rom.sfc")
        import tas_replay
        tas_replay.materialize_movie(A11.MOVIE, m)
        tas_replay.materialize_rom(A11.ROM, r)
        lua = os.path.join(w, "cap.lua")
        with open(lua, "w", encoding="utf-8") as fh:
            fh.write(LUA_X % (w.replace("\\", "/"), ))
        t0 = time.time()
        try:
            import subprocess
            with open(os.path.join(w, "emulator.log"), "wb") as lf:
                proc = subprocess.Popen([os.path.join(A11.BIZ, "EmuHawk.exe"), "--chromeless",
                                         "--movie=" + m, "--lua=" + lua, r],
                                        cwd=A11.BIZ, stdout=lf, stderr=subprocess.STDOUT)
                wd = WD.watch_process(proc, w, hard_timeout=900)
        finally:
            with open(A11.CFG, "w", encoding="utf-8") as fh:
                fh.write(base)
        dialogs = [t for rec in wd["dismissed_dialogs"] for t in rec["texts"]]
        fw_hits = [t for t in dialogs if A16.FW_WARN_RE.search(t)]
        return {"tag": t, "path": "ab11", "spec": sorted(sp or {}),
                "cfg_spec_at_launch": launched, "termination": wd["termination"],
                "dismissed": wd["dismissed"], "wall": round(time.time() - t0, 1),
                "fw_dialogs": fw_hits, "dialogs": dialogs,
                "console": WD.firmware_console_lines(os.path.join(w, "emulator.log")),
                "cfg_spec_after": cfg_spec_now()}

    return patched(tag, bool(spec), spec)


def main():
    if A11.emuhawk_running():
        print("!! EmuHawk 正在跑，串行规矩，本批不启动"); return 3
    import tas_replay
    tas_replay.force_core(A11.BIZ, "SNES", "BSNES")
    print("起跑前注册块:", cfg_spec_now(), flush=True)
    res = {}
    plan = [("x1_ab11_none", "ab11", None),
            ("x2_ab11_CX4", "ab11", {"CX4": A11.DUMMY}),
            ("x3_ab16_CX4", "ab16", {"CX4": os.path.join(A16.FW_DIR, "cx4.rom")}),
            ("x4_ab11_CX4", "ab11", {"CX4": A11.DUMMY})]
    for tag, path, spec in plan:
        if path == "ab11":
            rec = run_ab11(tag, spec)
        else:
            r = A16.run(tag, "CX4", os.path.join(A16.FW_DIR, "cx4.rom"), 32768, 0xCD)
            rec = {"tag": tag, "path": "ab16", "spec": ["CX4"],
                   "cfg_spec_at_launch": "(ab16 未存启动瞬间，见 spec_path)",
                   "termination": r["termination"], "dismissed": r["dismissed"],
                   "wall": r["wall"], "fw_dialogs": r["fw_dialogs"], "dialogs": r["dialogs"],
                   "console": r["fw_console"], "cfg_spec_after": r["config_spec_after"]}
        rec["heartbeat"] = core_from_hb(tag)
        rec["started"] = bool(re.search(r"^\d{8}\s", rec["heartbeat"], re.M))
        rec.update(state_metrics(tag))
        res[tag] = rec
        print("\n=== %-12s 路径=%-5s 注册=%-6s disc=%s fw=%s term=%s %.1fs" %
              (tag, rec["path"], rec["spec"], rec["dismissed"], len(rec["fw_dialogs"]),
               rec["termination"], rec["wall"]), flush=True)
        print("    心跳/核心:", repr(rec["heartbeat"]).replace("\\n", " | "))
        print("    启动瞬间注册块:", rec["cfg_spec_at_launch"][:180])
        print("    跑后注册块:", rec["cfg_spec_after"][:180])
        for d in rec["dialogs"]:
            print("    DLG:", d[:150])
        for l in rec["console"]:
            print("    FWC:", l[:150])
        print("    core_len=%s core_sha1=%s fb_sha1=%s" % (rec.get("core_len"),
              str(rec.get("core_sha1"))[:12], str(rec.get("fb_sha1"))[:12]), flush=True)
        if not rec["started"]:
            print("\n!! %s 心跳里没有 8 位帧号⇒压根没跑（term=%s hb=%r），本臂作废、停批" %
                  (tag, rec["termination"], rec["heartbeat"][:60]), flush=True)
            break
        with open(OUT.replace(".json", "_partial.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1, default=str)

    print("\n--- 核心名（判 乙：没弹框是不是因为换了核心）")
    for t, v in res.items():
        print("  %-12s %s" % (t, v["heartbeat"].splitlines()[0] if v["heartbeat"] else "无"))
    print("--- 画面（帧 60 Framebuffer.bmp sha1）")
    print("  ", {t: str(v.get("fb_sha1"))[:12] for t, v in res.items()})
    print("--- 状态（Core.bin 底层 vs x1 基线的差异字节，底数 234–297）")
    base = None
    if "x1_ab11_none" in res and res["x1_ab11_none"].get("core_sha1"):
        bp = os.path.join(A16.SCR, "x1_ab11_none", "s60.m11")
        base = SD.parts(bp)["Core.bin"] if os.path.exists(bp) else None
    for t, v in res.items():
        sp = os.path.join(A16.SCR, t, "s60.m11")
        if base and os.path.exists(sp):
            c = SD.parts(sp)["Core.bin"]
            d = sum(1 for a, b in zip(c, base) if a != b) if len(c) == len(base) else -1
            print("  %-12s len=%s diff_vs_x1=%s %s" % (t, len(c), d,
                  "≈底数⇒没进核心" if 0 <= d <= 350 else ("长度不同" if d == -1 else "≫底数⇒真进了")))
        else:
            print("  %-12s 无底层状态可比" % t)
    quite = [t for t, v in res.items() if v.get("started") and not v["fw_dialogs"]]
    print("\n--- 判定")
    print("  真跑起来的臂:", [t for t, v in res.items() if v.get("started")] or "无")
    print("  无固件框的臂:", quite or "全部有框")
    print("  ab11 路径抑制复现:", "x2_ab11_CX4" in quite, " ab16 路径抑制复现:",
          "x3_ab16_CX4" in quite)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    print("\nwrote", OUT, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
