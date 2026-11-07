#!/usr/bin/env python3
"""端口包自检：结构、port.json、ELF 架构/依赖/glibc、数据完整性。
本文件由 doom/check_port.py 复制而来，改了二进制前缀、必需数据、引擎 pak 三处常量。
用法: python check_port.py <package_dir 或 .zip>
"""
import json
import struct
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

TOP_KEYS = {"version", "name", "items", "items_opt", "attr"}
ATTR_KEYS = {"title", "desc", "inst", "genres", "porter", "image", "rtr",
             "exp", "runtime", "min_glibc", "reqs", "arch"}
REQUIRED_DATA = ["id1/pak0.pak", "id1/pak1.pak", "id1/autoexec.cfg"]
ENGINE_PAK = "quakespasm.pak"

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
    glibc = sorted({x.decode() for x in __import__("re").findall(rb"GLIBC_2\.\d+", blob)},
                   key=lambda s: tuple(map(int, s.split("_")[1].split("."))))
    return {"bits": 64, "machine": machine, "needed": needed,
            "glibc": glibc, "interp": interp}


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
            check("rtr=true 且数据随包", attr.get("rtr") is True)
            binary = next((m for m in members
                           if m.startswith(pj["items"][-1] + "/")
                           and Path(m).name.startswith("quakespasm.")), None)
            check("找到 quakespasm.<arch> 二进制", binary is not None, binary or "")
            if binary:
                elf = parse_elf(read_member(src, binary))
                check("是 64 位 ELF", elf and elf["bits"] == 64)
                check("e_machine=183 (AArch64)", elf and elf["machine"] == 183,
                      "machine=%s" % (elf and elf["machine"]))
                check("NEEDED 含 libSDL2-2.0.so.0 与 libGL.so.1",
                      elf and "libSDL2-2.0.so.0" in elf["needed"]
                      and "libGL.so.1" in elf["needed"],
                      str(elf and elf["needed"]))
                maxg = elf["glibc"][-1] if elf and elf["glibc"] else ""
                min_glibc = attr.get("min_glibc", "")
                check("min_glibc 覆盖二进制需求",
                      maxg and min_glibc and
                      tuple(map(int, min_glibc.split("."))) >=
                      tuple(map(int, maxg.split("_")[1].split("."))),
                      "二进制最高 %s / 声明 %s" % (maxg, min_glibc))
            check("引擎 %s 随包" % ENGINE_PAK,
                  any(Path(m).name == ENGINE_PAK for m in members))
            data_prefix = pj["items"][-1].rstrip("/") + "/data/"
            data_files = [m for m in members if m.startswith(data_prefix)]
            check("data/ 至少 1 个数据文件", len(data_files) >= 1, str(len(data_files)))
            for req in REQUIRED_DATA:
                check("data/%s 存在" % req,
                      any(m == data_prefix + req for m in members))
            check("有 gptk 手柄映射",
                  any(m.endswith(".gptk") for m in members))
            check("有截图", any(m.endswith("screenshot.png") for m in members))
            gi = next((m for m in members if m.endswith("gameinfo.xml")), None)
            if gi:
                try:
                    ET.fromstring(read_member(src, gi))
                    check("gameinfo.xml 可解析", True)
                except ET.ParseError as e:
                    check("gameinfo.xml 可解析", False, str(e))
            check("含许可证副本", any("COPYING" in Path(m).name for m in members))
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
