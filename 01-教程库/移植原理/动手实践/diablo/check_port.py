#!/usr/bin/env python3
"""端口包自检：结构、port.json、ELF 架构/依赖/glibc、assets 引擎资源、数据边界。
本文件由 wolf3d/check_port.py 复制而来，改动：
  * 引擎是单文件 devilutionx.aarch64，界面资源是 assets/ 目录（不是 pk3）；
  * "包里不许有任何 .mpq"——DIABDAT.MPQ / spawn.mpq 都归玩家；
  * 启动器用 DevilutionX 自带的 SDL2 手柄支持，断言它**不**调用 gptokeyb；
  * 许可证是 Sustainable Use License，另加两份 LGPL 副本的断言。
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
BINARY = "devilutionx."
DATA_PLACEHOLDER = "PUT YOUR DIABLO DATA HERE.txt"
DATA_FILE_RE = re.compile(r"\.(mpq|sv|hsv)$", re.I)

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
        return {"bits": bits * 8, "machine": machine, "needed": [], "glibc": [], "interp": None}
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
    glibc = sorted({x.decode() for x in re.findall(rb"GLIBC_2\.\d+", blob)},
                   key=lambda s: tuple(map(int, s.split("_")[1].split("."))))
    return {"bits": 64, "machine": machine, "needed": needed,
            "glibc": glibc, "interp": interp}


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
        sh = [m for m in members if "/" not in m and m.endswith(".sh")]
        check("根目录有 .sh 启动脚本", len(sh) == 1, str(sh))
        check("根目录有同名文件夹", any(m.count("/") > 0 for m in members))
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
            check("items 里含 .sh", any(i.endswith(".sh") for i in items), str(items))
            root_names = {m.split("/")[0] for m in members}
            missing = [i.rstrip("/") for i in items if i.rstrip("/") not in root_names]
            check("items 与实际条目一致", not missing, "缺: %s" % missing)

            check("rtr=false（数据要用户自备）", attr.get("rtr") is False,
                  "rtr=%s" % attr.get("rtr"))
            inst = str(attr.get("inst", "")).lower()
            check("inst 说明要放 DIABDAT.MPQ / spawn.mpq",
                  "diabdat" in inst and "spawn" in inst, inst)

            shipped = [m for m in members if DATA_FILE_RE.search(Path(m).name)]
            check("包内没有任何 .mpq / 存档", not shipped, str(shipped))

            prefix = pj["items"][-1].rstrip("/") + "/"
            binary = next((m for m in members
                           if m.startswith(prefix) and Path(m).name.startswith(BINARY)), None)
            check("找到 devilutionx.<arch> 二进制", binary is not None, binary or "")
            elf = None
            if binary:
                elf = parse_elf(read_member(src, binary))
                check("主程序是 64 位 ELF", elf and elf["bits"] == 64)
                check("主程序 e_machine=183 (AArch64)", elf and elf["machine"] == 183,
                      "machine=%s" % (elf and elf["machine"]))
                check("主程序 NEEDED 含 libSDL2-2.0.so.0",
                      elf and "libSDL2-2.0.so.0" in elf["needed"], str(elf and elf["needed"]))
                check("主程序不依赖 libstdc++（libc++ 已静态链入）",
                      elf and "libstdc++.so.6" not in elf["needed"], str(elf and elf["needed"]))

            assets = [m for m in members if m.startswith(prefix + "assets/")]
            check("随包 assets/ 引擎界面资源", len(assets) >= 100, "%d 个文件" % len(assets))
            check("assets 含 ASSETS_VERSION",
                  any(m.endswith("/assets/ASSETS_VERSION") for m in members))
            check("assets 含 CLX 字体",
                  any(m.endswith(".clx") and "/fonts/" in m for m in assets))

            bundled_sdl = [m for m in members if Path(m).name.startswith("libSDL2-2.0.so")]
            check("包内不捆绑 libSDL2 本体（用 CFW 自带）", not bundled_sdl, str(bundled_sdl))

            allowed = {"libSDL2-2.0.so.0", "libc.so.6", "libm.so.6",
                       "libdl.so.2", "libpthread.so.0", "ld-linux-aarch64.so.1"}
            if elf:
                extra = [n for n in elf["needed"] if n not in allowed]
                check("依赖在允许清单内", not extra, str(extra))
                maxg = elf["glibc"][-1] if elf["glibc"] else ""
                min_glibc = attr.get("min_glibc", "")
                check("min_glibc 覆盖二进制需求",
                      maxg and min_glibc and glibc_tuple(min_glibc) >= glibc_tuple(maxg.split("_")[1]),
                      "最高 %s / 声明 %s" % (maxg, min_glibc))

            check("有数据占位说明 %s" % DATA_PLACEHOLDER,
                  any(Path(m).name == DATA_PLACEHOLDER for m in members))
            check("没有 gptk（手柄走引擎自带支持）",
                  not any(m.endswith(".gptk") for m in members))
            check("有截图", any(m.endswith("screenshot.png") for m in members))
            gi = next((m for m in members if m.endswith("gameinfo.xml")), None)
            if gi:
                try:
                    ET.fromstring(read_member(src, gi))
                    check("gameinfo.xml 可解析", True)
                except ET.ParseError as e:
                    check("gameinfo.xml 可解析", False, str(e))
            else:
                check("有 gameinfo.xml", False)
            lic = [Path(m).name for m in members if "/licenses/" in m]
            check("含 DevilutionX 许可原文", "DevilutionX.txt" in lic, str(lic[:4]))
            check("含两份 LGPL 副本（SDL_audiolib / libsmackerdec）",
                  sum(1 for n in lic if "LGPL" in n) >= 2, str(lic))
            check("含 libpng/zlib/bzip2 许可副本",
                  {"libpng.txt", "zlib.txt", "bzip2.txt"} <= set(lic), str(sorted(lic)))

            launcher = next((m for m in members if "/" not in m and m.endswith(".sh")), "")
            if launcher:
                body = read_member(src, launcher).decode("utf-8", "replace")
                check("启动脚本把 libs.<arch> 加进 LD_LIBRARY_PATH",
                      "libs.${DEVICE_ARCH}" in body and "LD_LIBRARY_PATH" in body)
                check("启动脚本钉住 --data-dir/--save-dir/--config-dir",
                      all(x in body for x in ("--data-dir", "--save-dir", "--config-dir")))
                check("启动脚本导出 SDL_GAMECONTROLLERCONFIG",
                      "SDL_GAMECONTROLLERCONFIG" in body)
                check("启动脚本不抢手柄（不调用 GPTOKEYB）", "GPTOKEYB" not in body)
                check("启动脚本在缺数据时给出提示并退出",
                      "spawn.mpq" in body and "exit 1" in body)
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
