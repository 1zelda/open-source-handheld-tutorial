"""CX4 固件三臂真机 A/B（生产路径：record.run_full + tas_replay.run_replay）。

A 臂 = 真安装目录 BizHawk-2.9.1（Firmware 空）
B 臂 = 隔离副本，Firmware 空      —— 应与 A 等价，用来证明「副本本身不引入差异」
C 臂 = 同一隔离副本 + Firmware/CX4.bin = 32768 字节全零（sha1 已知）

要回答的问题：
1. 固件提示到底走哪个通道——弹框（dismissed_dialogs）还是控制台（emulator.log）？
2. BizHawk 认名字还是认哈希：放了名字对、内容错的文件，它是照收、报错，还是拒载？
3. 假固件会不会改变画面：逐帧 PNG sha1 与 B 臂比对，相同=那块芯片压根没被用上。

ROM/电影身份全部走生产 resolve/assess；不下网盘、不改真安装目录里的固件槽位。
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import registry as R          # noqa: E402
from taspipe import record as REC          # noqa: E402
from taspipe.backends import BizHawkNESBackend  # noqa: E402
from taspipe import watchdog as WD         # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = 5628
FRAMES = 1200
ARMS = [
    ("A_真安装", r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.9.1"),
    ("B_隔离无固件", os.path.join(HERE, "bizhawk_clean")),
    ("C_隔离假固件", os.path.join(HERE, "bizhawk_dummy")),
]


def sha(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest().upper()


def frame_shas(d):
    out = {}
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        if f.endswith(".png"):
            out[f] = sha(os.path.join(d, f))
    return out


def log_summary(path):
    """控制台日志：总行数 + 命中固件 marker 的行（原样，最多 20 条）。"""
    if not os.path.isfile(path):
        return {"exists": False}
    total = 0
    hits = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            total += 1
            if any(m in line.lower() for m in WD._FIRMWARE_MARKERS) and len(hits) < 20:
                hits.append(line.strip())
    return {"exists": True, "lines": total, "size": os.path.getsize(path),
            "firmware_hits": hits}


def main():
    lib = R.DEFAULT_LIB
    pubs = {int(p["id"]): p for p in R.load_publications(lib)}
    ri, vi = R.index_roms(lib), R.index_versions(lib)
    bh = R.discover_bizhawk(R.DEFAULT_EMU)
    a = R.assess(pubs[PUB], lib, ri, vi, bh)
    ident = {"movie": a["movie"], "rom": a["rom_match"][0], "core": a["core"],
             "system": a["platform_code"], "profile": a["profile"],
             "required_rom_sha1": a["required_rom_sha1"], "blockers": a["blockers"]}
    print("ident:", json.dumps({k: v for k, v in ident.items() if k != "profile"},
                               ensure_ascii=False), flush=True)
    hdr = R.read_bk2_header(ident["movie"])
    print("bk2 Header SNES_Firmware_CX4 =", hdr.get("SNES_Firmware_CX4"), flush=True)

    summary = {"identity": {k: v for k, v in ident.items() if k != "profile"},
               "bk2_header_firmware": hdr.get("SNES_Firmware_CX4"),
               "frames_requested": FRAMES, "arms": {}}
    for name, bd in ARMS:
        fw_dir = os.path.join(bd, "Firmware")
        fw_files = sorted(os.listdir(fw_dir)) if os.path.isdir(fw_dir) else None
        out = os.path.join(HERE, "out_" + name)
        t0 = time.time()
        print("\n=== %s  bizhawk=%s  Firmware=%s" % (name, bd, fw_files), flush=True)
        be = BizHawkNESBackend(bd)
        run = REC.run_full(be, ident["profile"], ident["movie"], ident["rom"], out,
                           frames=FRAMES, fps=60, core=ident["core"],
                           system=ident["system"], audio=False)
        rows = {c["check_id"]: c for c in run["verification"]["checks"]}
        work = os.path.dirname(rows["replay_no_desync"]["evidence_refs"][0])
        frames_dir = os.path.join(work, "frames")
        rec = {
            "bizhawk_dir": bd,
            "firmware_dir_listing": fw_files,
            "wall_s": round(time.time() - t0, 1),
            "work": work,
            "n_frames": rows["frames_captured"]["reason"],
            "replay": rows["replay_no_desync"]["reason"],
            "firmware_check": rows.get("chip_firmware_missing"),
            "watchdog_console_texts": WD.firmware_console_lines(
                os.path.join(work, "emulator.log")),
            "console_log": log_summary(os.path.join(work, "emulator.log")),
            "dismissed_dialogs": (run.get("watchdog") or {}).get("dismissed_dialogs"),
            "verification_verdict": run["verification"]["verdict"],
            "frames_sha_count": len(frame_shas(frames_dir)),
            "frames_sha_sample": dict(list(frame_shas(frames_dir).items())[:3]),
            "frames_sha_full": frame_shas(frames_dir),
            "run_id": run.get("run_id") or run.get("id"),
        }
        summary["arms"][name] = rec
        print("  chip_firmware_missing ->", json.dumps(rec["firmware_check"], ensure_ascii=False),
              flush=True)
        print("  console lines=%s firmware_hits=%d" % (
            rec["console_log"].get("lines"), len(rec["console_log"].get("firmware_hits", []))),
              flush=True)
        print("  verification=%s  n_frames=%s" % (rec["verification_verdict"],
                                                  rec["n_frames"]), flush=True)

    # 臂间逐帧比对：B vs C 是「假固件到底改没改画面」的直接答案
    b = summary["arms"]["B_隔离无固件"]["frames_sha_full"]
    c = summary["arms"]["C_隔离假固件"]["frames_sha_full"]
    diffs = [k for k in sorted(set(b) | set(c)) if b.get(k) != c.get(k)]
    a_vs_b = [k for k in sorted(set(b) | (summary["arms"]["A_真安装"]["frames_sha_full"] or {}))
              if b.get(k) != summary["arms"]["A_真安装"]["frames_sha_full"].get(k)]
    summary["B_vs_C_diff_frames"] = diffs[:40]
    summary["B_vs_C_diff_count"] = len(diffs)
    summary["A_vs_B_diff_frames"] = a_vs_b[:40]
    summary["A_vs_B_diff_count"] = len(a_vs_b)
    with open(os.path.join(HERE, "ab_result.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("\nB vs C 不同的帧数 =", len(diffs), diffs[:12], flush=True)
    print("A vs B 不同的帧数 =", len(a_vs_b), a_vs_b[:12], flush=True)
    print("wrote", os.path.join(HERE, "ab_result.json"), flush=True)


main()
