# -*- coding: utf-8 -*-
"""ab17：用 **ab11 自己的代码**再跑一遍 k0_none 和 key_CX4，判 ab11 的「注册把警告框压掉了」还成不成立。

为什么必须做这一批（全部是本轮实测逼出来的）：
  * ab16（本轮，6 臂，日志 F:/taspipe_scratch/cx4_ab/ab16.log）里
    `b1_spec_CX4rom_inFW`＝注册 `CX4 → Firmware/cx4.rom`（32KB 0xCD），和 ab11 那次唯一生效的臂
    **键名、文件名、长度、填充全同**，警告框却照样弹（fw_dialogs=1）。
  * ab16 b1 的 emulator.log 与 ab11 key_CX4 的 emulator.log **逐行相同**（归一化后 difflib 只差
    三行 Save/Blit 计时）⇒ 两边 BizHawk 在控制台上的行为一模一样，差别只在**看门狗记没记下那个框**。
  ⇒ 两种可能：①ab11 的抑制是真的，某个我没记进 JSON 的变量在这期间变了（配置基线、核心选择、
    exe 实物）；②ab11 那个框其实弹了，只是它的看门狗没抓到/没记到，`firmware_dialog_count=0`
    是**采集假象**——那「只有 CX4/SNES+CX4 两个键能压框」整条结论就要撤回，教程那句
    「丢进 Firmware 目录」的判法不受影响（目录侧证据是 ab9/ab10 的四种文件名，警告照弹）。
  ab11 的 JSON 只给 bisect 臂存了 (键名, 警告数, 终止, 控制台行) 四元组，**没存**当时的 config 正文
  和 all_dialogs，所以现在无从回查。本件把缺的两样当场补记，别的什么都不改：
  直接 import ab11_spec，调它自己的 run_arm()，跑 k0_none（正例：应当弹框）与 key_CX4（争议臂）。

判读：
  * key_CX4 警告数=0 且 all_dialogs 里确实没有固件正文 ⇒ ab11 复现成功 ⇒ 变量在 ab11 之外
    （下一步查 exe/核心/config 基线三项，ab16 与 ab11 的差集里找）。
  * key_CX4 警告数=1 ⇒ ab11 的抑制结论作废，注册门从来没压过框；
    那 ab12 的处理臂同样是假臂（已知），「假字节测不了 CX4 内容」这条只剩真固件一条路，D1 维持暂缓。
串行：EmuHawk 一次一个；run_arm 自带 finally 还原 config；本件跑完把用过的 config 正文落盘。
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ab11_spec as A11                 # noqa: E402
import tas_replay                       # noqa: E402

SCR = A11.SCR
CFG_LOG = os.path.join(SCR, "ab17_config_used.json")


def cfg_snapshot():
    raw = open(A11.CFG, encoding="utf-8", errors="replace").read()
    import json as J
    try:
        d = J.loads(raw)
    except Exception:
        d = None
    return {"sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "parse_ok": d is not None,
            "firmware_user_specs": (d or {}).get("FirmwareUserSpecifications"),
            "recent_cores": (d or {}).get("RecentCores"),
            "snes_core_keys": {k: v for k, v in (d or {}).items()
                               if isinstance(k, str) and k.startswith("SNES")}
                            if d else None}


def exe_snapshot():
    p = os.path.join(A11.BIZ, "EmuHawk.exe")
    b = open(p, "rb").read()
    return {"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest(),
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p)))}


def main():
    if A11.emuhawk_running():
        print("!! EmuHawk 正在跑，串行规矩，本批不启动"); return 3
    snap = {"exe": exe_snapshot(), "config_before": cfg_snapshot()}
    print("EmuHawk.exe:", json.dumps(snap["exe"], ensure_ascii=False))
    print("起跑 config:", json.dumps(snap["config_before"], ensure_ascii=False)[:400], flush=True)
    tas_replay.force_core(A11.BIZ, "SNES", "BSNES")
    snap["config_after_force_core"] = cfg_snapshot()
    print("force_core 后:", json.dumps(snap["config_after_force_core"]["firmware_user_specs"],
                                       ensure_ascii=False), flush=True)
    out = {"snapshot": snap, "arms": {}}
    for tag, dummy, spec in [("r0_none", False, {}),
                             ("r1_key_CX4", True, {"CX4": A11.DUMMY})]:
        rec = A11.run_arm(tag, dummy, spec)
        out["arms"][tag] = rec
        print("\n=== %-11s dismissed=%s fw_count=%s term=%s hb=%r cfg_restored=%s %.1fs" %
              (tag, rec["dismissed"], rec["firmware_dialog_count"], rec["termination"],
               rec["heartbeat"][:20], rec["cfg_restored_ok"], rec["elapsed"]), flush=True)
        print("    all_dialogs:", json.dumps(rec["all_dialogs"], ensure_ascii=False)[:400])
        print("    gate:", rec["gate"][0], "|", str(rec["gate"][1])[:120])
        with open(os.path.join(SCR, "ab17_replicate.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    fw0 = out["arms"]["r0_none"]["firmware_dialog_count"]
    fw1 = out["arms"]["r1_key_CX4"]["firmware_dialog_count"]
    print("\n--- 判定：r0 警告=%d r1 警告=%d" % (fw0, fw1))
    if fw1 == 0 and fw0 > 0:
        print("  ⇒ ab11 的抑制在本沙盒**当前状态**下仍成立（用 ab11 自己的代码）；"
              "ab16 用等价参数却弹框 ⇒ 差在两个脚本之间的某个变量，继续查 exe/核心/config")
    elif fw1 > 0:
        print("  ⇒ ab11 的「注册 CX4 能压掉警告框」复现失败 ⇒ 撤回该结论；"
              "注册门从来没有压框、也没有喂字节，假字节测不了 CX4 内容")
    else:
        print("  ⇒ 反常：r0 没弹框（基线坏了），整批不可用，重跑")
    with open(os.path.join(SCR, "ab17_replicate.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    with open(CFG_LOG, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, ensure_ascii=False, indent=1, default=str)
    print("wrote", os.path.join(SCR, "ab17_replicate.json"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
