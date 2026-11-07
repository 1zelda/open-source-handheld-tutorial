#!/usr/bin/env python3
"""端口包自检：结构、port.json、ELF 架构/依赖/glibc、渲染器与 game.so、数据边界。
本文件由 quake/check_port.py 复制而来，改动：二进制前缀、三个渲染器、baseq2/game.so，
以及"必须 rtr=false 且包内不许带任何商业 pak"这条数据边界断言。
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
BINARY = "quake2."
RENDERERS = ["ref_gles1.so", "ref_gl1.so", "ref_soft.so"]
GAME_MODULE = "baseq2/game.so"
PAK_PLACEHOLDER = "baseq2/PUT YOUR PAK FILES HERE.txt"

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
    """在 .dynsym 里找 symbol 且 st_shndx != SHN_UNDEF（即真的是本库定义的导出）。
    没有这条断言时，一个 1.7 KB、什么都没导出的空 .so 也能通过全部 ELF 检查（踩过）。
    """
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

    sym_off = v2o(tags.get(6, 0))      # DT_SYMTAB
    str_off = v2o(tags.get(5, 0))      # DT_STRTAB
    if sym_off is None or str_off is None or str_off <= sym_off:
        return False
    # 链接器把 .dynsym 紧挨着 .dynstr 放，用两者距离推符号数
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

            # 数据边界：本端口是 needs_data，必须 rtr=false 且包里不许有商业 pak
            check("rtr=false（数据要用户自备）", attr.get("rtr") is False,
                  "rtr=%s" % attr.get("rtr"))
            check("inst 指明放进 baseq2",
                  "baseq2" in str(attr.get("inst", "")).lower(),
                  str(attr.get("inst")))
            shipped_paks = [m for m in members
                            if re.search(r"baseq2/pak\d+\.pak$", m, re.I)]
            check("包内没有任何 baseq2/pak*.pak", not shipped_paks, str(shipped_paks))

            prefix = pj["items"][-1].rstrip("/") + "/"
            binary = next((m for m in members
                           if m.startswith(prefix)
                           and Path(m).name.startswith(BINARY)), None)
            check("找到 quake2.<arch> 二进制", binary is not None, binary or "")

            elfs = {}
            if binary:
                elfs[binary] = parse_elf(read_member(src, binary))
                elf = elfs[binary]
                check("主程序是 64 位 ELF", elf and elf["bits"] == 64)
                check("主程序 e_machine=183 (AArch64)", elf and elf["machine"] == 183,
                      "machine=%s" % (elf and elf["machine"]))
                check("主程序 NEEDED 含 libSDL2-2.0.so.0",
                      elf and "libSDL2-2.0.so.0" in elf["needed"],
                      str(elf and elf["needed"]))

            for r in RENDERERS:
                rp = next((m for m in members
                           if m == prefix + r or m.endswith("/" + r)), None)
                check("渲染器 %s 随包" % r, rp is not None, rp or "")
                if rp:
                    blob = read_member(src, rp)
                    e = elfs[rp] = parse_elf(blob)
                    check("%s 是 AArch64 共享库" % r,
                          e and e["machine"] == 183, "machine=%s" % (e and e["machine"]))
                    check("%s 导出 GetRefAPI" % r, has_export(blob, "GetRefAPI"),
                          "%d 字节" % len(blob))

            gm = next((m for m in members if m.endswith("/" + GAME_MODULE)), None)
            check("baseq2/game.so 随包", gm is not None, gm or "")
            if gm:
                blob = read_member(src, gm)
                e = elfs[gm] = parse_elf(blob)
                check("game.so 是 AArch64 共享库",
                      e and e["machine"] == 183, "machine=%s" % (e and e["machine"]))
                check("game.so 导出 GetGameAPI", has_export(blob, "GetGameAPI"),
                      "%d 字节" % len(blob))

            # 三个渲染器都通过 SDL_GL_GetProcAddress 取 GL 函数，理论上只依赖 SDL2/libc/libm；
            # 一旦多出别的 so（比如桌面 libGL），说明链接方式变了，设备上可能起不来
            allowed = {"libSDL2-2.0.so.0", "libc.so.6", "libm.so.6", "libdl.so.2",
                       "libpthread.so.0", "ld-linux-aarch64.so.1"}
            for m, e in sorted(elfs.items()):
                extra = [n for n in e["needed"] if n not in allowed]
                check("%s 只依赖 SDL2/libc/libm" % Path(m).name, not extra, str(extra))

            maxg = ""
            for e in elfs.values():
                if e and e["glibc"] and (not maxg or glibc_tuple(e["glibc"][-1].split("_")[1])
                                         > glibc_tuple(maxg.split("_")[1])):
                    maxg = e["glibc"][-1]
            min_glibc = attr.get("min_glibc", "")
            check("min_glibc 覆盖全部二进制需求",
                  maxg and min_glibc and glibc_tuple(min_glibc) >= glibc_tuple(maxg.split("_")[1]),
                  "最高 %s / 声明 %s" % (maxg, min_glibc))

            check("有数据占位说明 %s" % PAK_PLACEHOLDER,
                  any(m.endswith(PAK_PLACEHOLDER) for m in members))
            check("有 gptk 手柄映射", any(m.endswith(".gptk") for m in members))
            check("有截图", any(m.endswith("screenshot.png") for m in members))
            gi = next((m for m in members if m.endswith("gameinfo.xml")), None)
            if gi:
                try:
                    ET.fromstring(read_member(src, gi))
                    check("gameinfo.xml 可解析", True)
                except ET.ParseError as e:
                    check("gameinfo.xml 可解析", False, str(e))
            check("含许可证副本", any("COPYING" in Path(m).name for m in members))
            launcher = next((m for m in members if "/" not in m and m.endswith(".sh")), "")
            if launcher:
                body = read_member(src, launcher).decode("utf-8", "replace")
                check("启动脚本用 -datadir 指到游戏目录", "-datadir" in body)
                check("启动脚本设置渲染器", "vid_renderer" in body)
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
