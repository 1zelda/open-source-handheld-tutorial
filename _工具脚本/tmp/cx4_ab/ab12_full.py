# -*- coding: utf-8 -*-
"""ab12：让 BizHawk 真把固件字节喂进核心，再问「内容换没换画面/状态」。

前情（ab9 N 组 + ab11）：
  * 往配置声明的固件目录 `./Firmware` 扔文件，4 种文件名（`cx4.rom` / `SNES_cx4.rom`
    / 两个都放 / 1K 错长度）警告正文一字不差 ⇒ 目录扫描按内容识别（Client.Common 里
    `_firmwareSizes` / `KnownFirmwareFile` / `get_FirmwareHash`），假字节识别不了，压根没读。
  * 把路径写进 config 的 `FirmwareUserSpecifications`，警告框消失；bisect 出生效的键是
    裸芯片名 **`CX4`**（`SNES_cx4.rom`、`cx4.rom` 两个键都不吃）⇒ 这条路由字节真进了核心。
  * ab9 的 L 组「30,000 帧差异 109,853 字节」是 zstd 容器噪声：Core.bin / Framebuffer.bmp
    成员本身还是 zstd 帧，解到底层之后同配置跨进程底数只有 234–297 字节（state_decode.py）。

本件因此第一次能回答 D1 真正的问题：CX4 固件的内容会不会改变复刻结果。
两臂跑整片 111,727 帧（电影总帧由 bk2 内层 Input Log 行数实测），每 10,000 帧存一次状态；
状态里的 Framebuffer.bmp 就是那一帧的真实画面，比逐帧截图便宜得多（138 fps vs 50 fps）。

判读（都写在结果里）：
  * 某标记帧缓冲不同         ⇒ 固件内容会改画面 ⇒ 现在这批 CX4 片（5628/6891/3241/3247/3250）
                             的「没固件」产物与作者环境不等价，D1 要立刻办。
  * 全片帧缓冲都相同         ⇒ 至少这 32KB 假字节不改画面；再配 Core.bin 差异量判断字节
                             有没有真进状态（≈底数=没进，≫底数=进了但没执行/没被使能）。
  * 处理臂警告没消失         ⇒ 前提不成立，本臂等于白跑，直接停批（不许静默降级成 none-vs-none）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from taspipe import watchdog as WD      # noqa: E402
import tas_replay                       # noqa: E402
import state_decode as SD               # noqa: E402

SCR = r"F:\taspipe_scratch\cx4_ab"
BIZ = os.path.join(SCR, "bizhawk")
CFG = os.path.join(BIZ, "config.ini")
MOVIE = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\movies\SNES\5628.bk2"
ROM = r"F:\BaiduNetdiskDownload\rom\snes\洛克人 X2.zip!洛克人 X2.sfc"
DUMMY = os.path.join(BIZ, "Firmware", "cx4_spec_dummy.bin")
KEY = "CX4"                              # ab11 bisect 实测唯一生效的键名
FRAMES = 111700                          # 电影 111,727 帧，留 27 帧余量别撞「电影结束」框
MARKS = list(range(10000, FRAMES, 10000)) + [FRAMES - 100]

LUA = '''
local dir = "%s/"
local hb = io.open(dir .. "heartbeat.txt", "w")
local out = io.open(dir .. "marks.txt", "w")
assert(hb, "heartbeat.txt 打不开：工作目录必须全 ASCII")
local marks = {%s}
for i = 1, %d do
    emu.frameadvance()
    local fc = emu.framecount()
    hb:seek("set", 0)
    hb:write(string.format("%%08d %%-10s\\n", fc, tostring(movie.mode())))
    hb:flush()
    for _, m in ipairs(marks) do
        if fc == m then
            savestate.save(dir .. "s" .. m .. ".m11")
            out:write("saved " .. m .. " at " .. tostring(fc) .. "\\n"); out:flush()
        end
    end
end
out:write("end n=" .. tostring(emu.framecount()) .. " mode=" .. tostring(movie.mode()) .. "\\n")
out:close(); hb:close()
client.exit()
'''


def emuhawk_running():
    o = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                       text=True, errors="replace").stdout.lower()
    return "emuhawk" in o


def run_arm(tag, spec):
    """spec=None 什么都不动；spec=路径 则注册 FirmwareUserSpecifications[CX4] 并放假固件。"""
    fw = os.path.join(BIZ, "Firmware")
    for f in os.listdir(fw):
        os.remove(os.path.join(fw, f))
    base = open(CFG, encoding="utf-8", errors="replace").read()
    if spec:
        with open(DUMMY, "wb") as fh:
            fh.write(bytes([0xCD]) * 32768)
        pat = re.compile(r'"FirmwareUserSpecifications"\s*:\s*\{[^{}]*\}')
        if not pat.search(base):
            raise RuntimeError("config.ini 没有 FirmwareUserSpecifications 字段，前提不成立")
        blob = pat.sub('"FirmwareUserSpecifications": { "%s": "%s" }'
                       % (KEY, spec.replace("\\", "/")), base, count=1)
    else:
        blob = base
    with open(CFG, "w", encoding="utf-8") as fh:
        fh.write(blob)
    w = os.path.join(SCR, tag)
    if os.path.isdir(w):
        shutil.rmtree(w)
    os.makedirs(w)
    m, r = os.path.join(w, "movie.bk2"), os.path.join(w, "rom.sfc")
    tas_replay.materialize_movie(MOVIE, m)
    tas_replay.materialize_rom(ROM, r)
    lua = os.path.join(w, "cap.lua")
    with open(lua, "w", encoding="utf-8") as fh:
        fh.write(LUA % (w.replace("\\", "/"), ",".join(str(x) for x in MARKS), FRAMES))
    t0 = time.time()
    try:
        with open(os.path.join(w, "emulator.log"), "wb") as lf:
            proc = subprocess.Popen([os.path.join(BIZ, "EmuHawk.exe"), "--chromeless",
                                     "--movie=" + m, "--lua=" + lua, r],
                                    cwd=BIZ, stdout=lf, stderr=subprocess.STDOUT)
            wd = WD.watch_process(proc, w, hard_timeout=7200)
    finally:
        with open(CFG, "w", encoding="utf-8") as fh:
            fh.write(base)
        if os.path.exists(DUMMY):
            os.remove(DUMMY)
    logs = WD.firmware_console_lines(os.path.join(w, "emulator.log"))
    fwdlg = [t for rec in wd["dismissed_dialogs"] for t in rec["texts"]
             if "firmware" in t.lower()]
    verdict, why, specs = WD.firmware_verdict(dict(wd, console_texts=logs))
    hb = os.path.join(w, "heartbeat.txt")
    return {"tag": tag, "spec": bool(spec), "termination": wd["termination"],
            "dismissed": wd["dismissed"], "stalls": wd["stalls"],
            "elapsed": wd["elapsed"], "wall": round(time.time() - t0, 1),
            "heartbeat": open(hb, errors="replace").read().strip()
            if os.path.exists(hb) else "",
            "firmware_dialogs": fwdlg, "console_firmware_lines": logs,
            "gate_with_console": [verdict, why, specs],
            "states": sorted([f for f in os.listdir(w) if f.endswith(".m11")])}


def compare(A, B, label_a, label_b):
    """逐标记比：帧缓冲（真画面）是否相同 + Core.bin 解到底层的差异字节。"""
    rows = []
    for mk in MARKS:
        ka, kb = (A, "s%d" % mk), (B, "s%d" % mk)
        if ka not in F or kb not in F:
            rows.append((mk, "缺状态", None, None))
            continue
        fa, fb = F[ka]["Framebuffer.bmp"], F[kb]["Framebuffer.bmp"]
        d = SD.bytediff(F[ka]["Core.bin"], F[kb]["Core.bin"])
        rows.append((mk, "同" if fa == fb else "不同", d["diff"], d["runs"]))
    print("\n--- %s vs %s" % (label_a, label_b), flush=True)
    for mk, same, diff, runs in rows:
        print("   帧 %-7s 画面=%-4s 状态差异字节=%-7s 连续段=%s" % (mk, same, diff, runs))
    return [{"mark": mk, "picture": same, "core_diff_bytes": diff, "runs": runs}
            for mk, same, diff, runs in rows]


F = {}


def main():
    global F
    if emuhawk_running():
        print("!! EmuHawk 正在跑，串行规矩，本批不启动"); return 3
    tas_replay.force_core(BIZ, "SNES", "BSNES")
    res = {"frames": FRAMES, "marks": MARKS, "key": KEY}
    arms = {}
    for tag, spec in [("r0_none", None), ("r1_spec_dummy", DUMMY)]:
        rec = run_arm(tag, spec)
        arms[tag] = rec
        print("\n=== %-15s spec=%-5s term=%s disc=%s fw_dlg=%d %.1fs hb=%s 状态数=%d"
              % (tag, rec["spec"], rec["termination"], rec["dismissed"],
                 len(rec["firmware_dialogs"]), rec["wall"], rec["heartbeat"],
                 len(rec["states"])), flush=True)
        for t in rec["firmware_dialogs"]:
            print("    FWDLG:", t[:170])
        for l in rec["console_firmware_lines"][:3]:
            print("    LOG:", l[:150])
        print("    GATE(含 stdout 渠道):", rec["gate_with_console"])
        if rec["spec"] and rec["firmware_dialogs"]:
            print("\n!! 处理臂警告没消失，本臂没把字节喂进核心，停批"); return 4
        if not rec["heartbeat"].startswith(tuple("0123456789")):
            print("\n!! %s 一帧没跑，停批" % tag); return 5
    res["arms"] = arms
    print("\n解包 %d 个状态到最底层…" % sum(len(a["states"]) for a in arms.values()))
    for tag in arms:
        for f in arms[tag]["states"]:
            p = os.path.join(SCR, tag, f)
            F[(tag, os.path.splitext(f)[0])] = SD.parts(p)
    res["cmp_none_vs_dummy"] = compare("r0_none", "r1_spec_dummy", "什么都不放", "注册 32KB 假字节")
    with open(os.path.join(SCR, "ab12_full.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    print("\nwrote", os.path.join(SCR, "ab12_full.json"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
