#!/usr/bin/env python3
"""OpenTTD 端口包自检：结构、port.json、ELF 架构/依赖/glibc、随包 baseset、许可、启动脚本。

和 cnc/check_port.py 的差别：
  * 一个游戏、一个二进制，数据是**随包**的自由素材（OpenGFX/OpenSFX/OpenMSX），rtr=true；
  * 手柄靠 PortMaster 自带的 gptokeyb + 包内 openttd.gptk，所以这里反而**要**查 .gptk；
  * 要保证包里没有原版 TTD 的商业素材（sample.cat / trg*.grf / *.gm）。

用法: python check_port.py <package_dir 或 .zip>
"""
import json
import re
import struct
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

TOP_KEYS = {"version", "name", "items", "items_opt", "attr"}
ATTR_KEYS = {"title", "desc", "inst", "genres", "porter", "image", "rtr",
             "exp", "runtime", "min_glibc", "reqs", "arch"}
ALLOWED_NEEDED = {"libSDL2-2.0.so.0", "libc.so.6", "libm.so.6",
                  "libdl.so.2", "libpthread.so.0", "ld-linux-aarch64.so.1"}
# 原版 Transport Tycoon Deluxe 的商业素材特征名（小写）
COMMERCIAL = re.compile(r"(^|/)(sample\.cat|trg[0-9a-z]*r?\.grf|gm/.+\.gm|[^/]+\.gm)$", re.I)

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def read_member(src, name):
    if isinstance(src, zipfile.ZipFile):
        return src.read(name)
    return (Path(src) / name).read_bytes()


def list_members(src):
    if isinstance(src, zipfile.ZipFile):
        return src.namelist()
    return [str(p.relative_to(src)).replace("\\", "/")
            for p in Path(src).rglob("*") if p.is_file()]


def parse_elf(blob):
    if blob[:4] != b"\x7fELF":
        return None
    bits = blob[4]
    machine = struct.unpack("<H", blob[18:20])[0]
    if bits != 2:
        return {"bits": bits * 8, "machine": machine, "needed": [], "glibc": [],
                "interp": None, "rpath": []}
    phoff = struct.unpack("<Q", blob[0x20:0x28])[0]
    phentsize = struct.unpack("<H", blob[0x36:0x38])[0]
    phnum = struct.unpack("<H", blob[0x38:0x3a])[0]
    loads, dyn, interp = [], None, None
    for i in range(phnum):
        o = phoff + i * phentsize
        t, _fl, off, va, _pa, fs, _ms, _al = struct.unpack("<IIQQQQQQ", blob[o:o + 56])
        if t == 1:
            loads.append((off, va, fs))
        elif t == 2:
            dyn = (off, fs)
        elif t == 3:
            interp = blob[off:off + fs].split(b"\0")[0].decode()
    needed = []
    rpath = []
    if dyn:
        ents = []
        for j in range(0, dyn[1], 16):
            tag, val = struct.unpack("<qQ", blob[dyn[0] + j:dyn[0] + j + 16])
            ents.append((tag, val))
            if tag == 0:
                break
        strtab = next(v for t, v in ents if t == 5)

        def v2o(v):
            for off, va, fs in loads:
                if va <= v < va + fs:
                    return off + (v - va)
            raise ValueError("vaddr not mapped")

        base = v2o(strtab)
        for t, v in ents:
            if t == 1:
                s = base + v
                needed.append(blob[s:blob.index(b"\0", s)].decode())
            elif t in (15, 29):
                s = base + v
                rpath.extend(blob[s:blob.index(b"\0", s)].decode().split(":"))
    glibc = sorted({x.decode() for x in re.findall(rb"GLIBC_2\.\d+", blob)},
                   key=lambda s: tuple(map(int, s.split("_")[1].split("."))))
    return {"bits": 64, "machine": machine, "needed": needed,
            "glibc": glibc, "interp": interp, "rpath": rpath}


def glibc_tuple(v):
    return tuple(map(int, v.split(".")))


def main(target):
    p = Path(target)
    if p.suffix == ".zip":
        src = zipfile.ZipFile(p)
        members = list_members(src)
        close = src.close
    else:
        src = p
        members = list_members(src)
        close = lambda: None

    try:
        root_names = {m.split("/")[0] for m in members}
        scripts = [m for m in members if "/" not in m and m.endswith(".sh")]
        check("根目录有 OpenTTD.sh", scripts == ["OpenTTD.sh"], str(scripts))
        check("根目录有 openttd/ 文件夹",
              "openttd" in root_names or any(m.startswith("openttd/") for m in members))

        pj_name = next((m for m in members if m.endswith("/port.json")), None)
        check("有 port.json", pj_name is not None, pj_name or "")
        if pj_name:
            pj = json.loads(read_member(src, pj_name))
            check("port.json 顶层 5 键", TOP_KEYS <= pj.keys(),
                  "缺: %s" % sorted(TOP_KEYS - pj.keys()))
            attr = pj.get("attr", {})
            check("attr 12 键", ATTR_KEYS <= attr.keys(),
                  "缺: %s" % sorted(ATTR_KEYS - attr.keys()))
            items = pj.get("items", [])
            missing = [i.rstrip("/") for i in items if i.rstrip("/") not in root_names]
            check("items 与实际条目一致", not missing, "缺: %s" % missing)

            check("rtr=true（素材随包，开箱即玩）", attr.get("rtr") is True,
                  "rtr=%s" % attr.get("rtr"))
            inst = str(attr.get("inst", "")).upper()
            check("inst 说明素材已随包（OpenGFX/OpenSFX/OpenMSX）",
                  all(k in inst for k in ("OPENGFX", "OPENSFX", "OPENMSX")), inst[:100])

            shipped = [m for m in members if COMMERCIAL.search(m)]
            check("包内没有原版 TTD 商业素材", not shipped, str(shipped[:4]))

            prefix = "openttd/"
            min_glibc = attr.get("min_glibc", "")
            check("min_glibc 已声明", bool(min_glibc), min_glibc)

            name = next((m for m in members
                         if m.startswith(prefix) and Path(m).name.startswith("openttd.aarch64")), None)
            check("找到 openttd.aarch64 二进制", name is not None, name or "")
            if name:
                blob = read_member(src, name)
                elf = parse_elf(blob)
                check("openttd 是 64 位 ELF", elf and elf["bits"] == 64)
                check("openttd e_machine=183 (AArch64)", elf and elf["machine"] == 183,
                      "machine=%s" % (elf and elf["machine"]))
                check("openttd NEEDED 含 libSDL2-2.0.so.0（用 CFW 自带）",
                      elf and "libSDL2-2.0.so.0" in elf["needed"], str(elf and elf["needed"]))
                check("openttd 不依赖 libstdc++（libc++ 已静态链入）",
                      elf and not any("libstdc++" in n for n in elf["needed"]),
                      str(elf and elf["needed"]))
                if elf:
                    extra = [n for n in elf["needed"] if n not in ALLOWED_NEEDED]
                    check("openttd 依赖在允许清单内", not extra, str(extra))
                    maxg = elf["glibc"][-1] if elf["glibc"] else ""
                    check("openttd 的 glibc 需求被 min_glibc 覆盖",
                          bool(maxg) and bool(min_glibc)
                          and glibc_tuple(min_glibc) >= glibc_tuple(maxg.split("_")[1]),
                          "最高 %s / 声明 %s" % (maxg, min_glibc))
                    check("openttd 没有构建期 RPATH", not elf["rpath"], str(elf["rpath"]))
                check("openttd 里没有构建机路径", b"_scratch" not in blob and b"F:/" not in blob)

            bundled_sdl = [m for m in members if Path(m).name.startswith("libSDL2-2.0.so")]
            check("包内不捆绑 libSDL2 本体（用 CFW 自带）", not bundled_sdl, str(bundled_sdl))

            # ---- 随包的 baseset ----
            gfx = [m for m in members if "/baseset/opengfx-" in m and m.endswith("opengfx.obg")]
            sfx = [m for m in members if "/baseset/opensfx-" in m and m.endswith("opensfx.obs")]
            msx = [m for m in members if "/baseset/openmsx-" in m and m.endswith(".mid")]
            check("随包 OpenGFX（opengfx.obg）", len(gfx) == 1, str(gfx))
            check("随包 OpenSFX（opensfx.obs）", len(sfx) == 1, str(sfx))
            check("随包 OpenMSX（*.mid ≥ 30 首）", len(msx) >= 30, "%d 首" % len(msx))

            # ---- 随包语言 ----
            # 没装 lang/*.lng 的话引擎会直接报 "No available language packs" 退出，一个都进不去
            lng = [m for m in members if m.startswith(prefix + "lang/") and m.endswith(".lng")]
            names = {Path(m).name for m in lng}
            check("随包 lang/ 至少有英文和简体中文",
                  {"english.lng", "simplified_chinese.lng"} <= names, "%d 个: %s" % (len(lng), sorted(names)))

            # ---- 随包文本 ----
            shot = next((m for m in members if Path(m).name == "screenshot.png"), None)
            check("有截图", shot is not None, shot or "")
            if shot:
                head = read_member(src, shot)[:24]
                ok = head[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", head[16:24]) >= (320, 240)
                check("截图是真 PNG 且不小于 320x240", ok, str(head[:8]))
            gi = next((m for m in members if m.endswith("gameinfo.xml")), None)
            if gi:
                try:
                    root = ET.fromstring(read_member(src, gi))
                    check("gameinfo.xml 可解析", True)
                    games = root.findall("game")
                    check("gameinfo.xml 里一条游戏", len(games) == 1, "%d 条" % len(games))
                    paths = [g.findtext("path", "") for g in games]
                    check("gameinfo.xml 指向 OpenTTD.sh",
                          all(any(x.endswith(s) for s in scripts) for x in paths), str(paths))
                except ET.ParseError as e:
                    check("gameinfo.xml 可解析", False, str(e))
            else:
                check("有 gameinfo.xml", False)

            lic = {Path(m).name for m in members if "/licenses/" in m}
            for f in ("OpenTTD-GPL-2.0.txt", "OpenGFX.txt", "OpenSFX.txt",
                      "OpenMSX.txt", "SDL2.txt"):
                check("含许可原文 %s" % f, f in lic, str(sorted(lic)))

            # ---- 手柄映射 ----
            gptk = next((m for m in members if m.endswith(".gptk")), None)
            check("有 openttd.gptk", gptk is not None and Path(gptk).name == "openttd.gptk", gptk or "")
            if gptk:
                body = read_member(src, gptk).decode("utf-8", "replace")
                check("gptk 用左摇杆当鼠标", "left_analog_up = mouse_movement_up" in body)
                check("gptk 有鼠标左右键与慢速", "mouse_left" in body and "mouse_slow" in body)

            # ---- 启动脚本 ----
            for s in scripts:
                body = read_member(src, s).decode("utf-8", "replace")
                tag = Path(s).stem
                check("%s 设 HOME 进包目录（便携存档）" % tag, 'export HOME="$GAMESUB"' in body)
                check("%s 导出 SDL_GAMECONTROLLERCONFIG" % tag,
                      'export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"' in body)
                check("%s 首次启动写全屏 640x480 配置" % tag,
                      "fullscreen = true" in body and "resolution = 640,480" in body)
                check("%s 用 gptokeyb + 包内 .gptk" % tag,
                      "GPTOKEYB" in body and "openttd.gptk" in body)
                check("%s chmod +x 后再跑" % tag, "$ESUDO chmod +x" in body)
                check("%s 有 pm_platform_helper / pm_finish" % tag,
                      "pm_platform_helper" in body and "pm_finish" in body)
                check("%s 用 SDL 视频/音频驱动" % tag, "-v sdl" in body and "-s sdl" in body)
                check("%s 退出后杀掉 gptokeyb" % tag, "kill -9 $GPID" in body)
    finally:
        close()

    bad = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name,
                            ("  <- " + detail) if detail else ""))
    print("\n%d/%d 通过" % (len(results) - len(bad), len(results)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "package"))
