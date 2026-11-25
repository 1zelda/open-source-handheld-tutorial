# -*- coding: utf-8 -*-
"""ab13：给 ab12 补「同配置跨进程对照」和整片重复臂，凑成 2x2。

为什么要这一轮：ab12 每臂只跑一个进程，手里那个底数 **234–297 字节只是在帧 60 量过的**（§45.4）。
帧 100,000 的状态比帧 60 大得多，噪声带凭什么不随长度涨？拿不出长段底数，
ab12 的 r0 vs r1 差异一旦落在模糊带就没法区分「假字节进了状态」和「跨进程噪声」。

本轮四个格子（前两个 ab12 已经跑完、只解包不重跑）：
    r0_none        r2_none          同配置跨进程 ⇒ 长段**噪声底数**
    r1_spec_dummy  r3_spec_dummy    同配置跨进程 ⇒ 处理臂自己的噪声底数
    r0 vs r1 / r2 vs r3              同两种配置的两份**独立重复** ⇒ 处理效应能不能复现

判读：
  * 画面（Framebuffer.bmp）任一标记在两配置间不同，且另一份重复同向 ⇒ 假字节真改了画面 ⇒ D1 立刻办。
  * 画面全同，且 r0-r1 差异 ≈ 本轮量到的长段底数 ⇒ 字节压根没进状态（那 32KB 没被使能）。
  * 画面全同，但 r0-r1 差异 ≫ 底数、而底数也 ≫ 0 ⇒ 先别下结论：字节进了状态但没改变画面，
    只能说明这 32KB 的内容不使能 CX4 运算，不能说明真固件不改画面。
串行规矩：EmuHawk 一次一个，本件启动前先量、再等 ab12 退出。
"""
import json
import os
import sys

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ab12_full as AB                    # noqa: E402  复用 run_arm/compare/MARKS/F

SCR = AB.SCR


def collect(tag):
    """把某臂工作目录里已存的状态解到底层，塞进 AB.F 供 compare 用。"""
    w = os.path.join(SCR, tag)
    for f in sorted(x for x in os.listdir(w) if x.endswith(".m11")):
        AB.F[(tag, os.path.splitext(f)[0])] = AB.SD.parts(os.path.join(w, f))
    return [x for x in os.listdir(w) if x.endswith(".m11")]


def main():
    if AB.emuhawk_running():
        print("!! EmuHawk 正在跑（ab12 还没退），本件按串行规矩不启动"); return 3
    AB.tas_replay.force_core(AB.BIZ, "SNES", "BSNES")
    res = {"marks": AB.MARKS, "frames": AB.FRAMES, "arms": {}}
    for tag, spec in [("r2_none", None), ("r3_spec_dummy", AB.DUMMY)]:
        rec = AB.run_arm(tag, spec)
        res["arms"][tag] = rec
        print("\n=== %-15s spec=%-5s term=%s disc=%s fw_dlg=%d %.1fs hb=%s 状态数=%d"
              % (tag, rec["spec"], rec["termination"], rec["dismissed"],
                 len(rec["firmware_dialogs"]), rec["wall"], rec["heartbeat"],
                 len(rec["states"])), flush=True)
        for t in rec["firmware_dialogs"]:
            print("    FWDLG:", t[:170])
        for l in rec["console_firmware_lines"][:2]:
            print("    LOG:", l[:150])
        if rec["spec"] and rec["firmware_dialogs"]:
            print("\n!! 处理臂警告没消失，字节没进核心，本轮白跑"); return 4
        if not rec["heartbeat"].startswith(tuple("0123456789")):
            print("\n!! %s 一帧没跑" % tag); return 5
        if len(rec["states"]) != len(AB.MARKS):
            print("\n!! %s 状态数 %d != 标记数 %d，格子不齐"
                  % (tag, len(rec["states"]), len(AB.MARKS)))

    for tag in ("r0_none", "r1_spec_dummy", "r2_none", "r3_spec_dummy"):
        if os.path.isdir(os.path.join(SCR, tag)):
            n = collect(tag)
            print("解包 %-15s %d 个状态" % (tag, len(n)))
    pairs = [("r0_none", "r2_none", "同配置跨进程（都不放）=长段噪声底数"),
             ("r1_spec_dummy", "r3_spec_dummy", "同配置跨进程（都放）=处理臂噪声底数"),
             ("r0_none", "r1_spec_dummy", "重复 1：什么都不放 vs 注册 32KB"),
             ("r2_none", "r3_spec_dummy", "重复 2：什么都不放 vs 注册 32KB")]
    res["cmp"] = []
    for a, b, label in pairs:
        if not (os.path.isdir(os.path.join(SCR, a)) and os.path.isdir(os.path.join(SCR, b))):
            print("\n跳过 %s（缺一臂）" % label)
            continue
        rows = AB.compare(a, b, a, b)
        res["cmp"].append({"pair": [a, b], "meaning": label, "rows": rows})
        pic = sum(1 for r in rows if r["picture"] == "不同")
        dif = [r["core_diff_bytes"] for r in rows if isinstance(r["core_diff_bytes"], int)]
        print("    => 画面不同 %d/%d；Core.bin 底层差异 min=%s max=%s"
              % (pic, len(rows), min(dif) if dif else "-", max(dif) if dif else "-"))
    with open(os.path.join(SCR, "ab13_replicate.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    print("\nwrote", os.path.join(SCR, "ab13_replicate.json"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
