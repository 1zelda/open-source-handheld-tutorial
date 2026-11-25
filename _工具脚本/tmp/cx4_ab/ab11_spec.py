# -*- coding:
"""CX4 固件识别机制探针（ab11）：BizHawk 认「文件名」还是认「内容/配置注册」？

背景：ab9 的 N 组把 4 种文件名（`cx4.rom` / `SNES_cx4.rom`（表里的名字）/ 两个都放 /
1K 错长度）丢进配置声明的固件目录 `./Firmware`，五臂的警告正文一字不差都是
`Couldn't find firmware SNES+CX4. Will attempt to continue`。单看这行不能断定是
「文件名全不对」还是「目录根本没被当回事」——所以本件测的是另一条码路上存在的路径
（Client.Common 里的 `GetFirmwareWithPath` / `_firmwareUserSpecifications`）：
把文件路径写进 config 的 `FirmwareUserSpecifications`，看警告会不会消失。

三种结果都算答案：
  * 警告消失           ⇒ 目录扫描按内容识别（假字节识别不了），而配置指定路径能直接把字节喂给核心
                        ⇒ 下一步用命中的那个键做 2000 帧像素 A/B，这才测得出「固件内容影响画面吗」。
  * 警告不消失（所有键）⇒ 这一路在 2.9.1 + BSNES 上不吃配置，D1「放文件」无论怎么放都拿不到保真度。
  * 崩/配置被回写        ⇒ 记录被回写成什么，本身就是证据。

EmuHawk 严格串行；一次一臂，跑前确认上一进程已退净（锁 rom 会 0 帧）。
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
from taspipe import registry as R        # noqa: E402
from taspipe import watchdog as WD      # noqa: E402
import tas_replay                       # noqa: E402

SCR = r"F:\taspipe_scratch\cx4_ab"
BIZ = os.path.join(SCR, "bizhawk")
CFG = os.path.join(BIZ, "config.ini")
MOVIE = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\movies\SNES\5628.bk2"
ROM = r"F:\BaiduNetdiskDownload\rom\snes\洛克人 X2.zip!洛克人 X2.sfc"
FILL = bytes([0xCD])
DUMMY = os.path.join(BIZ, "Firmware", "cx4.rom")

LUA = '''
local dir = "%s/"
local hb = io.open(dir .. "heartbeat.txt", "w")
for i = 1, %d do
    emu.frameadvance()
    hb:seek("set", 0)
    hb:write(string.format("%%08d %%-10s\\n", emu.framecount(), tostring(movie.mode())))
    hb:flush()
end
hb:close()
client.exit()
'''

# 候选键：表里的文件名、libsnes 请求名、裸芯片名、System+Name 三种拼法、System 空格 Name
KEYS = ["SNES_cx4.rom", "cx4.rom", "CX4", "SNES CX4", "SNES+CX4", "Super Famicom CX4",
        "SNES/CX4", "SNESFIRMWARE_CX4"]


def sha(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest().upper()


def read_cfg():
    return open(CFG, encoding="utf-8", errors="replace").read()


def set_spec(blob, spec):
    """只动 FirmwareUserSpecifications 这一个对象，别整本重写（配置里有核心选择等别的字段）。"""
    pat = re.compile(r'"FirmwareUserSpecifications"\s*:\s*\{[^{}]*\}')
    if not pat.search(blob):
        raise RuntimeError("config.ini 里找不到 FirmwareUserSpecifications 字段，本探针前提不成立")
    body = ", ".join('"%s": "%s"' % (k, v.replace("\\", "/")) for k, v in spec.items())
    return pat.sub('"FirmwareUserSpecifications": { %s }' % body, blob, count=1)


def emuhawk_running():
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                         errors="replace").stdout.lower()
    return "emuhawk" in out


def run_arm(tag, dummy_file, spec):
    fw = os.path.join(BIZ, "Firmware")
    for f in os.listdir(fw):
        os.remove(os.path.join(fw, f))
    if dummy_file:
        with open(DUMMY, "wb") as fh:
            fh.write(FILL * 32768)
    base = read_cfg()
    with open(CFG, "w", encoding="utf-8") as fh:
        fh.write(set_spec(base, spec) if spec else base)
    w = os.path.join(SCR, tag)
    if os.path.isdir(w):
        shutil.rmtree(w)
    os.makedirs(w)
    m, r = os.path.join(w, "movie.bk2"), os.path.join(w, "rom.sfc")
    tas_replay.materialize_movie(MOVIE, m)
    tas_replay.materialize_rom(ROM, r)
    lua = os.path.join(w, "cap.lua")
    with open(lua, "w", encoding="utf-8") as fh:
        fh.write(LUA % (w.replace("\\", "/"), 60))
    t0 = time.time()
    try:
        with open(os.path.join(w, "emulator.log"), "wb") as lf:
            proc = subprocess.Popen([os.path.join(BIZ, "EmuHawk.exe"), "--chromeless",
                                     "--movie=" + m, "--lua=" + lua, r],
                                    cwd=BIZ, stdout=lf, stderr=subprocess.STDOUT)
            wd = WD.watch_process(proc, w, hard_timeout=900)
    finally:
        with open(CFG, "w", encoding="utf-8") as fh:
            fh.write(base)                       # 无论跑成啥样都把配置还原
    fwv, fwwhy, fwspecs = WD.firmware_verdict(wd)
    logs = WD.firmware_console_lines(os.path.join(w, "emulator.log"))
    fw_hits = [t for rec in wd["dismissed_dialogs"] for t in rec["texts"]
               if "firmware" in t.lower()]
    return {"tag": tag, "dummy": bool(dummy_file), "spec_keys": sorted(spec),
            "termination": wd["termination"], "dismissed": wd["dismissed"],
            "stalls": wd["stalls"], "elapsed": wd["elapsed"],
            "heartbeat": open(os.path.join(w, "heartbeat.txt"), errors="replace").read().strip()
            if os.path.exists(os.path.join(w, "heartbeat.txt")) else "",
            "firmware_dialog_count": len(fw_hits), "firmware_dialogs": fw_hits,
            "all_dialogs": [rec["texts"] for rec in wd["dismissed_dialogs"]],
            "console_firmware_lines": logs,
            "gate": [fwv, fwwhy, fwspecs],
            "cfg_after_spec": read_cfg()[
                read_cfg().find('"FirmwareUserSpecifications"'):
                read_cfg().find('"FirmwareUserSpecifications"') + 400],
            "cfg_restored_ok": read_cfg() == base}


def main():
    if emuhawk_running():
        print("!! 有 EmuHawk 在跑，串行规矩，本批不启动"); return 3
    tas_replay.force_core(BIZ, "SNES", "BSNES")
    res = {}
    arms = [("k0_none", False, {}),
            ("k1_spec_all", True, {k: DUMMY for k in KEYS})]
    for tag, dm, sp in arms:
        rec = run_arm(tag, dm, sp)
        res[tag] = rec
        print("\n=== %-13s dummy=%-5s spec=%d term=%s disc=%s fw_dlg=%s %.1fs hb=%s" % (
            tag, dm, len(sp), rec["termination"], rec["dismissed"],
            rec["firmware_dialog_count"], rec["elapsed"], rec["heartbeat"]), flush=True)
        for t in rec["firmware_dialogs"]:
            print("    FWDLG:", t[:170])
        for l in rec["console_firmware_lines"][:4]:
            print("    LOG:", l[:150])
        for a in rec["all_dialogs"]:
            print("    DLG:", " | ".join(x[:120] for x in a))
        print("    GATE:", rec["gate"][0], rec["gate"][2])
        print("    CFG :", rec["cfg_after_spec"][:260].replace("\n", " "))
        if rec["termination"] != "exited" or not rec["heartbeat"].startswith(
                tuple("0123456789")):
            print("\n!! %s 没跑起来（term=%s hb=%r），停批" % (tag, rec["termination"],
                                                            rec["heartbeat"][:20]))
            break
    hit = [t for t, r in res.items() if r["firmware_dialog_count"] == 0 and t != "k0_none"]
    print("\n抑制固件警告的臂=", hit or "无（所有候选键都没能吃掉警告）")
    if hit:                                   # 二分开：一臂一键，找出真正生效的键名
        solo = []
        for k in KEYS:
            rec = run_arm("key_" + re.sub(r"\W", "_", k), True, {k: DUMMY})
            solo.append((k, rec["firmware_dialog_count"], rec["termination"],
                         rec["console_firmware_lines"][:1]))
            print("  key %-22s fw_dlg=%s term=%s log=%s" % solo[-1], flush=True)
        res["bisect"] = solo
    with open(os.path.join(SCR, "ab11_spec.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("wrote", os.path.join(SCR, "ab11_spec.json"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
