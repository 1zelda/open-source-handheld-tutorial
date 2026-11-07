#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""扫遍 (d)ArkOS4Clone 里所有 .dtb, 解出每块机型的屏幕真值, 落成 TSV + Markdown 表。

为什么要扫 dtb 而不是读文档: 上游文档里的"768P/720P"只是 logo 目录名,
既没写横竖屏也没写物理尺寸; 而面板分辨率直接决定主题、视口、渲染分辨率能不能用。
dtb 里的 display-timings 是编译进镜像的事实, 不会说谎。

用法: py -3 _工具脚本/dtb_panel_sweep.py
"""
import csv
import io
import json
import math
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtb_peek import parse  # noqa: E402

ROOT = r"F:\开源掌机教程\02-模拟器库\已clone仓库\R36S专用"
SOURCES = [
    ("arkos4clone", os.path.join(ROOT, "arkos4clone", "boot", "dArkOS", "consoles")),
    ("R36S-DTB", os.path.join(ROOT, "R36S-DTB")),
]
OUT_TSV = r"F:\开源掌机教程\05-硬件与机型资料\panel_specs.tsv"
OUT_MD = r"F:\开源掌机教程\05-硬件与机型资料\屏幕真值表.md"

CELL = ("hactive", "vactive", "clock-frequency")


def u32s(val):
    if len(val) % 4:
        return []
    return list(struct.unpack(">%dI" % (len(val) // 4), val))


def cstr_list(val):
    return [x.decode("ascii", "replace") for x in val.split(b"\0") if x]


def scan(path):
    with open(path, "rb") as fh:
        buf = fh.read()
    items, _ = parse(buf)
    all_paths = []
    timings = []          # (hactive, vactive, clock)
    cur = ""
    lanes = set()
    panel_compat = set()
    for it in items:
        if len(it) == 2:
            cur = it[0]
            all_paths.append(cur)
        else:
            prop, val, _parent = it
            if prop in CELL and "display-timing" in cur:
                nums = u32s(val)
                if len(nums) == 1:
                    timings.append((prop, nums[0]))
            elif prop in ("data-lanes", "bus-width"):
                lanes.update(str(x) for x in u32s(val))
            elif prop == "compatible" and "panel" in cur:
                panel_compat.update(cstr_list(val))
            elif prop in ("width-mm", "height-mm"):
                nums = u32s(val)
                if len(nums) == 1:
                    timings.append((prop + "@" + cur.split("/")[-1], nums[0]))

    hv = {}
    for k, v in timings:
        if k == "hactive":
            hv["h"] = max(hv.get("h", 0), v)
        elif k == "vactive":
            hv["v"] = max(hv.get("v", 0), v)
        elif k == "clock-frequency":
            hv["clk"] = max(hv.get("clk", 0), v)
    mm = {}
    for k, v in timings:
        if k.startswith("width-mm"):
            mm["w"] = max(mm.get("w", 0), v)
        elif k.startswith("height-mm"):
            mm["h"] = max(mm.get("h", 0), v)

    joined = " ".join(all_paths).lower()
    if "dsi" in joined:
        iface = "MIPI-DSI"
    elif "lvds" in joined:
        iface = "LVDS"
    elif "edp" in joined:
        iface = "eDP"
    elif "/dp@" in joined or "display-subsystem/dp" in joined:
        iface = "DP"
    elif "hdmi" in joined:
        iface = "HDMI"
    elif "rgb" in joined:
        iface = "RGB"
    elif "spi" in joined:
        iface = "SPI"
    else:
        iface = "?"

    diag = ""
    dpi = ""
    if mm.get("w") and mm.get("h") and hv.get("h") and hv.get("v"):
        d_mm = math.hypot(mm["w"], mm["h"])
        diag = "%.2f" % (d_mm / 25.4)
        dpi = "%.0f" % (math.hypot(hv["h"], hv["v"]) / (d_mm / 25.4))
    return {
        "h": hv.get("h", 0), "v": hv.get("v", 0), "clk_mhz": round(hv.get("clk", 0) / 1e6, 1),
        "iface": iface, "lanes": ",".join(sorted(lanes)) if lanes else "",
        "w_mm": mm.get("w", ""), "h_mm": mm.get("h", ""), "diag_in": diag, "dpi": dpi,
        "panel": ";".join(sorted(panel_compat))[:60],
    }


def load_detect():
    """解析上游 console-detect 的 C 源码, 拿到"固件会怎么对待这块板子"的表。

    dtb 说的是硬件是什么; console_detect.c 说的是系统按什么参数去配它
    (旋转角度、热键类型、LED 方案、音量读法)。两张表拼起来才是能用的信息。
    """
    path = os.path.join(ROOT, "console-detect", "console_detect.c")
    if not os.path.exists(path):
        print("提示: 未 clone console-detect, 行为表留空")
        return {}, {}, {}
    src = open(path, encoding="utf-8", errors="replace").read()
    res = dict((m.group(1), (int(m.group(2)), int(m.group(3))))
               for m in re.finditer(r'\{"(\w+)",\s*(\d+),\s*(\d+)\}', src))
    cfg = {}
    for m in re.finditer(
            r'\{"([a-z0-9_\-]+)",\s*"(\w+)",\s*"(single|dual|none)",\s*"(select|happy5)",\s*'
            r'(\d+),\s*"([a-z0-9_\-]+)",\s*"(auto|manual)",\s*"(adc|gpio)?"\}', src):
        cfg[m.group(1)] = {
            "resolution_tag": m.group(2),
            "px": res.get(m.group(2)),
            "joystick": m.group(3),
            "hotkey_type": m.group(4),
            "rotation": int(m.group(5)),
            "led_type": m.group(6),
            "otg_type": m.group(7),
            "volume_type": m.group(8),
        }
    d2d = {m.group(1): m.group(2)
           for m in re.finditer(r'\{"([\w\-\.]+\.dtb)",\s*"([\w\- ]+)"\}', src)}
    return res, cfg, d2d


def main():
    _res, detect_cfg, dtb2dev = load_detect()
    rows = []
    for source, base in SOURCES:
        if not os.path.isdir(base):
            print("跳过(不存在):", base)
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in sorted(files):
                if not fn.endswith(".dtb"):
                    continue
                rel = os.path.relpath(dirpath, base).replace("\\", "/")
                if rel == ".":
                    rel = fn
                info = scan(os.path.join(dirpath, fn))
                # 优先按 dtb 文件名查 console-detect 的映射表; 查不到时退回目录名
                # (目录名恰好等于 device_configs 里的机型名时仍然有效)
                dev = dtb2dev.get(fn) or (rel if rel in detect_cfg else "")
                beh = detect_cfg.get(dev, {})
                if fn in dtb2dev:
                    known = "dtb"          # dtb 文件名在 console-detect 映射表里 -> 固件能认出
                elif dev:
                    known = "dir"          # 仅目录名与机型名相同, 固件仍按文件名查, 会回落
                else:
                    known = "no"           # 表里没有 -> console_detect 默认 r36s
                info.update(source=source, device=rel, dtb=fn, console=dev, known=known,
                            px_tag=beh.get("resolution_tag", ""),
                            joystick=beh.get("joystick", ""),
                            hotkey=beh.get("hotkey_type", ""),
                            rotation=beh.get("rotation", ""),
                            led=beh.get("led_type", ""),
                            volume=beh.get("volume_type", ""))
                rows.append(info)

    os.makedirs(os.path.dirname(OUT_TSV), exist_ok=True)
    cols = ["device", "source", "dtb", "console", "known", "iface", "h", "v", "clk_mhz", "lanes",
            "w_mm", "h_mm", "diag_in", "dpi", "panel",
            "px_tag", "joystick", "hotkey", "rotation", "led", "volume"]
    with open(OUT_TSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in cols})

    # Markdown: 同一机型目录里多个 dtb 通常同值, 按 (机型,分辨率,接口,行为) 去重
    uniq = {}
    for r in rows:
        uniq.setdefault((r["device"], r["h"], r["v"], r["iface"], r["diag_in"],
                         r["console"], r["known"], r["rotation"], r["hotkey"]), r)
    uniq = sorted(uniq.values(), key=lambda r: (-(r["h"] * r["v"]), r["device"]))
    KNOWN = {"dtb": "✅", "dir": "⚠️仅目录名", "no": "❌回落r36s"}
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("# RK3326 机型屏幕真值表(解析 dtb 得出)\n\n")
        fh.write("> 由 `_工具脚本/dtb_panel_sweep.py` 直接解析镜像自带的 `.dtb` 生成, 不是抄文档。\n")
        fh.write("> 数据源: %s\n" % " + ".join("%s(%s)" % s for s in SOURCES))
        fh.write("> `倍率` 以 R36S 的 640x480=307200 像素为 1.00x, 用来横向比较渲染负担;"
                 "2.5x 意味着同等设置下 GPU 开销约 2.5 倍。\n")
        fh.write("> `console/识别/热键/摇杆/旋转/LED/音量` 来自上游 `console-detect/console_detect.c`"
                 "的三张表(dtb 文件名 -> 机型名 -> 行为参数)。`识别` 列回答的是"
                 "「固件会不会正确认我的板子」: ✅=dtb 文件名在映射表里; "
                 "⚠️=只有目录名对得上, 固件按文件名查, 实际仍会回落; "
                 "❌=表里根本没有这个文件名, console_detect 默认按 r36s 配(旋转/热键/LED/音量全错)。\n"
                 "> 所以**永远不要为了省事改 dtb 文件名** —— 改名等于把机型身份丢掉。\n"
                 "> 补充: 表里对 R36S 原厂面板(origin/sauce/`rk3326-r35s-linux.dtb`)本来就有意不收录,"
                 "让它们回落到 `r36s` 正是期望结果;危险的是 xf45v 这类非 R36S 机型被改名或漏配后回落 —— "
                 "那会把 1024x768 的面板按 640x480 + 错误热键/LED 来配。\n")
        fh.write("> ⚠️ `尺寸mm/对角寸/DPI` 是 dtb 里 `width-mm/height-mm` 的原值, **整列都不可信**:"
                 "XiFan 全系/clone 全系/u8 同为 153x85, 而 1024x768 的 R46H/R40XX 又抄成 R36S 的 52x70,"
                 "显然是厂商改分辨率时忘了改物理尺寸。寸数与 DPI 请以商品页或卡尺实测为准, 这三列只作原始证据保留。\n\n")
        fh.write("| 机型/目录 | console | 识别 | 接口 | 分辨率 | 倍率 | 像素时钟MHz | lanes | 尺寸mm | 对角寸 | DPI | 热键 | 摇杆 | 旋转 | LED | dtb |\n")
        fh.write("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for r in uniq:
            px = r["h"] * r["v"]
            fh.write("| `%s` | %s | %s | %s | %dx%d | %.2fx | %s | %s | %sx%s | %s | %s | %s | %s | %s | %s | `%s` |\n" % (
                r["device"], r["console"] or "-", KNOWN.get(r["known"], "-"),
                r["iface"], r["h"], r["v"], px / 307200.0,
                r["clk_mhz"], r["lanes"], r["w_mm"], r["h_mm"],
                r["diag_in"], r["dpi"], r["hotkey"] or "-", r["joystick"] or "-",
                r["rotation"] if r["rotation"] != "" else "-", r["led"] or "-", r["dtb"]))
    print("rows=%d uniq=%d" % (len(rows), len(uniq)))
    stat = {}
    for r in rows:
        stat[r["known"]] = stat.get(r["known"], 0) + 1
    print("console-detect 覆盖率: 按文件名认出=%d, 仅目录名=%d, 回落r36s=%d"
          % (stat.get("dtb", 0), stat.get("dir", 0), stat.get("no", 0)))
    # 顺带产出机器可读版, 供 devices.json / 教程引用
    OUT_JSON = r"F:\开源掌机教程\05-硬件与机型资料\arkos4clone_devices.json"
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump({
            "_meta": {
                "generated_by": "_工具脚本/dtb_panel_sweep.py",
                "method": "直接解析 .dtb 的 display-timings / panel 节点, 并 join 上游 console-detect 的行为表",
                "warning": "width-mm/height-mm 是厂商复制的默认值(XiFan 全系与 clone 全系同为 153x85),"
                           "不能用来推算寸数或 DPI;diag_in/dpi 两列仅存原始证据。"
                           "known=no 表示该 dtb 文件名不在 console-detect 的映射表里, 固件会按 r36s 默认配置。",
                "console_detect": "02-模拟器库/已clone仓库/R36S专用/console-detect/console_detect.c",
                "sources": [base for _s, base in SOURCES],
            },
            "count": len(uniq),
            "devices": [{k: r[k] for k in cols} for r in uniq],
        }, fh, ensure_ascii=False, indent=1)
    print(OUT_JSON)
    print(OUT_TSV)
    print(OUT_MD)
    for r in uniq:
        if "xf" in r["device"] or "45" in r["device"] or "panel" in r["device"].lower():
            print("  %-28s %-9s %dx%-5d %-6sMHz lanes=%-6s mm=%sx%s 寸=%s dpi=%s" % (
                r["device"], r["iface"], r["h"], r["v"], r["clk_mhz"], r["lanes"],
                r["w_mm"], r["h_mm"], r["diag_in"], r["dpi"]))


if __name__ == "__main__":
    main()
