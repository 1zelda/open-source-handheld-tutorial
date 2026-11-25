# -*- coding: utf-8 -*-
"""CX4 固件 A/B 合并跑（反证格 + 文件名归属 + 内容是否参与运算），严格串行。

为什么重跑一遍（ab6 跑到一半被我自己判废）：探针把看门狗 `stall_timeout` 覆盖成 180s，
而缺固件必然弹原生 Warning 框 ⇒ 每一臂光等框就 3–9 分钟，n1 已经 8 分钟没动。
生产路径默认 30s 且靠 heartbeat.txt 判活，所以本件全部改回生产默认 + 像 cap.lua 那样写心跳。

三组问题，一次答完：
  C 组 恒量反证格：同进程同帧存两次 + 两次换新进程、配置完全相同 ⇒ 量出「状态字节」这把尺子
     的跨进程噪声底数（ab5 的 88,484 和 ab6 n0_none 的 88,496 是同配置不同进程，差 12 字节，
     不先量底数就没法把 ab6/ab7 的差异归因给固件）。
  N 组 文件名归属：空 / `cx4.rom` / `SNES_cx4.rom`（BizHawk 表里的名字）/ 两个都放 / 1K 短文件，
     各存 60 帧状态，与空臂比差异字节数。
  L 组 内容有没有真参与运算：空 vs 32KB 假固件，跑到 30,000 帧，在 60/10000/20000/30000 各存一次。
     差异字节数一直贴着噪声底数 ⇒ 芯片只是被装载没执行；随帧数变大 ⇒ CX4 确实在算，
     本机「没固件」的产物和作者环境不等价（这才是 D1 要不要放文件的实锤）。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import registry as R        # noqa: E402
from taspipe import watchdog as WD      # noqa: E402
import tas_replay                       # noqa: E402

SCR = r"F:\taspipe_scratch\cx4_ab"
BIZ = os.path.join(SCR, "bizhawk")
MOVIE = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\movies\SNES\5628.bk2"
ROM = r"F:\BaiduNetdiskDownload\rom\snes\洛克人 X2.zip!洛克人 X2.sfc"
FILL = bytes([0xCD])

LUA = '''
local dir = "%s/"
local hb = io.open(dir .. "heartbeat.txt", "w")
local out = io.open(dir .. "marks.txt", "w")
assert(hb, "heartbeat.txt 打不开：工作目录必须全 ASCII")
local marks = {%s}
local names = %s
for i = 1, %d do
    emu.frameadvance()
    local fc = emu.framecount()
    hb:seek("set", 0)
    hb:write(string.format("%%08d %%-10s\\n", fc, tostring(movie.mode())))
    hb:flush()
    for _, m in ipairs(marks) do
        if fc == m then
            for _, nm in ipairs(names[m]) do
                savestate.save(dir .. nm .. ".m11")
                out:write("saved " .. nm .. " at " .. tostring(fc) .. "\\n"); out:flush()
            end
        end
    end
end
out:write("end n=" .. tostring(emu.framecount()) .. " mode=" .. tostring(movie.mode()) .. "\\n")
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


def run_arm(tag, files, frames, marks, double_at=None):
    """files: [(名字, 长度)]；marks: 存状态的帧号；double_at: 在该帧同进程连存两份。"""
    fw = os.path.join(BIZ, "Firmware")
    for f in os.listdir(fw):
        os.remove(os.path.join(fw, f))
    placed = []
    for name, size in files:
        fp = os.path.join(fw, name)
        with open(fp, "wb") as fh:
            fh.write(FILL * size)
        placed.append({"name": name, "size": size, "sha1": sha(fp)})
    w = os.path.join(SCR, tag)
    if os.path.isdir(w):
        shutil.rmtree(w)
    os.makedirs(w)
    m, r = os.path.join(w, "movie.bk2"), os.path.join(w, "rom.sfc")
    tas_replay.materialize_movie(MOVIE, m)
    tas_replay.materialize_rom(ROM, r)
    names = {}
    for mk in marks:
        names[mk] = ["s%d_a" % mk, "s%d_b" % mk] if mk == double_at else ["s%d" % mk]
    lua = os.path.join(w, "cap.lua")
    # Lua 表字面量的整数键只能写 [k]=（c1 那臂写成 k:{...} 被 NLua 判
    # "'}' expected near ':'"，模拟器活着但一帧没跑）。
    names_lit = "{" + ",".join("[%d]={%s}" % (k, ",".join('"%s"' % n for n in v))
                              for k, v in names.items()) + "}"
    with open(lua, "w", encoding="utf-8") as fh:
        fh.write(LUA % (w.replace("\\", "/"), ",".join(str(x) for x in marks),
                        names_lit, frames))
    log = os.path.join(w, "emulator.log")
    t0 = time.time()
    with open(log, "wb") as lf:
        proc = subprocess.Popen(
            [os.path.join(BIZ, "EmuHawk.exe"), "--chromeless",
             "--movie=" + m, "--lua=" + lua, r],
            cwd=BIZ, stdout=lf, stderr=subprocess.STDOUT)
        wd = WD.watch_process(proc, w, hard_timeout=3600 if frames > 1000 else None)
    st = {f[:-4]: {"bytes": os.path.getsize(os.path.join(w, f)), "sha1": sha(os.path.join(w, f))}
          for f in sorted(os.listdir(w)) if f.endswith(".m11")}
    rec = {"placed": placed, "frames": frames, "termination": wd["termination"],
           "dismissed": wd["dismissed"], "stalls": wd["stalls"],
           "dialogs": [d.get("texts") for d in wd["dismissed_dialogs"]],
           "wall_s": round(time.time() - t0, 1),
           "heartbeat": open(os.path.join(w, "heartbeat.txt")).read().strip()
                        if os.path.isfile(os.path.join(w, "heartbeat.txt")) else "(none)",
           "marks": open(os.path.join(w, "marks.txt")).read().strip().splitlines()
                    if os.path.isfile(os.path.join(w, "marks.txt")) else [],
           "states": st, "fw_lines": WD.firmware_console_lines(log),
           "gate": WD.firmware_verdict(dict(wd, console_texts=WD.firmware_console_lines(log)))}
    rec["_dir"] = w
    print("\n=== %-14s placed=%-28s term=%s disc=%s stalls=%s %.1fs hb=%s" % (
        tag, str([p["name"] for p in placed]), wd["termination"], wd["dismissed"],
        wd["stalls"], rec["wall_s"], rec["heartbeat"]), flush=True)
    print("    states=%s" % {k: v["bytes"] for k, v in st.items()}, flush=True)
    for d in rec["dialogs"]:
        print("    DLG:", str(d)[:190], flush=True)
    for ln in rec["fw_lines"]:
        print("    LOG:", ln[:170], flush=True)
    print("    GATE:", rec["gate"][0], rec["gate"][2], flush=True)
    if not rec["heartbeat"].startswith(tuple("0123456789")):
        # 心跳一个字节都没写 => Lua 压根没执行，后面每一臂都会同样白跑，停在这里。
        rec["_never_started"] = True
        print("    !! 心跳文件缺失/非数字：Lua 没跑起来，看 %s 里的 LuaScriptException"
              % log, flush=True)
    return rec


def main():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EmuHawk.exe"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace").stdout
    if "EmuHawk.exe" in out:
        print("!! EmuHawk 正在跑，本脚本不启动（严格串行）"); return 3
    hdr = R.read_bk2_header(MOVIE)
    print("电影 Header:", {k: hdr.get(k) for k in ("SystemID", "Core", "emuVersion",
          "rerecordCount", "length", "SnesMemoryType") if k in hdr}, flush=True)
    tas_replay.force_core(BIZ, "SNES", "BSNES")
    res = {"header_subset": {k: v for k, v in hdr.items()
                             if k in ("SystemID", "Core", "emuVersion", "rerecordCount",
                                      "SnesMemoryType") or "Firmware" in k}}

    # ---------- C 组：尺子本身的噪声底数 ----------
    c1 = run_arm("c1_same_proc", [], 60, [60], double_at=60)
    if c1.get("_never_started"):
        print("\n!! c1 一帧没跑（Lua 未执行），整批停跑，别把 10 臂都白烧"); return 4
    c2 = run_arm("c2_new_proc", [], 60, [60])
    c3 = run_arm("c3_new_proc2", [], 60, [60])
    same = difftable(os.path.join(c1["_dir"], "s60_a.m11"), os.path.join(c1["_dir"], "s60_b.m11"))
    xp = {"c1_c2": difftable(os.path.join(c1["_dir"], "s60_a.m11"), os.path.join(c2["_dir"], "s60.m11")),
          "c2_c3": difftable(os.path.join(c2["_dir"], "s60.m11"), os.path.join(c3["_dir"], "s60.m11")),
          "c1_c3": difftable(os.path.join(c1["_dir"], "s60_a.m11"), os.path.join(c3["_dir"], "s60.m11"))}
    floor = max(v["n_diff"] for v in xp.values())
    res["control"] = {"same_proc_same_frame": same, "cross_proc": xp,
                      "cross_process_noise_floor": floor}
    print("\n  同进程同帧差异=%d  跨进程差异=%s  底数=%d" % (
        same["n_diff"], {k: v["n_diff"] for k, v in xp.items()}, floor), flush=True)

    # ---------- N 组：哪个文件名算数 ----------
    n_arms = [("n0_none", []), ("n1_bare_cx4rom", [("cx4.rom", 32768)]),
              ("n2_db_name", [("SNES_cx4.rom", 32768)]),
              ("n3_both", [("cx4.rom", 32768), ("SNES_cx4.rom", 32768)]),
              ("n4_wrong_len", [("cx4.rom", 1024)])]
    recs = {t: run_arm(t, f, 60, [60]) for t, f in n_arms}
    basep = os.path.join(recs["n0_none"]["_dir"], "s60.m11")
    res["names"] = {}
    for t, f in n_arms:
        p = os.path.join(recs[t]["_dir"], "s60.m11")
        d = difftable(basep, p) if t != "n0_none" and os.path.isfile(p) else None
        res["names"][t] = {"placed": f, "state_bytes": recs[t]["states"].get("s60", {}),
                           "diff_vs_none": d, "gate": recs[t]["gate"],
                           "dialogs": recs[t]["dialogs"], "fw_lines": recs[t]["fw_lines"]}
        print("  %-16s 与空臂差异字节=%-6s（底数 %d）" % (
            t, d and d["n_diff"], floor), flush=True)

    # ---------- L 组：内容参不参与运算（30,000 帧） ----------
    marks = [60, 10000, 20000, 30000]
    L1 = run_arm("L1_none", [], 30000, marks)
    L2 = run_arm("L2_dummy32k", [("cx4.rom", 32768)], 30000, marks)
    by_mark = {}
    for mk in marks:
        pa = os.path.join(L1["_dir"], "s%d.m11" % mk)
        pb = os.path.join(L2["_dir"], "s%d.m11" % mk)
        d = difftable(pa, pb) if os.path.isfile(pa) and os.path.isfile(pb) else None
        by_mark["s%d" % mk] = d
        print("  mark %-7s 空=%s 假固件=%s 差异字节=%-8s（底数 %d）" % (
            mk, L1["states"].get("s%d" % mk, {}).get("sha1", "")[:10],
            L2["states"].get("s%d" % mk, {}).get("sha1", "")[:10],
            d and d["n_diff"], floor), flush=True)
    res["growth"] = {"none": {k: v for k, v in L1.items() if k != "_dir"},
                     "dummy": {k: v for k, v in L2.items() if k != "_dir"},
                     "diff_by_mark": by_mark, "noise_floor": floor}

    with open(os.path.join(SCR, "ab9_all.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print("\nwrote", os.path.join(SCR, "ab9_all.json"), flush=True)
    return 0


sys.exit(main())
