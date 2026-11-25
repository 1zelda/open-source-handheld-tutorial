# -*- coding: utf-8 -*-
"""ab16：注册门到底认**文件名**还是认**内容**——ab11 与 ab12/ab15 结果不一致的唯一差别就是文件名。

为什么要单独问这个（前情，全部实测）：
  * ab11：`FirmwareUserSpecifications[CX4]` 指向 `Firmware/cx4.rom`（32KB 0xCD）⇒
          「Couldn't find firmware SNES+CX4」警告框**消失**（bisect 只有裸名 `CX4`/`SNES+CX4` 两个键吃）。
  * ab12：同一键，但指向 `Firmware/cx4_spec_dummy.bin` ⇒ 警告框**仍在**（r1 disc=3 fw_dlg=1）。
  * ab15：同一键，指向 `Firmware/v1_32k_CD.bin`（32KB 0xCD，和 ab11 同长度同内容，只换了名字）⇒
          警告框**仍在**。
  ⇒ 三次唯一变过的就是**文件名**。要么门按名字认（BizHawk 只把注册路径当「已知固件文件的备选位置」），
    要么 ab11 那次是假象。这决定 D1 的整片 A/B 怎么做：处理臂必须用 `cx4.rom` 这个名字。

字面量取证（本轮在沙盒二进制里 utf-16 搜到的，别再凭印象）：
  * `BizHawk.Client.Common.dll`  → "Couldn't find firmware {0}.  Will attempt to continue: {1}"
                                    另有 "Couldn't find required firmware {0}.  This is fatal{1}"
  * `BizHawk.Emulation.Cores.dll`→ "Bad firmware length detected! Firmware might not work!"
                                    "Hacked firmware detected! Firmware might not work!"
                                    —— 这两句挨着 `ARM9`/`Wifi AP1..AP3`/`USER0`/`CRC16`/
                                       "Firmware could not be decryped for" ⇒ 是 **NDS 固件路**的文案，
                                       不是 BSNES/CX4 的。所以「r1 里没出现 Hacked」这句话没有信息量，
                                       ab15 前言里的这条依据作废（本文件顶部记了）。

六臂（每臂 60 帧，约 90 秒）：
  b0_none              什么都不注册，也不放文件        —— 同批基线（ab15 缺这条）
  b1_spec_CX4rom_inFW  注册 CX4 → Firmware/cx4.rom（32K 0xCD） —— 复现 ab11
  b2_spec_weird_inFW   注册 CX4 → Firmware/cx4_spec_dummy.bin（32K 0xCD） —— 复现 ab12/ab15
  b3_spec_CX4rom_out   注册 CX4 → <Firmware 之外>/cx4.rom（32K 0xCD） —— 名字对、位置不对
  b4_spec_CX4rom_16K   注册 CX4 → Firmware/cx4.rom（16K 0xCD）      —— 名字对、长度不对
  b5_file_only_nospec  Firmware/cx4.rom（32K 0xCD）但**不**注册      —— 复现 ab11 arm2/3

判读（写进结果，不靠嘴）：
  * b1 无警告、b2 有警告 ⇒ 门按**文件名**认；整片处理臂必须用 `cx4.rom` 这个名字，
    ab12 的「画面/状态分不出来」是没喂进字节的假结论（已作废，等真内容再测）。
  * b1 与 b3 都无警告 ⇒ 只认名字、不看位置；b3 有警告 ⇒ 名字+目录都要对上。
  * b1 无警告但 b1 与 b0 的状态/画面仍分不出来 ⇒ 门只是压框不喂字节（乙），
    这时才第一次能量出「压框」与「喂字节」是两件事——因为 b4 长度不对若也被压框，
    说明它连长度都没看过。
串行：EmuHawk 一次一个；跑前确认没有 EmuHawk，跑完把 config 还原、假文件删掉。
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
from taspipe import registry as REG     # noqa: E402
import tas_replay                       # noqa: E402
import state_decode as SD               # noqa: E402
import ab12_full as AB                  # noqa: E402

SCR, BIZ, CFG = AB.SCR, AB.BIZ, AB.CFG
FW_DIR = os.path.join(BIZ, "Firmware")
OUT_DIR = os.path.join(SCR, "ab16_files")          # Firmware 之外的那个位置
FRAMES = 60
SPEC_PAT = re.compile(r'"FirmwareUserSpecifications"\s*:\s*\{[^{}]*\}')
FW_WARN_RE = re.compile(r"Couldn'?t find (?:required )?firmware", re.I)
# 臂卫生基线从生产件现查，不写死常量
HDR = REG.read_bk2_header(AB.MOVIE)
ROM_SHA1_EXPECT = (HDR.get("SHA1") or "").upper()

# (tag, 注册键 or None, 目标绝对路径 or None, 长度, 填充)
ARMS = [
    ("b0_none", None, None, None, None),
    ("b1_spec_CX4rom_inFW", "CX4", os.path.join(FW_DIR, "cx4.rom"), 32768, 0xCD),
    ("b2_spec_weird_inFW", "CX4", os.path.join(FW_DIR, "cx4_spec_dummy.bin"), 32768, 0xCD),
    ("b3_spec_CX4rom_out", "CX4", os.path.join(OUT_DIR, "cx4.rom"), 32768, 0xCD),
    ("b4_spec_CX4rom_16K", "CX4", os.path.join(FW_DIR, "cx4.rom"), 16384, 0xCD),
    ("b5_file_only_nospec", None, os.path.join(FW_DIR, "cx4.rom"), 32768, 0xCD),
]

LUA = '''
local dir = "%s/"
local hb = io.open(dir .. "heartbeat.txt", "w")
for i = 1, %d do emu.frameadvance() end
hb:write(string.format("%%08d %%-10s\\n", emu.framecount(), tostring(movie.mode()))); hb:flush()
savestate.save(dir .. "s60.m11")
hb:write("saved\\n"); hb:close()
client.exit()
'''


def spec_blob(base, key, path):
    """只动 FirmwareUserSpecifications 这一个对象；key=None 就写**合法的空对象 {}**。

    11-23 ab16 第一次跑踩到的坑（已落成脚本内闸门）：初版把 key=None 写成
    `"FirmwareUserSpecifications": `（冒号后面空），config 当场不是合法 JSON，
    BSNES 加载 ROM 时抛 `System.NullReferenceException @ BizHawk.Client.Common.FirmwareManager.Do…`，
    弹的是「A core accepted the rom, but threw an exception while loading it」而不是固件提示，
    而我的过滤器按子串 `irmware` 命中了类名 **FirmwareManager**，把这条**异常**数成了「固件警告框 1 个」。
    两处一起修：空值写 `{}`，写盘前先 json 复算，警告框只认 Client.Common 那句正文。
    """
    if not SPEC_PAT.search(base):
        raise RuntimeError("config.ini 里没有 FirmwareUserSpecifications 字段，本探针前提不成立")
    body = "{}" if key is None else '{ "%s": "%s" }' % (key, path.replace("\\", "/"))
    blob = SPEC_PAT.sub('"FirmwareUserSpecifications": %s' % body, base, count=1)
    want = {} if key is None else {key: path.replace("\\", "/")}
    try:
        got = json.loads(blob).get("FirmwareUserSpecifications")
    except Exception as e:
        raise RuntimeError("写出来的 config 不是合法 JSON（%s），本臂前提不成立" % type(e).__name__)
    if got != want:
        raise RuntimeError("config 注册块回读=%r，期望=%r，臂不成立" % (got, want))
    return blob


def clean_fw():
    for f in os.listdir(FW_DIR):
        p = os.path.join(FW_DIR, f)
        if os.path.isfile(p):
            os.remove(p)


def run(tag, key, path, size, fill):
    clean_fw()
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    base = open(CFG, encoding="utf-8", errors="replace").read()
    with open(CFG, "w", encoding="utf-8") as fh:
        fh.write(spec_blob(base, key, path))
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(bytes([fill]) * size)
    w = os.path.join(SCR, tag)
    if os.path.isdir(w):
        shutil.rmtree(w)
    os.makedirs(w)
    try:
        m, r = os.path.join(w, "movie.bk2"), os.path.join(w, "rom.sfc")
        tas_replay.materialize_movie(AB.MOVIE, m)
        tas_replay.materialize_rom(AB.ROM, r)
        rec_rom = hashlib.sha1(open(r, "rb").read()).hexdigest().upper()
        if rec_rom != ROM_SHA1_EXPECT:
            raise RuntimeError("沙盒 rom.sfc 哈希(%s)对不上 bk2 Header SHA1(%s)，臂不成立"
                               % (rec_rom, ROM_SHA1_EXPECT))
        rec_movie = hashlib.sha256(open(m, "rb").read()).hexdigest()
        lua = os.path.join(w, "cap.lua")
        with open(lua, "w", encoding="utf-8") as fh:
            fh.write(LUA % (w.replace("\\", "/"), FRAMES))
        fw_files = sorted(os.listdir(FW_DIR))
        t0 = time.time()
        with open(os.path.join(w, "emulator.log"), "wb") as lf:
            proc = subprocess.Popen([os.path.join(BIZ, "EmuHawk.exe"), "--chromeless",
                                     "--movie=" + m, "--lua=" + lua, r],
                                    cwd=BIZ, stdout=lf, stderr=subprocess.STDOUT)
            wd = WD.watch_process(proc, w, hard_timeout=900)
    finally:
        with open(CFG, "w", encoding="utf-8") as fh:
            fh.write(base)
        clean_fw()
        if os.path.isdir(OUT_DIR):
            shutil.rmtree(OUT_DIR)
    logp = os.path.join(w, "emulator.log")
    logs = WD.firmware_console_lines(logp)
    raw = open(logp, encoding="utf-8", errors="replace").read()
    fw_lines = [l.strip() for l in raw.splitlines() if "irmware" in l]
    dialogs = [t for d in wd["dismissed_dialogs"] for t in d["texts"]]
    # 只认 Client.Common 那句正文（dll 里是 "Couldn't find firmware {0}. Will attempt to
    # continue: {1}"，fatal 版是 "Couldn't find required firmware {0}. This is fatal{1}"）；
    # 按子串 firmware 过滤会把 FirmwareManager 的堆栈当成固件提示。
    fw_warn = [t for t in dialogs if FW_WARN_RE.search(t)]
    core_exc = [t for t in dialogs if "threw an exception" in t.lower()]
    rec = {"tag": tag, "spec_key": key, "spec_path": path, "size": size,
           "fill": None if fill is None else hex(fill),
           "termination": wd["termination"], "dismissed": wd["dismissed"],
           "wall": round(time.time() - t0, 1),
           "rom_sha1": rec_rom, "movie_sha256": rec_movie,
           "spec_basename": (os.path.basename(path) if path else None),
           "fw_dir_at_launch": fw_files,
           "in_fw_dir": bool(path) and os.path.dirname(path) == FW_DIR,
           "core_exception": core_exc,
           "fw_console": logs, "fw_log_lines": fw_lines,
           "config_spec_after": SPEC_PAT.search(
               open(CFG, encoding="utf-8", errors="replace").read()).group()[:200]}
    if core_exc:
        raise RuntimeError("核心加载 ROM 抛异常（config 被写坏或固件表对不上），本臂作废：%s"
                           % core_exc[0][:200])
    rec.update(dialogs=dialogs, fw_dialogs=fw_warn)
    sp = os.path.join(w, "s60.m11")
    hb = os.path.join(w, "heartbeat.txt")
    rec["heartbeat"] = open(hb, encoding="utf-8", errors="replace").read().strip() if os.path.exists(hb) else "无"
    if os.path.exists(sp):
        parts = SD.parts(sp)
        core, fb = parts["Core.bin"], parts["Framebuffer.bmp"]
        rec.update(core_len=len(core), core_sha1=hashlib.sha1(core).hexdigest(),
                   fb_len=len(fb), fb_sha1=hashlib.sha1(fb).hexdigest(),
                   CD_run=core.count(bytes([0xCD]) * 4096),
                   state_bytes=os.path.getsize(sp))
    else:
        rec["core_sha1"] = "无状态"
    return rec


def main():
    if AB.emuhawk_running():
        print("!! EmuHawk 正在跑，串行规矩，本批不启动"); return 3
    cur = SPEC_PAT.search(open(CFG, encoding="utf-8", errors="replace").read())
    print("起跑前 config 的注册块：%s" % (cur.group() if cur else "(找不到该字段)"), flush=True)
    if cur and "CX4" in cur.group().upper():
        print("!! config 里还留着上一批的 CX4 注册，先手工清干净再跑"); return 4
    print("臂卫生基线（生产件现查）：ROM SHA1=%s  电影=%s" % (ROM_SHA1_EXPECT, AB.MOVIE), flush=True)
    tas_replay.force_core(BIZ, "SNES", "BSNES")
    assert not os.path.exists(OUT_DIR), "上一批在 Firmware 外面留了文件，先确认再删"
    out = {}
    for tag, key, path, size, fill in ARMS:
        rec = run(tag, key, path, size, fill)
        out[tag] = rec
        print("\n=== %-20s 注册=%s 目标名=%s 在Firmware里=%s 长度=%s disc=%s term=%s %.1fs" %
              (tag, rec["spec_key"], rec["spec_basename"], rec["in_fw_dir"], rec["size"],
               rec["dismissed"], rec["termination"], rec["wall"]), flush=True)
        print("    Firmware 目录实况:", rec["fw_dir_at_launch"])
        print("    跑后注册块:", rec["config_spec_after"])
        for d in rec["dialogs"]:
            print("    DLG:", d[:160])
        for l in rec["fw_console"]:
            print("    FWC:", l[:160])
        print("    固件警告框数=%d  心跳=%r core_len=%s core_sha1=%s fb_sha1=%s CD连块=%s"
              % (len(rec["fw_dialogs"]), rec["heartbeat"], rec.get("core_len"),
                 str(rec.get("core_sha1"))[:12], str(rec.get("fb_sha1"))[:12],
                 rec.get("CD_run")), flush=True)
        with open(os.path.join(SCR, "ab16_partial.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    print("\n--- 逐格相同性")
    for k in ("dialogs", "fw_console"):
        uniq = sorted({json.dumps(v[k], ensure_ascii=False) for v in out.values()})
        print("  %-11s 不同取值 %d 种" % (k, len(uniq)))
    for k in ("fw_dialogs", "core_sha1", "fb_sha1", "core_len"):
        print("  %-11s %s" % (k, {t: (len(v[k]) if k == "fw_dialogs" else str(v.get(k))[:12])
                                  for t, v in out.items()}))
    print("\n--- 判定（压框的到底是哪一格）")
    for t, v in out.items():
        print("  %-21s 名=%-19s 在FW=%-5s 长度=%-6s 注册=%-5s 警告框=%d" %
              (t, v["spec_basename"], v["in_fw_dir"], v["size"], bool(v["spec_key"]),
               len(v["fw_dialogs"])))
    quite = [t for t, v in out.items() if not v["fw_dialogs"]]
    print("  无警告的臂：%s" % (quite or "全部都有警告"))
    if "b1_spec_CX4rom_inFW" in quite and "b2_spec_weird_inFW" not in quite:
        print("  ⇒ 门按**文件名**认：ab12/ab15 用 cx4_spec_dummy.bin 是没喂进字节的假处理臂，"
              "整片 A/B 必须改用 cx4.rom 这个名字重做")
    elif "b1_spec_CX4rom_inFW" in quite and "b2_spec_weird_inFW" in quite:
        print("  ⇒ 与 ab12/ab15 矛盾，ab11 那次另有变量（沙盒状态/时间），本批不能定论")
    elif not quite:
        print("  ⇒ 连 ab11 的正对照都复现不了，注册门在本沙盒里压不住框，"
              "ab12/ab15 的零差异同样是假结论（没有任何字节进核心）")
    print("  恒量反证：rom_sha1 取值 %d 种 %s / movie_sha256 取值 %d 种" %
          (len({v["rom_sha1"] for v in out.values()}),
           {v["rom_sha1"][:8] for v in out.values()},
           len({v["movie_sha256"] for v in out.values()})))
    with open(os.path.join(SCR, "ab16_name.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    print("\nwrote", os.path.join(SCR, "ab16_name.json"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
