"""CX4 固件真机四臂 A/B（生产回放件 tas_replay.run_replay）。

前提纠正（11-23 实测）：Firmware 目录空着，BizHawk 也在控制台回了
    Served libsnes request for firmware "cx4.rom"
—— 它压根没抱怨缺固件，也没有弹框。所以「缺 CX4 固件」这个 blocker 得先问清楚：
它 serve 的到底是什么。四个臂用「名字对/长度对/长度错」的已知内容假固件去试它的反应。

臂：
  1 无固件            Firmware/ 空                      —— 基线
  2 假固件_1K         Firmware/cx4.rom = 1024×0xCD      —— 名字对、长度错
  3 假固件_32K        Firmware/cx4.rom = 32768×0xCD     —— 名字对、长度对、内容错
  4 假固件_32K大写名  Firmware/SNES_cx4.rom = 32768×0xCD—— 换成固件库里的文件名字面量

判读：
  臂2 若报长度错     => 那个文件真被读了，BizHawk 按名字找、按长度/哈希验内容
  臂3 若画面变       => serve 的内容会改变 emulation，基线那次 serve 的不是这份
  臂3 若画面不变     => 要么读都不读（另有来源），要么这 2000 帧没调用到芯片
所有 work/frames 放 ASCII 路径：cap.lua 的 io.open 在中文目录下返回 nil，
整跑会被 Lua 异常打死（11-23 第一版探针就是这么只出 1 帧的）。
"""
import hashlib
import json
import os
import shutil
import sys
import time

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import registry as R      # noqa: E402
from taspipe import watchdog as WD     # noqa: E402
import tas_replay                      # noqa: E402

JSON_ID = r"F:\开源掌机教程\_工具脚本\tmp\cx4_ab\assess_5628.json"
BIZHAWK = r"F:\taspipe_scratch\cx4_ab\bizhawk"          # ASCII 副本
SCRATCH = r"F:\taspipe_scratch\cx4_ab"
FRAMES = 2000
# 臂名一律 ASCII：work 目录名一旦带中文，cap.lua 的 io.open 就返回 nil，
# 整跑只出 1 帧（11-23 连踩两次，第二次就是 work_1_无固件 害的）。
ARMS = [
    ("arm1_none", None, "1_无固件"),
    ("arm2_cx4rom_1k", ("cx4.rom", 1024), "2_假固件_1K_长度错"),
    ("arm3_cx4rom_32k", ("cx4.rom", 32768), "3_假固件_32K"),
    ("arm4_snescx4rom_32k", ("SNES_cx4.rom", 32768), "4_假固件_32K_库文件名"),
]
FILL = bytes([0xCD])


def sha(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest().upper()


def frame_shas(d):
    if not os.path.isdir(d):
        return {}
    return {f: sha(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith(".png")}


def firmware_lines(log_path):
    """日志里所有提到 firmware 的行（不加我的 marker 过滤，先看真相全貌）。"""
    if not os.path.isfile(log_path):
        return []
    out = []
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "firmware" in line.lower():
                s = line.strip()
                if s not in out:
                    out.append(s)
    return out


def setup_copy():
    src = r"F:\开源掌机教程\02-模拟器库\BizHawk\BizHawk-2.9.1"
    if not os.path.isdir(BIZHAWK):
        os.makedirs(SCRATCH, exist_ok=True)
        shutil.copytree(src, BIZHAWK)
    fw = os.path.join(BIZHAWK, "Firmware")
    for f in os.listdir(fw):
        os.remove(os.path.join(fw, f))
    return fw


def main():
    os.makedirs(SCRATCH, exist_ok=True)
    a = json.load(open(JSON_ID, encoding="utf-8"))["assess"]
    movie, rom, core, system = (a["movie"], a["rom_match"][0], a["core"],
                              a["platform_code"])
    fw_dir = setup_copy()
    print("bizhawk copy:", BIZHAWK, "Firmware cleared ->", os.listdir(fw_dir), flush=True)
    print("movie:", movie, "\nrom:", rom, flush=True)

    result = {"frames_requested": FRAMES, "arms": {}}
    for key, spec, name in ARMS:
        for f in os.listdir(fw_dir):
            os.remove(os.path.join(fw_dir, f))
        placed = None
        if spec:
            fn, size = spec
            placed = {"name": fn, "size": size, "fill": "0xCD"}
            with open(os.path.join(fw_dir, fn), "wb") as fh:
                fh.write(FILL * size)
            placed["sha1"] = sha(os.path.join(fw_dir, fn))
        work = os.path.join(SCRATCH, key)
        if os.path.isdir(work):
            shutil.rmtree(work)
        t0 = time.time()
        res = tas_replay.run_replay(movie, rom, core, system, BIZHAWK, FRAMES, work=work)
        fdir = res["frames_dir"]
        if res["n_frames"] < max(2, FRAMES // 4):
            print("!! %s 只出 %d/%d 帧，这臂的证据不成立，日志尾如下:" % (
                name, res["n_frames"], FRAMES), flush=True)
            tail = open(os.path.join(work, "emulator.log"),
                        encoding="utf-8", errors="replace").read().splitlines()[-6:]
            for ln in tail:
                print("   TAIL:", ln[:200], flush=True)
        lg = os.path.join(work, "emulator.log")
        rec = {
            "firmware_placed": placed,
            "wall_s": round(time.time() - t0, 1),
            "termination": res["termination"],
            "status": res["status"],
            "desync": res["desync"],
            "n_frames": res["n_frames"],
            "report": res["report"][-260:],
            "emulator_log_bytes": os.path.getsize(lg) if os.path.isfile(lg) else None,
            "firmware_lines": firmware_lines(lg),
            "gate_console_texts": WD.firmware_console_lines(lg),
            "gate_verdict": WD.firmware_verdict(res["watchdog"]),
            "first_frame_sha": next(iter(frame_shas(fdir).values()), None),
            "last_frame_sha": list(frame_shas(fdir).values())[-1:] or [None],
            "all_frame_shas": frame_shas(fdir),
        }
        result["arms"][key] = dict(rec, label=name)
        print("\n=== %s  placed=%s  n=%s term=%s status=%s desync=%s  %.1fs" % (
            name, placed, res["n_frames"], res["termination"], res["status"],
            res["desync"], rec["wall_s"]), flush=True)
        for ln in rec["firmware_lines"]:
            print("   LOG:", ln[:180], flush=True)
        print("   GATE:", rec["gate_verdict"][0], "|", rec["gate_verdict"][1][:150], flush=True)
        print("   frames_sha_count=%d first=%s last=%s" % (
            len(rec["all_frame_shas"]), str(rec["first_frame_sha"])[:12],
            str(rec["last_frame_sha"][0])[:12]), flush=True)

    base = result["arms"]["arm1_none"]["all_frame_shas"]
    for key, _s, name in ARMS[1:]:
        other = result["arms"][key]["all_frame_shas"]
        keys = sorted(set(base) | set(other))
        diff = [k for k in keys if base.get(k) != other.get(k)]
        result["arms"][key]["diff_vs_arm1"] = {"count": len(diff), "first": diff[:10]}
        print("\n%s vs 1_无固件: 不同帧数=%d %s" % (name, len(diff), diff[:8]), flush=True)
    with open(os.path.join(SCRATCH, "ab4.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("\nwrote", os.path.join(SCRATCH, "ab4.json"), flush=True)


main()
