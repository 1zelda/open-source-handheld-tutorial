# -*- coding: utf-8 -*-
"""M1：资产索引 + Profile Registry（依据 _scratch/强模型方案回复.md §5 M1）。

职责：
  * 索引本地已有资产（movie / version 哈希 / ROM），不重复下载。
  * 对每条出版物给出"可回放 / 被阻塞"的解释（阻塞用 M0 错误码）。
  * 对就绪条目生成经 M0 校验的 Profile。

不做：下载、执行回放、猜测 RAM 地址。资料不足 => 标记阻塞留待补。
运行:
  python -m taspipe.registry build      # 全量评估，写 registry.json
  python -m taspipe.registry status     # 只看汇总
  python -m taspipe.registry assess 5246  # 单条解释
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

from .schema import (Profile, Platform, FailureCode, SchemaError, to_dict)

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]                       # F:\开源掌机教程
DEFAULT_LIB = ROOT / "04-游戏资源库" / "TAS输入录像库"
DEFAULT_EMU = ROOT / "02-模拟器库"

# TASVideos 平台码 -> M0 Platform（仅建模已支持的平台；其余如实标"未建模"）
PLATFORM_MAP = {
    "NES": Platform.NES,
    "FDS": Platform.NES,        # Famicom Disk System，BizHawk 走 NesHawk
    "SNES": Platform.SNES,
    "BSX": Platform.SNES,
    "SGB": Platform.SNES,
    "PSX": Platform.PS1,
    "PSP": Platform.PSP,
}


def norm_sha1(s):
    return (s or "").strip().upper()


def load_publications(lib):
    p = Path(lib) / "publications.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    pubs = d["publications"]
    return list(pubs.values()) if isinstance(pubs, dict) else list(pubs)


def index_roms(lib):
    """roms_verify 下所有 ROM 的 SHA-1 -> [path]（bk2 Header / version 页都用 SHA-1）。"""
    import hashlib
    idx = {}
    base = Path(lib) / "roms_verify"
    if not base.is_dir():
        return idx
    for f in base.rglob("*"):
        if f.is_file() and f.suffix.lower() not in (".json", ".txt", ".md"):
            hh = hashlib.sha1()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    hh.update(chunk)
            idx.setdefault(hh.hexdigest().upper(), []).append(str(f))
    return idx


def index_versions(lib):
    """versions/*.json -> {version_id: {sha1, md5, name, ...}}。"""
    idx = {}
    base = Path(lib) / "versions"
    if not base.is_dir():
        return idx
    for f in base.glob("*.json"):
        try:
            v = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        idx[f.stem] = {
            "sha1": norm_sha1(v.get("SHA-1")),
            "md5": (v.get("MD5") or "").strip().upper(),
            "name": v.get("Name", ""),
            "system": v.get("System Code", ""),
        }
    return idx


def discover_bizhawk(emu_root):
    """扫描 BizHawk-<ver>/EmuHawk.exe -> {version: dir}。"""
    out = {}
    base = Path(emu_root) / "BizHawk"
    if not base.is_dir():
        return out
    for d in base.iterdir():
        m = re.fullmatch(r"BizHawk-(.+)", d.name)
        if m and (d / "EmuHawk.exe").is_file():
            out[m.group(1)] = str(d)
    return out


def read_bk2_header(path):
    """读 BizHawk .bk2（zip）的 Header.txt；.zip 外壳则取内部首个 .bk2。

    非 BizHawk 容器返回 None（不臆测）。
    """
    path = str(path)
    try:
        z = zipfile.ZipFile(path)
    except Exception:
        return None
    names = z.namelist()
    header_name = "Header.txt" if "Header.txt" in names else None
    if header_name is None:
        inner = [n for n in names if n.lower().endswith(".bk2")]
        if not inner:
            return None
        try:
            import io
            z = zipfile.ZipFile(io.BytesIO(z.read(inner[0])))
            names = z.namelist()
            header_name = "Header.txt" if "Header.txt" in names else None
        except Exception:
            return None
    if header_name is None:
        return None
    hdr = {}
    for line in z.read(header_name).decode("utf-8", "replace").splitlines():
        if " " in line:
            k, v = line.split(" ", 1)
            hdr[k.strip()] = v.strip()
    return hdr or None


def resolve_movie(pub, lib):
    """定位真正可回放的 movie 文件。

    local_movie 可能是 .zip 外壳；若同目录有同名 .bk2 优先用它。
    FCEUX .fm2/.fcm/.fm3 不能直接回放：查 _converted/<plat>/<id>.bk2 缓存，
    有则用转换件，无则返回 None + 转换提示（阻塞留待补）。
    返回 (path|None, note)。
    """
    rel = pub.get("local_movie")
    if not rel:
        return None, "索引未记录 local_movie（尚未下载）"
    p = Path(lib) / rel
    if not p.is_file():
        return None, f"索引记录的 movie 不存在: {rel}"
    suf = p.suffix.lower()
    if suf in (".fm2", ".fcm", ".fm3"):
        plat = pub.get("platform") or "NES"
        conv = Path(lib) / "_converted" / plat / f"{pub['id']}.bk2"
        if conv.is_file():
            return str(conv), "FCEUX 电影已转换为 .bk2"
        return None, (f"FCEUX {suf} 需先转换："
                      f"python -m taspipe.fceux convert --pub {pub['id']}")
    if suf == ".zip":
        bk2 = p.with_suffix(".bk2")
        if bk2.is_file():
            return str(bk2), "使用已解压的同名 .bk2"
        return str(p), "movie 为 .zip 外壳，回放前需解压内部 .bk2"
    return str(p), ""


def emulator_match(emulator_str, bizhawk_dirs):
    """把 'BizHawk 2.8' 之类映射到本地目录；非 BizHawk 或无匹配返回 None。

    FCEUX 原生管线未接入，但其 .fm2/.fcm 可经 taspipe.fceux 转成 .bk2 走 BizHawk；
    转换后 assess 会改按 bk2 Header 的 emuVersion 匹配本地 BizHawk。
    """
    s = emulator_str or ""
    m = re.match(r"BizHawk\s+([0-9.]+)", s)
    if not m:
        if s.lower().startswith(("fceux", "fceu")):
            return None, ("非 BizHawk 原生管线；FCEUX .fm2/.fcm 可经 taspipe.fceux "
                          "转换为 .bk2 后走本地 BizHawk")
        return None, "非 BizHawk 管线（本 registry 暂未接入）"
    ver = m.group(1)
    if ver in bizhawk_dirs:
        return bizhawk_dirs[ver], ""
    return None, f"本地无 BizHawk {ver}（已有: {', '.join(sorted(bizhawk_dirs)) or '无'}）"


def map_platform(pub, header):
    code = (header or {}).get("Platform") or pub.get("platform", "")
    if code in PLATFORM_MAP:
        return PLATFORM_MAP[code], code, ""
    if code == "Arcade":
        emu = (pub.get("emulator") or "").lower()
        if "mame" in emu:
            return Platform.ARCADE_MAME, code, ""
        if "fbneo" in emu or "finalburn" in emu or "fba" in emu:
            return Platform.ARCADE_FBNEO, code, ""
        return None, code, "Arcade 需先确定 FBNeo/MAME 后端"
    return None, code, f"平台 {code} 尚未在 schema 建模"


def assess(pub, lib, rom_idx, ver_idx, bizhawk_dirs):
    """对单条出版物给出可回放性评估（不执行、不下载）。"""
    pid = pub["id"]
    movie, movie_note = resolve_movie(pub, lib)
    header = read_bk2_header(movie) if movie else None

    plat, plat_code, plat_note = map_platform(pub, header)

    # 所需 ROM 哈希：bk2 Header 优先，其次 version 页
    req_sha1 = norm_sha1((header or {}).get("SHA1"))
    hash_src = "bk2 Header" if req_sha1 else ""
    if not req_sha1:
        v = ver_idx.get(pub.get("version_id", ""))
        if v and v["sha1"]:
            req_sha1 = v["sha1"]
            hash_src = "version 页"
    rom_match = rom_idx.get(req_sha1, []) if req_sha1 else []

    core = (header or {}).get("Core", "")
    emu_ver = (header or {}).get("emuVersion", "")
    emu_str = pub.get("emulator", "")
    # FCEUX 电影一旦转换成 .bk2（resolve_movie 命中 _converted 缓存），
    # 回放走的是 BizHawk：按转换件 Header 的 emuVersion 匹配本地 BizHawk，
    # 而不是原出版物登记的 FCEUX 版本。
    if emu_str.lower().startswith(("fceux", "fceu")) and header and core:
        mv = re.search(r"([0-9][0-9.]*)", emu_ver)
        if mv:
            emu_str = f"BizHawk {mv.group(1)}"
    emu_dir, emu_note = emulator_match(emu_str, bizhawk_dirs)

    blockers = []
    if not movie:
        blockers.append((FailureCode.MISSING_RESOURCE, movie_note))
    if not req_sha1:
        blockers.append((FailureCode.MISSING_RESOURCE,
                         "未知所需 ROM 哈希（version 页未抓取且非 bk2）"))
    elif not rom_match:
        blockers.append((FailureCode.MISSING_RESOURCE,
                         f"无匹配 ROM（需 SHA1={req_sha1}，来源 {hash_src}）"))
    if plat is None:
        blockers.append((FailureCode.UNSUPPORTED_CAPABILITY, plat_note))
    if not emu_dir:
        blockers.append((FailureCode.MISSING_RESOURCE, emu_note))

    status = "replayable" if not blockers else "blocked"
    profile = None
    if status == "replayable":
        try:
            profile = Profile(
                profile_id=f"tasvideos_{pid}",
                game_revision_id=pub.get("version_id") or f"game_{pub.get('game_id')}",
                backend_id="nes_bizhawk" if plat == Platform.NES else f"bizhawk_{plat_code.lower()}",
                platform=plat,
                emulator_fingerprint=emu_ver or pub.get("emulator", ""),
                core=core,
                rom_sha1=req_sha1,
                capability_report={"source": "tasvideos", "movie_ext": pub.get("movie_ext"),
                                   "bizhawk_dir": emu_dir},
            ).validate()
        except SchemaError as e:
            blockers.append((FailureCode.SCHEMA_INVALID, str(e)))
            status = "blocked"

    return {
        "id": pid,
        "game": pub.get("game"),
        "title": pub.get("title"),
        "platform_code": plat_code,
        "status": status,
        "movie": movie,
        "movie_note": movie_note,
        "required_rom_sha1": req_sha1,
        "hash_source": hash_src,
        "rom_match": rom_match,
        "core": core,
        "emulator": pub.get("emulator"),
        "emulator_dir": emu_dir,
        "blockers": [{"code": c.value, "reason": r} for c, r in blockers],
        "profile": to_dict(profile) if profile else None,
    }


def build(lib, emu_root, out=None, only_ready=False):
    pubs = load_publications(lib)
    rom_idx = index_roms(lib)
    ver_idx = index_versions(lib)
    bh = discover_bizhawk(emu_root)
    results = [assess(p, lib, rom_idx, ver_idx, bh) for p in pubs]
    if only_ready:
        results = [r for r in results if r["status"] == "replayable"]
    ready = [r for r in results if r["status"] == "replayable"]
    summary = {
        "total": len(results),
        "replayable": len(ready),
        "blocked": len(results) - len(ready),
        "roms_indexed": sum(len(v) for v in rom_idx.values()),
        "versions_indexed": len(ver_idx),
        "bizhawk_available": sorted(bh),
    }
    doc = {"summary": summary, "assessments": results}
    if out:
        Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    return doc


def _fmt_blockers(r):
    return "; ".join(f"[{b['code']}] {b['reason']}" for b in r["blockers"]) or "无"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["build", "status", "assess"])
    ap.add_argument("pub_id", nargs="?", help="assess 用的出版物 id")
    ap.add_argument("--lib", default=str(DEFAULT_LIB))
    ap.add_argument("--emu", default=str(DEFAULT_EMU))
    ap.add_argument("--out", default=None, help="build 输出 json（默认 lib/registry.json）")
    ap.add_argument("--ready", action="store_true", help="build 只输出可回放条目")
    args = ap.parse_args()

    if args.cmd == "assess":
        if not args.pub_id:
            ap.error("assess 需要 pub_id")
        pubs = {p["id"]: p for p in load_publications(args.lib)}
        if args.pub_id not in pubs:
            print(f"未知出版物 id: {args.pub_id}", file=sys.stderr)
            return 1
        r = assess(pubs[args.pub_id], args.lib, index_roms(args.lib),
                   index_versions(args.lib), discover_bizhawk(args.emu))
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0

    out = args.out or str(Path(args.lib) / "registry.json")
    doc = build(args.lib, args.emu, out if args.cmd == "build" else None,
                only_ready=args.ready)
    s = doc["summary"]
    print(f"总 {s['total']} | 可回放 {s['replayable']} | 阻塞 {s['blocked']}")
    print(f"ROM 索引 {s['roms_indexed']} | version 索引 {s['versions_indexed']} "
          f"| 本地 BizHawk {', '.join(s['bizhawk_available']) or '无'}")
    if args.cmd == "build":
        print(f"已写 {out}")
        for r in doc["assessments"]:
            if r["status"] == "replayable":
                print(f"  [READY] {r['id']} {r['game']} core={r['core']} "
                      f"rom={r['rom_match'][0] if r['rom_match'] else '?'}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())