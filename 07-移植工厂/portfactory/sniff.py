from __future__ import annotations

import os
from collections import Counter
from pathlib import Path


PE_MACHINES = {
    0x014C: "x86",
    0x8664: "x86-64",
    0x01C0: "arm",
    0x01C4: "arm",
    0xAA64: "aarch64",
}

ELF_MACHINES = {
    0x03: "x86",
    0x3E: "x86-64",
    0x28: "arm",
    0xB7: "aarch64",
    0x08: "mips",
    0x14: "ppc",
    0x15: "ppc64",
    0xF3: "riscv",
}

EXEC_EXTS = {".exe", ".dll", ".so", ".elf", ".nro", ".xex", ".xbe", ".dol", ".prx", ".self"}
DATA_EXTS = {".mpq", ".pak", ".dat", ".iso", ".bin", ".cue", ".img", ".chd", ".grp",
             ".pod", ".pk3", ".wad", ".zip", ".7z", ".rar", ".arc", ".pkg"}

DIR_SIGNALS = [
    ({"starcraft.exe", "stardat.mpq", "broodat.mpq", "patch_rt.mpq"}, "疑似星际争霸（文件名信号）"),
    ({"sango2.exe", "san2.exe", "sango2.pak", "sango2.ini"}, "疑似三国群英传2（文件名信号）"),
]


def read_head(path: Path, size: int = 0x9000) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(size)


def sniff_bytes(head: bytes, file_size: int | None = None) -> dict:
    info: dict = {"format": "unknown", "arch": None, "detail": {}}
    if len(head) < 4:
        return info

    if head[:2] == b"MZ" and len(head) >= 0x40:
        pe_off = int.from_bytes(head[0x3C:0x40], "little")
        if 0 < pe_off and pe_off + 6 <= len(head) and head[pe_off:pe_off + 4] == b"PE\0\0":
            machine = int.from_bytes(head[pe_off + 4:pe_off + 6], "little")
            info.update(format="pe", arch=PE_MACHINES.get(machine, f"machine-0x{machine:04x}"))
            info["detail"] = {"pe_offset": pe_off, "machine": f"0x{machine:04x}"}
            return info
        info.update(format="mz-dos", arch="x86")
        return info

    if head[:4] == b"\x7fELF":
        ei_class = head[4]
        ei_data = head[5]
        order = "little" if ei_data == 1 else "big"
        machine = int.from_bytes(head[18:20], order)
        e_type = int.from_bytes(head[16:18], order)
        info.update(format="elf", arch=ELF_MACHINES.get(machine, f"machine-0x{machine:04x}"))
        info["detail"] = {
            "bits": 64 if ei_class == 2 else 32,
            "endian": order,
            "type": {1: "rel", 2: "exec", 3: "dyn", 4: "core"}.get(e_type, str(e_type)),
            "machine": f"0x{machine:04x}",
        }
        return info

    if head[:4] == b"XBEH":
        info.update(format="xbox-xbe", arch="x86")
        return info
    if head[:4] == b"XEX2":
        info.update(format="xbox360-xex", arch="ppc")
        return info

    if len(head) >= 0x14 and head[0x10:0x14] == b"NRO0":
        first = int.from_bytes(head[:4], "little")
        branch = (first & 0xFC000000) == 0x14000000
        info.update(format="switch-nro", arch="aarch64")
        info["detail"] = {
            "magic_at_0x10": "NRO0",
            "entry_branch": branch,
            "size": file_size,
        }
        return info
    if head[:4] == b"PFS0":
        info.update(format="switch-nsp", arch="aarch64")
        return info
    if len(head) >= 0x104 and head[0x100:0x104] == b"HEAD":
        info.update(format="switch-xci", arch="aarch64")
        return info

    if len(head) >= 0x8006 and head[0x8001:0x8006] == b"CD001":
        info.update(format="iso9660", arch=None)
        return info

    if head[:4] == b"\x7fCNT":
        info.update(format="ps4-pkg", arch="x86-64")
        return info
    if head[:4] == b"\x00PBP":
        info.update(format="psp-pbp", arch="mips")
        return info

    if len(head) >= 0x20 and head[0x1C:0x20] == b"\xc2\x33\x9f\x3d":
        info.update(format="gamecube-dol", arch="ppc")
        return info

    if head[:4] == b"PK\x03\x04":
        info.update(format="zip", arch=None)
        return info
    if head[:6] == b"Rar!\x1a\x07":
        info.update(format="rar", arch=None)
        return info
    if head[:6] == b"7z\xbc\xaf\x27\x1c":
        info.update(format="7z", arch=None)
        return info

    return info


def sniff_file(path: Path) -> dict:
    head = read_head(path)
    info = sniff_bytes(head, path.stat().st_size)
    info["path"] = str(path)
    return info


def survey_directory(root: Path, max_files: int = 50000) -> dict:
    ext_counts: Counter[str] = Counter()
    total_size = 0
    file_count = 0
    truncated = False
    largest: list[tuple[int, str]] = []
    executables: list[str] = []
    data_files: list[str] = []
    names: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
        for filename in filenames:
            if file_count >= max_files:
                truncated = True
                break
            full = Path(dirpath) / filename
            try:
                size = full.stat().st_size
            except OSError:
                continue
            rel = str(full.relative_to(root)).replace("\\", "/")
            lower = filename.lower()
            ext = Path(lower).suffix
            ext_counts[ext or "<none>"] += 1
            total_size += size
            file_count += 1
            names.add(lower)
            largest.append((size, rel))
            largest = sorted(largest, reverse=True)[:20]
            if ext in EXEC_EXTS and len(executables) < 100:
                executables.append(rel)
            if ext in DATA_EXTS and len(data_files) < 100:
                data_files.append(rel)
        if truncated:
            break

    signals = []
    for required, label in DIR_SIGNALS:
        hits = sorted(required & names)
        if hits:
            signals.append({"label": label, "evidence": hits, "confidence": "suspected"})

    return {
        "kind": "directory",
        "root": str(root),
        "file_count": file_count,
        "total_size": total_size,
        "truncated": truncated,
        "extensions": dict(ext_counts.most_common(30)),
        "largest": [{"path": p, "size": s} for s, p in largest],
        "executables": executables,
        "data_files": data_files,
        "signals": signals,
        "note": "文件名与扩展名只作线索，游戏身份与版本仍需文件级确认。",
    }
