#!/usr/bin/env python3
"""端口包自检：结构、port.json、ELF 架构/依赖/glibc、随包开源库、数据边界。
本文件由 quake3/check_port.py 复制而来，改动：
  * 没有渲染器/goal 特定断言，引擎是单文件 ecwolf.aarch64；
  * 新增"包内不许出现任何 id 商业数据文件（*.WL1/*.WL6/*.SOD 及 VSWAP/GAMEMAPS 等）"；
  * 新增 ecwolf.pk3 只能装引擎文本定义、不许夹带 id 美术的断言；
  * 新增 SDL2_mixer / SDL2_net 由包自带、libSDL2 本体由 CFW 提供 的断言。
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
BINARY = "ecwolf."
PK3 = "ecwolf.pk3"
DATA_PLACEHOLDER = "PUT YOUR WOLF3D DATA HERE.txt"
# id 的数据文件：分享版 WL1、正式版 WL6、资料片 SOD，以及原版拆出来的裸 lump
DATA_FILE_RE = re.compile(r"(\.(wl1|wl6|sod|wad)$)|^(vswap|gamemaps|maphead|audiot|"
                          r"audiohed|vgagraph|vgahead|vgadict)\.", re.I)

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


def has_export(blob, symbol):
    """在 .dynsym 里找 symbol 且 st_shndx != SHN_UNDEF（即真的是本库定义的导出）。"""
    if blob[:4] != b"\x7fELF" or blob[4] != 2:
        return False
    phoff = struct.unpack("<Q", blob[0x20:0x28])[0]
    phentsize = struct.unpack("<H", blob[0x36:0x38])[0]
    phnum = struct.unpack("<H", blob[0x38:0x3a])[0]
    loads, dyn = [], None
    for i in range(phnum):
        o = phoff + i * phentsize
        t, _fl, off, va, _pa, fs, _ms, _al = struct.unpack("<IIQQQQQQ", blob[o:o + 56])
        if t == 1:
            loads.append((off, va, fs))
        elif t == 2:
            dyn = (off, fs)
    if not dyn:
        return False
    tags = {}
    for j in range(0, dyn[1], 16):
        tag, val = struct.unpack("<qQ", blob[dyn[0] + j:dyn[0] + j + 16])
        if tag == 0:
            break
        tags[tag] = val

    def v2o(v):
        for off, va, fs in loads:
            if va <= v < va + fs:
                return off + (v - va)
        return None

    sym_off = v2o(tags.get(6, 0))
    str_off = v2o(tags.get(5, 0))
    if sym_off is None or str_off is None or str_off <= sym_off:
        return False
    count = (str_off - sym_off) // 24
    for n in range(count):
        e = sym_off + n * 24
        st_name, _info, _other, st_shndx, _val, _size = struct.unpack(
            "<IBBHQQ", blob[e:e + 24])
        if st_name == 0:
            continue
        s = blob[str_off + st_name:blob.find(0, str_off + st_name)]
        if s.decode("latin1") == symbol and st_shndx != 0:
            return True
    return False


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

            # 数据边界：ECWolf 官方立场就是"引擎不带游戏数据"，本包同样只发引擎
            check("rtr=false（数据要用户自备）", attr.get("rtr") is False,
                  "rtr=%s" % attr.get("rtr"))
            inst = str(attr.get("inst", "")).lower()
            check("inst 说明要放 WL1/WL6/SOD",
                  ("wl1" in inst or "wl6" in inst) and "wolf3d/" in inst, inst)
            shipped = [m for m in members if DATA_FILE_RE.search(Path(m).name)]
            check("包内没有任何 id 商业数据文件", not shipped, str(shipped))

            prefix = pj["items"][-1].rstrip("/") + "/"
            binary = next((m for m in members
                           if m.startswith(prefix)
                           and Path(m).name.startswith(BINARY)
                           and not Path(m).name.endswith(".pk3")), None)
            check("找到 ecwolf.<arch> 二进制", binary is not None, binary or "")

            elfs = {}
            if binary:
                elfs[binary] = parse_elf(read_member(src, binary))
                elf = elfs[binary]
                check("主程序是 64 位 ELF", elf and elf["bits"] == 64)
                check("主程序 e_machine=183 (AArch64)", elf and elf["machine"] == 183,
                      "machine=%s" % (elf and elf["machine"]))
                for lib in ("libSDL2-2.0.so.0", "libSDL2_mixer-2.0.so.0",
                            "libSDL2_net-2.0.so.0"):
                    check("主程序 NEEDED 含 %s" % lib,
                          elf and lib in elf["needed"], str(elf and elf["needed"]))

            # ecwolf.pk3 是 wadsrc 生成的引擎资源，不是 id 的 VSWAP/VGAGRAPH
            pk3 = next((m for m in members if m.startswith(prefix) and m.endswith("/" + PK3)), None)
            check("随包 %s" % PK3, pk3 is not None, pk3 or "")
            if pk3:
                import io
                blob = read_member(src, pk3)
                z = zipfile.ZipFile(io.BytesIO(blob))
                names = z.namelist()
                check("%s 是合法 zip 且非空" % PK3, len(names) > 50, "%d 项" % len(names))
                check("%s 含 wolf 角色定义" % PK3,
                      any(n.lower().startswith("actors/wolf/") for n in names))
                check("%s 不含 id 美术/地图 lump" % PK3,
                      not [n for n in names if DATA_FILE_RE.search(Path(n).name)],
                      str([n for n in names if DATA_FILE_RE.search(Path(n).name)]))

            # SDL2 本体由 CFW 提供；捆绑反而可能和设备的 SDL2 打架
            bundled_sdl = [m for m in members if Path(m).name.startswith("libSDL2-2.0.so")]
            check("包内不捆绑 libSDL2 本体（用 CFW 自带）", not bundled_sdl, str(bundled_sdl))

            for lib, sym in (("libSDL2_mixer-2.0.so.0", "Mix_OpenAudio"),
                             ("libSDL2_net-2.0.so.0", "SDLNet_Init")):
                lp = next((m for m in members if Path(m).name == lib), None)
                check("%s 随包" % lib, lp is not None, lp or "")
                if lp:
                    blob = read_member(src, lp)
                    e = elfs[lp] = parse_elf(blob)
                    check("%s 是 AArch64 共享库" % lib,
                          e and e["machine"] == 183, "machine=%s" % (e and e["machine"]))
                    check("%s 导出 %s" % (lib, sym), has_export(blob, sym),
                          "%d 字节" % len(blob))

            allowed = {"libSDL2-2.0.so.0", "libSDL2_mixer-2.0.so.0",
                       "libSDL2_net-2.0.so.0", "libc.so.6", "libm.so.6",
                       "libdl.so.2", "libpthread.so.0", "ld-linux-aarch64.so.1"}
            for m, e in sorted(elfs.items()):
                extra = [n for n in e["needed"] if n not in allowed]
                check("%s 依赖在允许清单内" % Path(m).name, not extra, str(extra))

            maxg = ""
            for e in elfs.values():
                if e and e["glibc"] and (not maxg or glibc_tuple(e["glibc"][-1].split("_")[1])
                                         > glibc_tuple(maxg.split("_")[1])):
                    maxg = e["glibc"][-1]
            min_glibc = attr.get("min_glibc", "")
            check("min_glibc 覆盖全部二进制需求",
                  maxg and min_glibc and glibc_tuple(min_glibc) >= glibc_tuple(maxg.split("_")[1]),
                  "最高 %s / 声明 %s" % (maxg, min_glibc))

            check("有数据占位说明 %s" % DATA_PLACEHOLDER,
                  any(Path(m).name == DATA_PLACEHOLDER for m in members))
            check("有 gptk 手柄映射", any(m.endswith(".gptk") for m in members))
            check("有截图", any(m.endswith("screenshot.png") for m in members))
            gi = next((m for m in members if m.endswith("gameinfo.xml")), None)
            if gi:
                try:
                    ET.fromstring(read_member(src, gi))
                    check("gameinfo.xml 可解析", True)
                except ET.ParseError as e:
                    check("gameinfo.xml 可解析", False, str(e))
            check("含 GPL-2.0 副本", any("COPYING" in Path(m).name for m in members))
            check("含 SDL 库许可副本",
                  sum(1 for m in members if Path(m).name.startswith("LICENSE.")) >= 2)
            launcher = next((m for m in members if "/" not in m and m.endswith(".sh")), "")
            if launcher:
                body = read_member(src, launcher).decode("utf-8", "replace")
                check("启动脚本把 libs.<arch> 加进 LD_LIBRARY_PATH",
                      "libs.${DEVICE_ARCH}" in body and "LD_LIBRARY_PATH" in body)
                check("启动脚本钉住 --config/--savedir", "--config" in body and "--savedir" in body)
                check("启动脚本按 640x480 全屏启动",
                      "--res 640 480" in body and "--fullscreen" in body)
                check("启动脚本关掉 SDL 手柄（改用 gptk）", "--joystick -1" in body)
                check("启动脚本在缺数据时给出提示并退出",
                      "WL6" in body and "exit 1" in body)
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
