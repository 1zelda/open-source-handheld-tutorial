# -*- coding: utf-8 -*-
"""ab15：`FirmwareUserSpecifications[CX4]` 这扇门到底读不读字节——用「长度不对」当探针。

为什么要单独问这个：ab12 的处理臂（注册 32KB 0xCD）跑完，画面与状态跟「什么都不放」**分不出来**，
而且 r1 的 emulator.log 里**只有** `Served libsnes request for firmware "cx4.rom"` 这一句，
既没有 `Hacked firmware detected!`（内容不在表里该有的提示），也没有 `Bad firmware length detected!`。
这句 "Served" 在什么都没放的 r0 里同样出现（ab9 n0 也一样）⇒ 它只证明核心问过一次，不证明回了什么。

于是 ab12 的零差异有两种解释，必须先分开再谈 D1：
  (甲) 字节真进了核心，只是这部电影这段不使能 CX4 ⇒ 尺子有效，零差异是实质结论。
  (乙) 键名把**警告框**压掉了，但 libsnes 那条取字节的路压根没理这个注册 ⇒ 尺子无效，
       零差异什么都不能说，只有拿到真固件（`188D471F…`）才测得动。

本件用 60 帧短臂（每臂约 90 秒）做四个注册变体，看 BizHawk 会不会**因为字节本身**说不同的话：
  v1 32,768B 0xCD   —— ab12 处理臂的短版，正对照（已知警告框会消失）
  v2 16,384B 0xCD   —— **长度不对**：若这扇门读文件，长度校验最该在这里露出来
  v3 32,768B 0xAB   —— 同长度换内容：若报 Hacked/内容可疑，说明内容真被看过
  v4 32,768B 0x00   —— 全零（等价于「没内容」），跟 v1 比就是最省事的灵敏度对照
每臂记：弹框正文、控制台固件相关行、firmware_verdict 三件套、帧 60 状态 Core.bin 底层 sha1 与长度。
判读：
  * 四臂证据一字不差 ⇒ 这扇门只压框不喂字节 ⇒ (乙) ⇒ ab12 零差异作废，D1 只能靠真固件回答。
  * v2 或 v3 冒出别的提示/警告框回来 ⇒ 门是活的 ⇒ (甲) ⇒ ab12 的零差异是实质结论：本片这段不吃 CX4 内容。
串行：EmuHawk 一次一个。
"""
import hashlib
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
import ab12_full as AB                  # noqa: E402

SCR, BIZ, CFG = AB.SCR, AB.BIZ, AB.CFG
FW_DIR = os.path.join(BIZ, "Firmware")
FRAMES = 60
VARIANTS = [("v1_32k_CD", 32768, 0xCD), ("v2_16k_CD", 16384, 0xCD),
            ("v3_32k_AB", 32768, 0xAB), ("v4_32k_00", 32768, 0x00)]

LUA = '''
local dir = "%s/"
local hb = io.open(dir .. "heartbeat.txt", "w")
for i = 1, %d do emu.frameadvance() end
hb:write(string.format("%%08d %%-10s\\n", emu.framecount(), tostring(movie.mode()))); hb:flush()
savestate.save(dir .. "s60.m11")
hb:write("saved\\n"); hb:close()
client.exit()
'''


def run(tag, size, fill):
    for f in os.listdir(FW_DIR):
        os.remove(os.path.join(FW_DIR, f))
    base = open(CFG, encoding="utf-8", errors="replace").read()
    pat = re.compile(r'"FirmwareUserSpecifications"\s*:\s*\{[^{}]*\}')
    blob = pat.sub('"FirmwareUserSpecifications": { "%s": "%s" }'
                   % (AB.KEY, (FW_DIR + "/" + tag + ".bin").replace("\\", "/")), base, count=1)
    with open(CFG, "w", encoding="utf-8") as fh:
        fh.write(blob)
    w = os.path.join(SCR, tag)
    if os.path.isdir(w):
        shutil.rmtree(w)
    os.makedirs(w)
    fw = os.path.join(FW_DIR, tag + ".bin")
    try:
        with open(fw, "wb") as fh:
            fh.write(bytes([fill]) * size)
        m, r = os.path.join(w, "movie.bk2"), os.path.join(w, "rom.sfc")
        tas_replay.materialize_movie(AB.MOVIE, m)
        tas_replay.materialize_rom(AB.ROM, r)
        lua = os.path.join(w, "cap.lua")
        with open(lua, "w", encoding="utf-8") as fh:
            fh.write(LUA % (w.replace("\\", "/"), FRAMES))
        t0 = time.time()
        with open(os.path.join(w, "emulator.log"), "wb") as lf:
            proc = subprocess.Popen([os.path.join(BIZ, "EmuHawk.exe"), "--chromeless",
                                     "--movie=" + m, "--lua=" + lua, r],
                                    cwd=BIZ, stdout=lf, stderr=subprocess.STDOUT)
            wd = WD.watch_process(proc, w, hard_timeout=900)
    finally:
        with open(CFG, "w", encoding="utf-8") as fh:
            fh.write(base)
        if os.path.exists(fw):
            os.remove(fw)
    logs = WD.firmware_console_lines(os.path.join(w, "emulator.log"))
    raw = open(os.path.join(w, "emulator.log"), encoding="utf-8", errors="replace").read()
    other = [l.strip() for l in raw.splitlines()
             if l.strip() and "irmware" not in l and not re.search(r"\.png saved\.$", l.strip())]
    rec = {"tag": tag, "size": size, "fill": hex(fill), "termination": wd["termination"],
           "dismissed": wd["dismissed"], "wall": round(time.time() - t0, 1),
           "dialogs": [t for r_ in wd["dismissed_dialogs"] for t in r_["texts"]],
           "fw_console": logs, "other_console": other[:12],
           "gate": WD.firmware_verdict(dict(wd, console_texts=logs))}
    sp = os.path.join(w, "s60.m11")
    if os.path.exists(sp):
        core = SD.parts(sp)["Core.bin"]
        rec["core_len"] = len(core)
        rec["core_sha1"] = hashlib.sha1(core).hexdigest()
        rec["core_CD_run32k"] = core.count(bytes([0xCD]) * 4096)
        rec["state_bytes"] = os.path.getsize(sp)
    else:
        rec["core_sha1"] = "无状态"
    return rec


def main():
    if AB.emuhawk_running():
        print("!! EmuHawk 正在跑，串行规矩，本批不启动"); return 3
    tas_replay.force_core(BIZ, "SNES", "BSNES")
    out = {}
    for tag, size, fill in VARIANTS:
        rec = run(tag, size, fill)
        out[tag] = rec
        print("\n=== %-10s %6dB fill=%s disc=%s term=%s %.1fs" %
              (tag, size, rec["fill"], rec["dismissed"], rec["termination"], rec["wall"]), flush=True)
        for d in rec["dialogs"]:
            print("    DLG:", d[:150])
        for l in rec["fw_console"]:
            print("    FWC:", l[:150])
        for l in rec["other_console"]:
            print("    OTH:", l[:150])
        print("    GATE:", rec["gate"][0], "|", rec["gate"][1][:120])
        print("    core_len=%s core_sha1=%s 32K-CD 连续块命中=%s"
              % (rec.get("core_len"), str(rec.get("core_sha1"))[:12], rec.get("core_CD_run32k")))
    print("\n--- 逐格相同性（只看会不会因为字节本身说不同的话）")
    keys = ("dialogs", "fw_console", "gate")
    for k in keys:
        vals = {t: json.dumps(out[t][k], ensure_ascii=False) for t in out}
        uniq = sorted(set(vals.values()))
        print("  %-11s 不同取值 %d 种" % (k, len(uniq)))
        if len(uniq) > 1:
            for t, v in vals.items():
                print("      %-10s %s" % (t, v[:200]))
    hs = {t: out[t].get("core_sha1") for t in out}
    print("  core_sha1   不同取值 %d 种：%s" % (len(set(hs.values())), hs))
    with open(os.path.join(SCR, "ab15_variants.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    print("\nwrote", os.path.join(SCR, "ab15_variants.json"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
