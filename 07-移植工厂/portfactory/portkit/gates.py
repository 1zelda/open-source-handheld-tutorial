from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import portmaster

ALLOWED_NEEDED = {
    "libSDL2-2.0.so.0", "libSDL2_mixer-2.0.so.0", "libSDL2_image-2.0.so.0",
    "libSDL2_net-2.0.so.0", "libopenal.so.1", "libc.so.6", "libm.so.6",
    "libdl.so.2", "libpthread.so.0", "librt.so.1", "libz.so.1",
    "ld-linux-aarch64.so.1", "libgcc_s.so.1",
}


@dataclass
class Result:
    status: str  # pass / fail / blocked
    detail: dict


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_elf(blob: bytes) -> dict | None:
    if blob[:4] != b"\x7fELF":
        return None
    elf_class = blob[4]  # 1=32 位, 2=64 位
    bits = 32 if elf_class == 1 else 64
    machine = struct.unpack("<H", blob[18:20])[0]
    info = {"bits": bits, "machine": machine, "needed": [], "glibc": [],
            "interp": None, "rpath": []}
    if bits != 64:
        return info
    phoff = struct.unpack("<Q", blob[0x20:0x28])[0]
    phentsize = struct.unpack("<H", blob[0x36:0x38])[0]
    phnum = struct.unpack("<H", blob[0x38:0x3A])[0]
    loads, dyn = [], None
    for i in range(phnum):
        o = phoff + i * phentsize
        t, _fl, off, va, _pa, fs, _ms, _al = struct.unpack("<IIQQQQQQ", blob[o:o + 56])
        if t == 1:
            loads.append((off, va, fs))
        elif t == 2:
            dyn = (off, fs)
        elif t == 3:
            info["interp"] = blob[off:off + fs].split(b"\0")[0].decode()
    if dyn:
        ents = []
        for j in range(0, dyn[1], 16):
            tag, val = struct.unpack("<qQ", blob[dyn[0] + j:dyn[0] + j + 16])
            ents.append((tag, val))
            if tag == 0:
                break
        strtab = next((v for t, v in ents if t == 5), 0)

        def v2o(v: int) -> int:
            for off, va, fs in loads:
                if va <= v < va + fs:
                    return off + (v - va)
            raise ValueError("vaddr not mapped")

        base = v2o(strtab)
        for t, v in ents:
            if t == 1:
                s = base + v
                info["needed"].append(blob[s:blob.index(b"\0", s)].decode())
            elif t in (15, 29):
                s = base + v
                info["rpath"].extend(blob[s:blob.index(b"\0", s)].decode().split(":"))
    info["glibc"] = sorted({x.decode() for x in re.findall(rb"GLIBC_2\.\d+", blob)})
    return info


def _glibc_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.replace("GLIBC_", "").split("."))


# ---------------------------------------------------------------- 单项闸门

def gate_elf(ctx: dict) -> Result:
    artifact = Path(ctx["artifact"])
    if not artifact.is_file():
        return Result("blocked", {"reason": f"产物不存在：{artifact}"})
    elf = parse_elf(artifact.read_bytes())
    if elf is None:
        return Result("fail", {"reason": "产物不是 ELF"})
    target = ctx["target"]
    arch = target.get("arch", "aarch64")
    expect_machine = {"aarch64": 183, "armv7": 40, "x86_64": 62}.get(arch)
    problems = []
    if expect_machine and elf["machine"] != expect_machine:
        problems.append(f"e_machine={elf['machine']} 不是 {arch}")
    if elf["bits"] != 64 and arch != "armv7":
        problems.append(f"{elf['bits']} 位")
    allow = set(target.get("allow_needed") or ALLOWED_NEEDED)
    extra = [n for n in elf["needed"] if n not in allow]
    if extra:
        problems.append(f"依赖不在允许清单：{extra}")
    if target.get("no_libstdcxx", True) and any("libstdc++" in n for n in elf["needed"]):
        problems.append("动态依赖 libstdc++（应静态链 libc++ 或改用静态 C++ 运行库）")
    if elf["rpath"]:
        problems.append(f"残留 RPATH/RUNPATH：{elf['rpath']}")
    declared = target.get("min_glibc")
    if declared:
        top = max(elf["glibc"], key=_glibc_tuple) if elf["glibc"] else None
        if top and _glibc_tuple(top) > _glibc_tuple(declared):
            problems.append(f"glibc 需求 {top} 超过声明 {declared}")
    detail = {"size": artifact.stat().st_size, "sha256": _sha256(artifact),
              "needed": elf["needed"], "min_glibc": declared,
              "glibc": elf["glibc"], "rpath": elf["rpath"]}
    return Result("fail" if problems else "pass",
                  {"problems": problems, **detail})


def gate_no_build_paths(ctx: dict) -> Result:
    artifact = Path(ctx["artifact"])
    if not artifact.is_file():
        return Result("blocked", {"reason": f"产物不存在：{artifact}"})
    needles = ctx["target"].get("build_path_needles") or ["_scratch", "F:/", "/f/"]
    blob = artifact.read_bytes()
    hits = {n: blob.count(n.encode()) for n in needles}
    hits = {k: v for k, v in hits.items() if v}
    return Result("fail" if hits else "pass",
                  {"hits": hits, "needles": needles, "size": len(blob)})


def _zip_members(path: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(path)


def gate_portmaster_layout(ctx: dict) -> Result:
    pkg = Path(ctx["package"])
    if not pkg.is_file():
        return Result("blocked", {"reason": f"包不存在：{pkg}"})
    problems = []
    with _zip_members(pkg) as zf:
        infos = {i.filename: i for i in zf.infolist()}
        names = set(infos)
        scripts = [n for n in names if "/" not in n and n.endswith(".sh")]
        if not scripts:
            problems.append("根目录没有 .sh 启动脚本")
        for script in scripts:
            mode = infos[script].external_attr >> 16
            if not mode & 0o111:
                problems.append(f"{script} 没有可执行位")
            body = zf.read(script).decode("utf-8", "replace")
            if "pm_finish" not in body or "get_controls" not in body:
                problems.append(f"{script} 缺 PortMaster 约定（get_controls/pm_finish）")
        pj = next((n for n in names if n.endswith("/port.json")), None)
        if pj is None:
            problems.append("没有 port.json")
        else:
            data = json.loads(zf.read(pj))
            top = {"version", "name", "items", "items_opt", "attr"}
            attr = {"title", "desc", "inst", "genres", "porter", "image", "rtr",
                    "exp", "runtime", "min_glibc", "reqs", "arch"}
            if not top <= set(data):
                problems.append(f"port.json 顶层缺 {sorted(top - set(data))}")
            if not attr <= set(data.get("attr", {})):
                problems.append(f"attr 缺 {sorted(attr - set(data.get('attr', {})))}")
            roots = {n.split("/")[0] for n in names}
            for item in data.get("items", []):
                if item.rstrip("/") not in roots:
                    problems.append(f"items 指向不存在的条目：{item}")
        if not any(n.endswith("/gameinfo.xml") for n in names):
            problems.append("没有 gameinfo.xml")
    return Result("fail" if problems else "pass",
                  {"problems": problems, "members": len(names),
                   "scripts": sorted(scripts), "sha256": _sha256(pkg)})


def gate_data_policy(ctx: dict) -> Result:
    pkg = Path(ctx["package"])
    spec = ctx["spec"]
    globs = spec.forbidden_globs()
    hits = []
    with _zip_members(pkg) as zf:
        names = zf.namelist()
    for name in names:
        base = name.rsplit("/", 1)[-1].lower()
        if any(fnmatch.fnmatch(base, g) for g in globs):
            hits.append(name)
    problems = []
    if hits:
        problems.append(f"包内出现用户自备数据：{hits[:6]}")
    if spec.data.get("policy") == "user-supplied":
        required = spec.data.get("required", [])
        if not required:
            problems.append("policy=user-supplied 但 data.required 为空（启动脚本无法判断缺数据）")
        else:
            scripts = [n for n in names if "/" not in n and n.endswith(".sh")]
            body = ""
            with _zip_members(pkg) as zf:
                for script in scripts:
                    body += zf.read(script).decode("utf-8", "replace")
            missing = [f for f in required if f.lower() not in body.lower()]
            if missing:
                problems.append(f"启动脚本没有检查这些数据文件：{missing}")
    return Result("fail" if problems else "pass",
                  {"problems": problems, "forbidden": globs, "hits": hits})


def gate_licenses(ctx: dict) -> Result:
    pkg = Path(ctx["package"])
    expected = [Path(p).name for p in ctx["target"].get("package", {}).get("license_files", [])]
    expected += ctx["target"].get("package", {}).get("extra_license_names", [])
    if not expected:
        return Result("fail", {"reason": "spec 没有声明随包许可文件"})
    with _zip_members(pkg) as zf:
        names = {n.rsplit("/", 1)[-1] for n in zf.namelist()}
    missing = sorted(set(expected) - names)
    return Result("fail" if missing else "pass",
                  {"missing": missing, "expected": sorted(set(expected))})


def gate_deterministic_zip(ctx: dict) -> Result:
    pkg = Path(ctx["package"])
    with _zip_members(pkg) as zf:
        infos = zf.infolist()
    stamps = {i.date_time for i in infos}
    names = [i.filename for i in infos]
    problems = []
    if stamps != {portmaster.PACK_EPOCH}:
        problems.append(f"时间戳不统一：{sorted(stamps)[:4]}")
    if names != sorted(names):
        problems.append("条目未按名字排序")
    if len(names) != len(set(names)):
        problems.append("有条目重名")
    return Result("fail" if problems else "pass",
                  {"problems": problems, "entries": len(names),
                   "epoch": list(portmaster.PACK_EPOCH)})


def gate_screenshot(ctx: dict) -> Result:
    pkg = Path(ctx["package"])
    with _zip_members(pkg) as zf:
        name = next((n for n in zf.namelist() if n.rsplit("/", 1)[-1] == "screenshot.png"), None)
        if name is None:
            return Result("fail", {"reason": "包里没有 screenshot.png"})
        head = zf.read(name)[:24]
    ok = head[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", head[16:24]) >= (320, 240)
    return Result("pass" if ok else "fail",
                  {"name": name, "signature": head[:8].hex(),
                   "size": list(struct.unpack(">II", head[16:24])) if len(head) >= 24 else None})


def gate_nro(ctx: dict) -> Result:
    path = Path(ctx["artifact"])
    if not path.is_file():
        return Result("blocked", {"reason": f"产物不存在：{path}"})
    head = path.read_bytes()[:0x20]
    if head[0x10:0x14] != b"NRO0":
        return Result("fail", {"reason": "0x10 处没有 NRO0", "head": head.hex()})
    first = int.from_bytes(head[:4], "little")
    if (first & 0xFC000000) != 0x14000000:
        return Result("fail", {"reason": "首指令不是 ARM64 分支"})
    return Result("pass", {"size": path.stat().st_size, "sha256": _sha256(path)})


GATES = {
    "elf": gate_elf,
    "no_build_paths": gate_no_build_paths,
    "portmaster_layout": gate_portmaster_layout,
    "data_policy": gate_data_policy,
    "licenses": gate_licenses,
    "deterministic_zip": gate_deterministic_zip,
    "screenshot": gate_screenshot,
    "nro": gate_nro,
}
