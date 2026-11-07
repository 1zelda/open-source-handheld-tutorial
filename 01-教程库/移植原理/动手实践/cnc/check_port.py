#!/usr/bin/env python3
"""端口包自检：结构、port.json、两个 ELF 的架构/依赖/glibc、商业数据边界、许可、启动脚本。

和 diablo/check_port.py 的差别：
  * 一个包里有两个游戏（td / ra），两套启动脚本和两个二进制都要查；
  * OpenAL 是包内自带的（libs.aarch64/libopenal.so.1），SDL2 反而不能带；
  * 包内不许有任何 Westwood 的容器文件（.MIX/.ISO/.VQA/.AUD/...）——数据归玩家。

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
DATA_FILE_RE = re.compile(r"\.(mix|iso|vqa|aud|wsa|pcx|cps|shp|tmp|bin|img)$", re.I)
ALLOWED_NEEDED = {"libSDL2-2.0.so.0", "libopenal.so.1", "libc.so.6", "libm.so.6",
                  "libdl.so.2", "libpthread.so.0", "ld-linux-aarch64.so.1"}

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
        check("根目录有两个 .sh 启动脚本", len(scripts) == 2, str(scripts))
        check("根目录有 cnc/ 文件夹", "cnc" in root_names or any(m.startswith("cnc/") for m in members))

        pj_name = next((m for m in members if m.endswith("/port.json")), None)
        check("有 port.json", pj_name is not None, pj_name or "")
        if pj_name:
            pj = json.loads(read_member(src, pj_name))
            check("port.json 顶层 5 键", TOP_KEYS <= pj.keys(),
                  "缺: %s" % sorted(TOP_KEYS - pj.keys()))
            attr = pj.get("attr", {})
            check("attr 12 键", ATTR_KEYS <= attr.keys(),
                  "缺: %s" % sorted(ATTR_KEYS - pj.keys()))
            items = pj.get("items", [])
            check("items 里含两个 .sh", sum(1 for i in items if i.endswith(".sh")) == 2, str(items))
            missing = [i.rstrip("/") for i in items if i.rstrip("/") not in root_names]
            check("items 与实际条目一致", not missing, "缺: %s" % missing)

            check("rtr=false（数据要用户自备）", attr.get("rtr") is False,
                  "rtr=%s" % attr.get("rtr"))
            inst = str(attr.get("inst", "")).upper()
            check("inst 说明要放 CONQUER.MIX 和 REDALERT.MIX",
                  "CONQUER.MIX" in inst and "REDALERT.MIX" in inst, inst[:80])

            shipped = [m for m in members if DATA_FILE_RE.search(Path(m).name)]
            check("包内没有任何商业游戏数据", not shipped, str(shipped[:4]))

            prefix = pj["items"][-1].rstrip("/") + "/"
            min_glibc = attr.get("min_glibc", "")
            check("min_glibc 已声明", bool(min_glibc), min_glibc)

            # ---- 两个主程序 ----
            for sub, binary in (("td/vanillatd", "vanillatd"), ("ra/vanillara", "vanillara")):
                name = next((m for m in members
                             if m.startswith(prefix + sub) and Path(m).name.startswith(binary)), None)
                check("找到 %s 二进制" % binary, name is not None, name or "")
                if not name:
                    continue
                elf = parse_elf(read_member(src, name))
                check("%s 是 64 位 ELF" % binary, elf and elf["bits"] == 64)
                check("%s e_machine=183 (AArch64)" % binary, elf and elf["machine"] == 183,
                      "machine=%s" % (elf and elf["machine"]))
                check("%s NEEDED 含 libSDL2-2.0.so.0（用 CFW 自带）" % binary,
                      elf and "libSDL2-2.0.so.0" in elf["needed"], str(elf and elf["needed"]))
                check("%s NEEDED 含 libopenal.so.1（包内自带）" % binary,
                      elf and "libopenal.so.1" in elf["needed"], str(elf and elf["needed"]))
                check("%s 不依赖 libstdc++（libc++ 已静态链入）" % binary,
                      elf and not any("libstdc++" in n for n in elf["needed"]),
                      str(elf and elf["needed"]))
                if elf:
                    extra = [n for n in elf["needed"] if n not in ALLOWED_NEEDED]
                    check("%s 依赖在允许清单内" % binary, not extra, str(extra))
                    maxg = elf["glibc"][-1] if elf["glibc"] else ""
                    check("%s 的 glibc 需求被 min_glibc 覆盖" % binary,
                          bool(maxg) and bool(min_glibc)
                          and glibc_tuple(min_glibc) >= glibc_tuple(maxg.split("_")[1]),
                          "最高 %s / 声明 %s" % (maxg, min_glibc))
                    check("%s 没有构建期 RPATH" % binary, not elf["rpath"], str(elf["rpath"]))

            # ---- 随包的 OpenAL ----
            oal = next((m for m in members if m.startswith(prefix + "libs.") and "libopenal.so.1" == Path(m).name), None)
            check("随包 libs.<arch>/libopenal.so.1", oal is not None, oal or "")
            if oal:
                elf = parse_elf(read_member(src, oal))
                check("libopenal 是 AArch64 动态库", elf and elf["bits"] == 64 and elf["machine"] == 183)
                if elf:
                    extra = [n for n in elf["needed"] if n not in ALLOWED_NEEDED]
                    check("libopenal 依赖在允许清单内", not extra, str(extra))
                    maxg = elf["glibc"][-1] if elf["glibc"] else ""
                    check("libopenal 的 glibc 需求被 min_glibc 覆盖",
                          bool(maxg) and bool(min_glibc)
                          and glibc_tuple(min_glibc) >= glibc_tuple(maxg.split("_")[1]),
                          "最高 %s / 声明 %s" % (maxg, min_glibc))
                    check("libopenal 没有构建期 RPATH", not elf["rpath"], str(elf["rpath"]))

            bundled_sdl = [m for m in members if Path(m).name.startswith("libSDL2-2.0.so")]
            check("包内不捆绑 libSDL2 本体（用 CFW 自带）", not bundled_sdl, str(bundled_sdl))
            check("没有 gptk（手柄走引擎自带支持）",
                  not any(m.endswith(".gptk") for m in members))

            # ---- 随包文本 ----
            check("有截图", any(m.endswith("screenshot.png") for m in members))
            gi = next((m for m in members if m.endswith("gameinfo.xml")), None)
            if gi:
                try:
                    root = ET.fromstring(read_member(src, gi))
                    check("gameinfo.xml 可解析", True)
                    games = root.findall("game")
                    check("gameinfo.xml 里两条游戏", len(games) == 2, "%d 条" % len(games))
                    paths = [g.findtext("path", "") for g in games]
                    check("gameinfo.xml 指向两个启动脚本",
                          all(any(x.endswith(s) for s in scripts) for x in paths), str(paths))
                except ET.ParseError as e:
                    check("gameinfo.xml 可解析", False, str(e))
            else:
                check("有 gameinfo.xml", False)

            lic = [Path(m).name for m in members if "/licenses/" in m]
            check("含 Vanilla Conquer 许可原文", "Vanilla-Conquer-GPL-3.0.txt" in lic, str(lic))
            check("含 OpenAL Soft LGPL 原文", "OpenAL-Soft-LGPL-2.0.txt" in lic, str(lic))
            check("含 SDL2 zlib 许可原文", "SDL2.txt" in lic, str(lic))

            for sub, marker in (("td/", "C&C"), ("ra/", "RED ALERT")):
                check("%s 有数据放置说明" % sub,
                      any(Path(m).name.startswith("PUT YOUR") and marker in Path(m).name.upper()
                          for m in members if m.startswith(prefix + sub)))

            # ---- 启动脚本 ----
            for s in scripts:
                body = read_member(src, s).decode("utf-8", "replace")
                tag = Path(s).stem
                check("%s 把 libs.<arch> 加进 LD_LIBRARY_PATH" % tag,
                      "libs.${DEVICE_ARCH}" in body and "LD_LIBRARY_PATH" in body)
                check("%s 导出 SDL_GAMECONTROLLERCONFIG" % tag, "SDL_GAMECONTROLLERCONFIG" in body)
                check("%s 缺数据时提示并退出" % tag, "sleep 6" in body and "exit 1" in body)
                check("%s chmod +x 后再跑" % tag, "$ESUDO chmod +x" in body)
                check("%s 有 pm_platform_helper / pm_finish" % tag,
                      "pm_platform_helper" in body and "pm_finish" in body)
                want = "vanillatd" if "Tiberian" in s else "vanillara"
                other = "vanillara" if want == "vanillatd" else "vanillatd"
                check("%s 只启动 %s" % (tag, want), want in body and other not in body)
                check("%s 不抢手柄（不调用 GPTOKEYB）" % tag, "GPTOKEYB" not in body)
                check("%s 默认写 ControllerEnabled=yes" % tag, "ControllerEnabled=yes" in body)
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
