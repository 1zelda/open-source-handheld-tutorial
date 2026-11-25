# -*- coding: utf-8 -*-
"""ab14：换一块**内容不同的假固件**再跑一遍——问的是「这把尺子对固件内容敏不敏感」。

ab12 前两臂已经量到（本轮实测）：
  * r0_none vs r1_spec_dummy 在 10k/20k/30k/40k 四个标记：帧缓冲**逐字节相同**，
    Core.bin 底层差 285 字节 / 63 段；
  * 同配置跨进程噪声（r0_none vs ab9 的 l1_none，同一批标记）差 332 字节 / 64 段；
  * 两组差异偏移**交集 284**，r1 独有的只有 **1** 个偏移 ⇒ 处理效应淹没在噪声里，不是超出噪声。
  * 在 r1 的 Core.bin 里搜 32KB 的 0xCD 连续块：**找不到**（两臂 0xCD 单字节计数都是 666，纯 RAM 噪声）。

⇒「注册 0xCD 假固件」这件事在整片里没留下任何可测痕迹。但这里有个必须分开的问题：
  (甲) 这部电影根本没使能 CX4 ⇒ 喂什么字节都没用；
  (乙) 使能了、但 BizHawk 没把固件放进状态也没执行。
只靠 r0 vs r1 分不开这两条，因为**两块不同的垃圾也可能都让画面一样**。

本件补一臂 `r4_spec_ab`：同样的键 `CX4`、同样的 32,768 字节，但填 **0xAB**。三格对照：
  r0_none  vs r1_spec_dummy(0xCD)   —— ab12 已有
  r1_spec_dummy(0xCD) vs r4_spec_ab(0xAB)   —— **本件的正面判据**
  r0_none  vs r4_spec_ab(0xAB)      —— 重复
判读：
  * 0xCD 与 0xAB 两处画面/状态仍分不出 ⇒ 这把尺子对固件内容**不敏感**（CX4 在本片没被使能，
    或 BizHawk 压根没执行它）⇒ 拿假字节永远回答不了 D1，只有真固件（`188D471F…`）才行，
    而真固件要用户批准才能下载 ⇒ D1 继续暂缓，且理由从「放文件没用」升级成「这条路测不出来」。
  * 0xCD 与 0xAB 出现画面差异 ⇒ 核心确实在执行喂进去的字节 ⇒ 尺子是活的，
    那么 ab12 的「r0 与 r1 相同」就变成**实质结论**：本片这段不依赖 CX4 内容。
串行：EmuHawk 一次一个，等 ab12 退出才启动。
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
import ab12_full as AB                  # noqa: E402

SCR, BIZ, CFG = AB.SCR, AB.BIZ, AB.CFG
DUMMY_AB = os.path.join(BIZ, "Firmware", "cx4_spec_ab.bin")


def run_dummy(tag, fill):
    """跟 ab12 的 r1 臂同一条路，只换填充字节。"""
    fw = os.path.join(BIZ, "Firmware")
    for f in os.listdir(fw):
        os.remove(os.path.join(fw, f))
    base = open(CFG, encoding="utf-8", errors="replace").read()
    pat = re.compile(r'"FirmwareUserSpecifications"\s*:\s*\{[^{}]*\}')
    if not pat.search(base):
        raise RuntimeError("config.ini 没有 FirmwareUserSpecifications 字段，前提不成立")
    blob = pat.sub('"FirmwareUserSpecifications": { "%s": "%s" }'
                   % (AB.KEY, DUMMY_AB.replace("\\", "/")), base, count=1)
    with open(CFG, "w", encoding="utf-8") as fh:
        fh.write(blob)
    w = os.path.join(SCR, tag)
    if os.path.isdir(w):
        shutil.rmtree(w)
    os.makedirs(w)
    try:
        with open(DUMMY_AB, "wb") as fh:
            fh.write(bytes([fill]) * 32768)
        m, r = os.path.join(w, "movie.bk2"), os.path.join(w, "rom.sfc")
        tas_replay.materialize_movie(AB.MOVIE, m)
        tas_replay.materialize_rom(AB.ROM, r)
        lua = os.path.join(w, "cap.lua")
        with open(lua, "w", encoding="utf-8") as fh:
            fh.write(AB.LUA % (w.replace("\\", "/"), ",".join(str(x) for x in AB.MARKS), AB.FRAMES))
        t0 = time.time()
        with open(os.path.join(w, "emulator.log"), "wb") as lf:
            proc = subprocess.Popen([os.path.join(BIZ, "EmuHawk.exe"), "--chromeless",
                                     "--movie=" + m, "--lua=" + lua, r],
                                    cwd=BIZ, stdout=lf, stderr=subprocess.STDOUT)
            wd = WD.watch_process(proc, w, hard_timeout=7200)
    finally:
        with open(CFG, "w", encoding="utf-8") as fh:
            fh.write(base)
        if os.path.exists(DUMMY_AB):
            os.remove(DUMMY_AB)
    logs = WD.firmware_console_lines(os.path.join(w, "emulator.log"))
    fwdlg = [t for rec in wd["dismissed_dialogs"] for t in rec["texts"] if "firmware" in t.lower()]
    hb = os.path.join(w, "heartbeat.txt")
    return {"tag": tag, "fill": hex(fill), "termination": wd["termination"],
            "dismissed": wd["dismissed"], "wall": round(time.time() - t0, 1),
            "firmware_dialogs": fwdlg,
            "gate": WD.firmware_verdict(dict(wd, console_texts=logs)),
            "heartbeat": open(hb, errors="replace").read().strip() if os.path.exists(hb) else "",
            "states": sorted(f for f in os.listdir(w) if f.endswith(".m11"))}


def main():
    if AB.emuhawk_running():
        print("!! EmuHawk 正在跑，串行规矩，本批不启动"); return 3
    tas_replay.force_core(BIZ, "SNES", "BSNES")
    rec = run_dummy("r4_spec_ab", 0xAB)
    print("\n=== %-15s term=%s disc=%s fw_dlg=%d %.1fs hb=%s 状态数=%d"
          % (rec["tag"], rec["termination"], rec["dismissed"], len(rec["firmware_dialogs"]),
             rec["wall"], rec["heartbeat"], len(rec["states"])), flush=True)
    for t in rec["firmware_dialogs"]:
        print("    FWDLG:", t[:170])
    print("    GATE:", rec["gate"])
    if rec["firmware_dialogs"]:
        print("\n!! 0xAB 臂警告没消失，注册没生效，本臂白跑"); return 4
    if not rec["heartbeat"].startswith(tuple("0123456789")):
        print("\n!! 0xAB 臂一帧没跑"); return 5
    out = {"arms": {"r4_spec_ab": rec}, "cmp": []}
    print("\n解包三个臂…")
    for tag in ("r0_none", "r1_spec_dummy", "r4_spec_ab"):
        d = os.path.join(SCR, tag)
        names = [x for x in os.listdir(d) if x.endswith(".m11")]
        for f in names:
            AB.F[(tag, os.path.splitext(f)[0])] = SD.parts(os.path.join(d, f))
        print("   %-15s %d 个状态" % (tag, len(names)))
    for a, b, label in (("r1_spec_dummy", "r4_spec_ab", "0xCD vs 0xAB：尺子对固件内容敏不敏感"),
                        ("r0_none", "r4_spec_ab", "什么都不放 vs 0xAB：重复 ab12 的处理效应")):
        rows = AB.compare(a, b, a, b)
        out["cmp"].append({"pair": [a, b], "meaning": label, "rows": rows})
        pic = sum(1 for r in rows if r["picture"] == "不同")
        dif = [r["core_diff_bytes"] for r in rows if isinstance(r["core_diff_bytes"], int)]
        print("    => %s：画面不同 %d/%d，Core.bin 底层差异 min=%s max=%s"
              % (label, pic, len(rows), min(dif) if dif else "-", max(dif) if dif else "-"), flush=True)
    with open(os.path.join(SCR, "ab14_diffgarbage.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    print("\nwrote", os.path.join(SCR, "ab14_diffgarbage.json"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
