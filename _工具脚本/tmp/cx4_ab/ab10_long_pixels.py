# -*- coding: utf-8 -*-
"""CX4 固件 A/B 的长片像素臂（走生产 tas_replay.run_replay，30,000 帧两臂对照）。

为什么还要这一臂：ab4 只跑到 2000 帧（版权页+开场），四臂逐帧 PNG sha 全等，
那只能说明"开场这两千帧芯片内容不影响画面"；C 组又量出「状态字节」这把尺子的
跨进程抖动跟固件信号同一数量级 ⇒ 状态差值不能用来判"内容有没有参与运算"。
唯一还能服的证据是画面本身，而洛克人X2 用到 CX4 的旋转/缩放精灵在关里，不在标题页。
所以把两臂都推到 30,000 帧（约 8.3 分钟影片长度），用生产管线出逐帧 PNG，再抽样比。

两臂：
  P1_none   空 Firmware 目录（本机现状）
  P2_dummy  放 32KB 全 0xCD 的 cx4.rom（内容肯定是错的，若芯片真被执行，画面/回放必然出问题）
看点：
  1) desync / status：生产口径 movie.mode() 离开 PLAY 就判 desync（假固件把芯片算歪 ⇒ 这里先炸）
  2) 逐 1000 帧的 PNG sha 是否相等
  3) 抽 8 对 PNG 落 out_pairs/，由我亲自看图（数值闸门全绿也会漏"画面里多了个人"）
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import watchdog as WD      # noqa: E402
import tas_replay                       # noqa: E402

SCR = r"F:\taspipe_scratch\cx4_ab"
BIZ = os.path.join(SCR, "bizhawk")
MOVIE = r"F:\开源掌机教程\04-游戏资源库\TAS输入录像库\movies\SNES\5628.bk2"
ROM = r"F:\BaiduNetdiskDownload\rom\snes\洛克人 X2.zip!洛克人 X2.sfc"
FILL = bytes([0xCD])
FRAMES = 30000
STEP = 1000
PAIRS = [6000, 10000, 14000, 18000, 22000, 26000, 29000, 30000]


def sha(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest().upper()


def frame_png(d, i):
    for name in ("f%04d.png" % i, "f%05d.png" % i, "f%06d.png" % i):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def arm(tag, files):
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
    t0 = time.time()
    res = tas_replay.run_replay(MOVIE, ROM, "BSNES", "SNES", BIZ, FRAMES, work=w)
    fd = res["frames_dir"]
    marks = {i: (sha(frame_png(fd, i)) if frame_png(fd, i) else None)
             for i in range(0, res["n_frames"] or 0, STEP)}
    rec = {"placed": placed, "wall_s": round(time.time() - t0, 1),
           "n_frames": res["n_frames"], "status": res.get("status"),
           "desync": res["desync"], "termination": res.get("termination"),
           "report": res.get("report"), "work": res["work"],
           "frames_dir": fd, "frames_on_disk": len(os.listdir(fd)),
           "mark_shas": marks,
           "console_texts": (res.get("watchdog") or {}).get("console_texts"),
           "dialogs": [d.get("texts") for d in (res.get("watchdog") or {}).get("dismissed_dialogs", [])],
           "gate": WD.firmware_verdict(res.get("watchdog") or {})}
    print("\n=== %s placed=%s n=%s status=%s desync=%s term=%s %.1fs" % (
        tag, [p["name"] for p in placed], res["n_frames"], res.get("status"),
        res["desync"], res.get("termination"), rec["wall_s"]), flush=True)
    print("    report=%s frames_on_disk=%d" % (rec["report"], rec["frames_on_disk"]), flush=True)
    for d in rec["dialogs"]:
        print("    DLG:", str(d)[:190], flush=True)
    for ln in rec["console_texts"] or []:
        print("    LOG:", ln[:170], flush=True)
    print("    GATE:", rec["gate"][0], rec["gate"][2], flush=True)
    return rec


def main():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EmuHawk.exe"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace").stdout
    if "EmuHawk.exe" in out:
        print("!! EmuHawk 正在跑，本脚本不启动（严格串行）"); return 3
    tas_replay.force_core(BIZ, "SNES", "BSNES")
    a = arm("P1_none", [])
    b = arm("P2_dummy32k", [("cx4.rom", 32768)])

    diff = {k: {"none": a["mark_shas"].get(k), "dummy": b["mark_shas"].get(k),
                "same": a["mark_shas"].get(k) == b["mark_shas"].get(k)}
            for k in sorted(set(a["mark_shas"]) | set(b["mark_shas"]))}
    n_same = sum(1 for v in diff.values() if v["same"])
    print("\n  逐 %d 帧抽样：可比 %d 格，画面相同 %d 格，不同 %d 格" % (
        STEP, len(diff), n_same, len(diff) - n_same), flush=True)
    for k, v in sorted(diff.items()):
        if not v["same"]:
            print("    帧 %-7s none=%s dummy=%s" % (k, str(v["none"])[:10], str(v["dummy"])[:10]),
                  flush=True)

    insp = os.path.join(SCR, "out_pairs_long")
    if os.path.isdir(insp):
        shutil.rmtree(insp)
    os.makedirs(insp)
    copied = []
    for fr in PAIRS:
        pa, pb = frame_png(a["frames_dir"], fr), frame_png(b["frames_dir"], fr)
        if pa and pb:
            shutil.copy(pa, os.path.join(insp, "f%05d_none.png" % fr))
            shutil.copy(pb, os.path.join(insp, "f%05d_dummy.png" % fr))
            copied.append(fr)
    print("    抽来看图的帧:", copied, "->", insp, flush=True)

    res = {"frames_requested": FRAMES, "step": STEP,
           "none": {k: v for k, v in a.items() if k != "mark_shas"},
           "dummy": {k: v for k, v in b.items() if k != "mark_shas"},
           "mark_shas": {"none": a["mark_shas"], "dummy": b["mark_shas"]},
           "sample_diff": diff, "inspection_frames": copied,
           "inspection_dir": insp}
    with open(os.path.join(SCR, "ab10_long_pixels.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print("\nwrote", os.path.join(SCR, "ab10_long_pixels.json"), flush=True)
    return 0


sys.exit(main())
